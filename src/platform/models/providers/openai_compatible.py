"""OpenAI-compatible Adapter：本地 OMLX、OpenAI 与兼容服务（02 §3.1）。

- 固定路径：``/models``、``/embeddings``、``/chat/completions``
  （base path 来自经 EndpointPolicy 验证的 Endpoint，不接受用户自定义路径）。
- 认证：Bearer；密钥经 ``get_secret`` 短租约注入，不存实例字段、不入
  repr/异常。
- api_flavor 在 V1 使用 chat_completions 语义（responses API 留待后续）。
"""
from __future__ import annotations

import time
from typing import Callable

from src.platform.models.endpoint_policy import Endpoint
from src.platform.models.providers.base import (
    ChatMessage,
    ChatRequest,
    ChatResult,
    EmbedRequest,
    EmbedResult,
    ModelProviderAdapter,
    ProbeResult,
    ProviderCapabilityMismatch,
    ProviderDimensionMismatch,
    ProviderError,
    ProviderModel,
    ProviderResponseInvalid,
    Usage,
    request_json,
)


class OpenAICompatibleAdapter:
    """实现 :class:`ModelProviderAdapter` 的 OpenAI-compatible 语义。"""

    kind = "openai_compatible"

    def __init__(self, endpoint: Endpoint, *,
                 get_secret: Callable[[], bytes],
                 timeout_ms: int,
                 max_retries: int,
                 api_flavor: str = "chat_completions",
                 expected_dimension: int | None = None,
                 base_path: str | None = None) -> None:
        self._endpoint = endpoint
        self._get_secret = get_secret
        self._timeout_ms = int(timeout_ms)
        self._max_retries = int(max_retries)
        self._api_flavor = api_flavor
        self._expected_dimension = expected_dimension
        self._base_path = base_path if base_path is not None else endpoint.path

    def __repr__(self) -> str:
        return (f"OpenAICompatibleAdapter(host={self._endpoint.host!r}, "
                f"port={self._endpoint.port}, "
                f"location={self._endpoint.location!r}, "
                f"timeout_ms={self._timeout_ms}, "
                f"max_retries={self._max_retries})")

    # ------------------------------------------------------------- helpers

    def _secret(self) -> bytes:
        value = self._get_secret()
        if isinstance(value, str):
            value = value.encode("utf-8")
        if not value:
            raise ProviderError("secret 租约为空：拒绝调用")
        return value

    def _request(self, method: str, path: str, *,
                 json_body: dict | None, idempotent: bool):
        secret = self._secret()
        headers = {"Authorization": f"Bearer {secret.decode('utf-8')}"}
        resp = request_json(
            self._endpoint, method, self._base_path + path,
            headers=headers, json_body=json_body,
            timeout_ms=self._timeout_ms, max_retries=self._max_retries,
            idempotent=idempotent, secrets=[secret])
        payload = resp.json_or_none()
        if payload is None:
            raise ProviderResponseInvalid("Provider 返回了非 JSON 响应")
        request_id = (resp.headers.get("x-request-id")
                      or str(payload.get("id") or ""))
        return payload, request_id

    # ---------------------------------------------------------------- API

    def list_models(self) -> list[ProviderModel]:
        payload, _ = self._request("GET", "/models", json_body=None,
                                   idempotent=True)
        data = payload.get("data")
        if not isinstance(data, list):
            raise ProviderResponseInvalid("models 响应缺少 data 列表")
        models: list[ProviderModel] = []
        for item in data:
            if isinstance(item, dict) and isinstance(
                    item.get("id"), str) and item["id"]:
                models.append(ProviderModel(model_id=item["id"]))
        return models

    def embed(self, request: EmbedRequest) -> EmbedResult:
        started = time.perf_counter()
        payload, request_id = self._request(
            "POST", "/embeddings",
            json_body={"model": request.model_id,
                       "input": list(request.inputs)},
            idempotent=True)
        data = payload.get("data")
        if not isinstance(data, list):
            raise ProviderResponseInvalid("embeddings 响应缺少 data 列表")
        if len(data) != len(request.inputs):
            raise ProviderResponseInvalid(
                f"向量数量与输入不一致：{len(data)} != {len(request.inputs)}")
        vectors: list[tuple[float, ...]] = []
        dimension: int | None = None
        for item in data:
            vec = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(vec, list) or not all(
                    isinstance(x, (int, float)) and not isinstance(x, bool)
                    for x in vec):
                raise ProviderResponseInvalid("embedding 向量格式非法")
            vec_t = tuple(float(x) for x in vec)
            if dimension is None:
                dimension = len(vec_t)
            elif len(vec_t) != dimension:
                raise ProviderResponseInvalid("同批向量维度不一致")
            vectors.append(vec_t)
        if dimension is None:
            raise ProviderResponseInvalid("embeddings 响应为空")
        if (self._expected_dimension is not None
                and dimension != self._expected_dimension):
            raise ProviderDimensionMismatch(
                f"embedding 维度不符：{dimension} != "
                f"{self._expected_dimension}")
        usage_raw = payload.get("usage")
        usage = Usage(
            input_tokens=_int_or_none(
                usage_raw.get("prompt_tokens")) if isinstance(
                    usage_raw, dict) else None)
        latency = (time.perf_counter() - started) * 1000.0
        return EmbedResult(
            model_id=str(payload.get("model") or request.model_id),
            vectors=tuple(vectors), dimension=dimension, usage=usage,
            usage_complete=isinstance(usage_raw, dict)
            and usage.input_tokens is not None,
            provider_request_id=request_id, latency_ms=latency)

    def chat(self, request: ChatRequest) -> ChatResult:
        started = time.perf_counter()
        body: dict = {
            "model": request.model_id,
            "messages": [{"role": m.role, "content": m.content}
                         for m in request.messages],
            "max_tokens": request.max_tokens,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        payload, request_id = self._request(
            "POST", "/chat/completions", json_body=body, idempotent=False)
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderResponseInvalid("chat 响应缺少 choices")
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") or {}
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise ProviderResponseInvalid("chat 响应缺少消息正文")
        usage_raw = payload.get("usage")
        cached = None
        reasoning = None
        if isinstance(usage_raw, dict):
            details = usage_raw.get("prompt_tokens_details")
            if isinstance(details, dict):
                cached = _int_or_none(details.get("cached_tokens"))
            out_details = usage_raw.get("completion_tokens_details")
            if isinstance(out_details, dict):
                reasoning = _int_or_none(out_details.get("reasoning_tokens"))
        usage = Usage(
            input_tokens=_int_or_none(usage_raw.get("prompt_tokens"))
            if isinstance(usage_raw, dict) else None,
            output_tokens=_int_or_none(usage_raw.get("completion_tokens"))
            if isinstance(usage_raw, dict) else None,
            cached_input_tokens=cached,
            reasoning_tokens=reasoning)
        latency = (time.perf_counter() - started) * 1000.0
        return ChatResult(
            model_id=str(payload.get("model") or request.model_id),
            text=text,
            finish_reason=str(first.get("finish_reason") or ""),
            usage=usage,
            usage_complete=(isinstance(usage_raw, dict)
                            and usage.input_tokens is not None
                            and usage.output_tokens is not None),
            provider_request_id=request_id, latency_ms=latency)

    def probe(self, model_id: str, capability: str) -> ProbeResult:
        try:
            if capability == "embedding":
                result = self.embed(EmbedRequest(model_id=model_id,
                                                 inputs=("probe",)))
                return ProbeResult(ok=True, capability=capability,
                                   model_id=result.model_id,
                                   dimension=result.dimension)
            if capability in ("chat", "reasoning", "vision"):
                result = self.chat(ChatRequest(
                    model_id=model_id,
                    messages=(ChatMessage(role="user", content="probe"),),
                    max_tokens=1))
                return ProbeResult(ok=True, capability=capability,
                                   model_id=result.model_id)
            return ProbeResult(ok=False, capability=capability,
                               model_id=model_id,
                               detail="MODEL_CAPABILITY_MISMATCH")
        except ProviderError as e:
            return ProbeResult(ok=False, capability=capability,
                               model_id=model_id, detail=e.code)


def _int_or_none(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None
