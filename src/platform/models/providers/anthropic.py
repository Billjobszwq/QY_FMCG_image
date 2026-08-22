"""Anthropic 原生 Adapter（02 §3.2）。

- 原生协议：``GET /v1/models``、``POST /v1/messages``；使用 ``x-api-key``
  与固定 ``anthropic-version``。Anthropic 不是 OpenAI-compatible：本适配
  器有独立的请求/响应 parser，不复用 OpenAI 字段改名。
- V1 只声明 chat/reasoning/vision 能力；``embed`` 直接抛
  ProviderCapabilityMismatch，不为 Anthropic 伪造 Embedding 能力。
"""
from __future__ import annotations

import time
from typing import Callable

from src.platform.models.endpoint_policy import Endpoint
from src.platform.models.providers.base import (
    ChatRequest,
    ChatResult,
    EmbedRequest,
    EmbedResult,
    ProbeResult,
    ProviderCapabilityMismatch,
    ProviderError,
    ProviderModel,
    ProviderResponseInvalid,
    Usage,
    request_json,
)

ANTHROPIC_VERSION = "2023-06-01"
_DECLARED_CAPABILITIES = ("chat", "reasoning", "vision")


class AnthropicAdapter:
    kind = "anthropic"

    def __init__(self, endpoint: Endpoint, *,
                 get_secret: Callable[[], bytes],
                 timeout_ms: int,
                 max_retries: int,
                 base_path: str | None = None) -> None:
        self._endpoint = endpoint
        self._get_secret = get_secret
        self._timeout_ms = int(timeout_ms)
        self._max_retries = int(max_retries)
        self._base_path = base_path if base_path is not None else endpoint.path

    def __repr__(self) -> str:
        return (f"AnthropicAdapter(host={self._endpoint.host!r}, "
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
        headers = {
            "x-api-key": secret.decode("utf-8"),
            "anthropic-version": ANTHROPIC_VERSION,
        }
        resp = request_json(
            self._endpoint, method, self._base_path + path,
            headers=headers, json_body=json_body,
            timeout_ms=self._timeout_ms, max_retries=self._max_retries,
            idempotent=idempotent, secrets=[secret])
        payload = resp.json_or_none()
        if payload is None:
            raise ProviderResponseInvalid("Provider 返回了非 JSON 响应")
        request_id = (resp.headers.get("request-id")
                      or str(payload.get("id") or ""))
        return payload, request_id

    # ---------------------------------------------------------------- API

    def list_models(self) -> list[ProviderModel]:
        payload, _ = self._request("GET", "/v1/models", json_body=None,
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
        raise ProviderCapabilityMismatch(
            "Anthropic 不提供 embedding 能力：不得伪造")

    def chat(self, request: ChatRequest) -> ChatResult:
        started = time.perf_counter()
        system_parts = [m.content for m in request.messages
                        if m.role == "system"]
        messages = [{"role": m.role, "content": m.content}
                    for m in request.messages if m.role != "system"]
        body: dict = {
            "model": request.model_id,
            "messages": messages,
            "max_tokens": request.max_tokens,
        }
        if system_parts:
            body["system"] = "\n\n".join(system_parts)
        if request.temperature is not None:
            body["temperature"] = request.temperature
        payload, request_id = self._request(
            "POST", "/v1/messages", json_body=body, idempotent=False)

        content = payload.get("content")
        if not isinstance(content, list):
            raise ProviderResponseInvalid("messages 响应缺少 content")
        text_parts = [block.get("text", "") for block in content
                      if isinstance(block, dict)
                      and block.get("type") == "text"]
        usage_raw = payload.get("usage")
        usage = Usage(
            input_tokens=_int_or_none(usage_raw.get("input_tokens"))
            if isinstance(usage_raw, dict) else None,
            output_tokens=_int_or_none(usage_raw.get("output_tokens"))
            if isinstance(usage_raw, dict) else None,
            cached_input_tokens=_int_or_none(
                usage_raw.get("cache_read_input_tokens"))
            if isinstance(usage_raw, dict) else None)
        latency = (time.perf_counter() - started) * 1000.0
        return ChatResult(
            model_id=str(payload.get("model") or request.model_id),
            text="".join(text_parts),
            finish_reason=str(payload.get("stop_reason") or ""),
            usage=usage,
            usage_complete=(isinstance(usage_raw, dict)
                            and usage.input_tokens is not None
                            and usage.output_tokens is not None),
            provider_request_id=request_id, latency_ms=latency)

    def probe(self, model_id: str, capability: str) -> ProbeResult:
        if capability not in _DECLARED_CAPABILITIES:
            return ProbeResult(ok=False, capability=capability,
                               model_id=model_id,
                               detail="MODEL_CAPABILITY_MISMATCH")
        try:
            result = self.chat(ChatRequest(
                model_id=model_id,
                messages=_probe_messages(), max_tokens=1))
            return ProbeResult(ok=True, capability=capability,
                               model_id=result.model_id)
        except ProviderError as e:
            return ProbeResult(ok=False, capability=capability,
                               model_id=model_id, detail=e.code)


def _probe_messages():
    from src.platform.models.providers.base import ChatMessage
    return (ChatMessage(role="user", content="probe"),)


def _int_or_none(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None
