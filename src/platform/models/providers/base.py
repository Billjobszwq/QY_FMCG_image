"""Adapter 协议、规范化结果与受控 HTTP 层（02 §3）。

纪律：
- 所有结果规范化：provider request ID、model ID、latency、usage、
  retry_after 与稳定错误码。
- usage 缺失不得伪造为 0：字段为 None 且 ``usage_complete=False``。
- 连接只使用 EndpointPolicy 复核过的 pinned IPs（防 DNS rebinding）；
  不自动跟随重定向，重定向目标必须重新通过策略（最多 3 次）。
- Chat 不做自动重试（远端副作用不可回滚）；幂等操作
  （models/embeddings）在连接错误/超时/5xx 时按 max_retries 重试。
- 异常与 repr 必须净化 secret：以当前 lease 值做字面替换。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol

try:  # httpx 属可选依赖组 model-providers；缺失时调用 fail-closed
    import httpx
except ImportError:  # pragma: no cover - 取决于宿主安装
    httpx = None  # type: ignore[assignment]

from src.platform.models.contracts import (
    MODEL_AUTH_FAILED,
    MODEL_CAPABILITY_MISMATCH,
    MODEL_DIMENSION_MISMATCH,
    MODEL_PROVIDER_UNAVAILABLE,
    MODEL_RATE_LIMITED,
    MODEL_TIMEOUT,
    ModelManagementError,
)
from src.platform.models.endpoint_policy import Endpoint, EndpointPolicy

MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_REDIRECTS = 3
_BODY_EXCERPT = 200


# ------------------------------------------------------------------ errors


class ProviderError(ModelManagementError):
    code = MODEL_PROVIDER_UNAVAILABLE
    http_status = 503

    def __init__(self, message: str = "", *,
                 retry_after: float | None = None,
                 provider_request_id: str | None = None) -> None:
        super().__init__(message, retry_after=retry_after)
        self.provider_request_id = provider_request_id


class ProviderAuthFailed(ProviderError):
    code = MODEL_AUTH_FAILED
    http_status = 503  # 平台会话有效、Provider 凭据无效 → 上游不可用


class ProviderRateLimited(ProviderError):
    code = MODEL_RATE_LIMITED
    http_status = 429


class ProviderTimeout(ProviderError):
    code = MODEL_TIMEOUT
    http_status = 503


class ProviderUnavailable(ProviderError):
    code = MODEL_PROVIDER_UNAVAILABLE
    http_status = 503


class ProviderResponseInvalid(ProviderError):
    code = MODEL_PROVIDER_UNAVAILABLE
    http_status = 503


class ProviderDimensionMismatch(ProviderError):
    code = MODEL_DIMENSION_MISMATCH
    http_status = 409


class ProviderCapabilityMismatch(ProviderError):
    code = MODEL_CAPABILITY_MISMATCH
    http_status = 422


# ------------------------------------------------------------------ result


@dataclass(frozen=True)
class Usage:
    """真实 usage；None = Provider 未报告（不得以 0 冒充）。"""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None


@dataclass(frozen=True)
class ProviderModel:
    model_id: str
    revision: str = ""


@dataclass(frozen=True)
class EmbedRequest:
    model_id: str
    inputs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.model_id or not self.inputs:
            raise ValueError("EmbedRequest 需要 model_id 与非空 inputs")
        if any(not isinstance(i, str) for i in self.inputs):
            raise ValueError("inputs 必须是字符串序列")


@dataclass(frozen=True)
class EmbedResult:
    model_id: str
    vectors: tuple[tuple[float, ...], ...]
    dimension: int
    usage: Usage
    usage_complete: bool
    provider_request_id: str
    latency_ms: float


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class ChatRequest:
    model_id: str
    messages: tuple[ChatMessage, ...]
    max_tokens: int = 1024
    temperature: float | None = None

    def __post_init__(self) -> None:
        if not self.model_id or not self.messages:
            raise ValueError("ChatRequest 需要 model_id 与非空 messages")


@dataclass(frozen=True)
class ChatResult:
    model_id: str
    text: str
    finish_reason: str
    usage: Usage
    usage_complete: bool
    provider_request_id: str
    latency_ms: float


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    capability: str
    model_id: str
    dimension: int | None = None
    detail: str = ""


class ModelProviderAdapter(Protocol):
    kind: str

    def list_models(self) -> list[ProviderModel]: ...

    def probe(self, model_id: str, capability: str) -> ProbeResult: ...

    def embed(self, request: EmbedRequest) -> EmbedResult: ...

    def chat(self, request: ChatRequest) -> ChatResult: ...


# ------------------------------------------------------------ http support


def _redact(text: str, secrets: list[bytes]) -> str:
    out = text
    for s in secrets:
        for candidate in {s.decode("utf-8", errors="ignore")}:
            if candidate:
                out = out.replace(candidate, "***")
    return out


def _excerpt(content: bytes, secrets: list[bytes]) -> str:
    sample = content[:_BODY_EXCERPT].decode("utf-8", errors="replace")
    return _redact(sample, secrets)


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict
    content: bytes

    def json_or_none(self) -> Any | None:
        try:
            return json.loads(self.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None


def request_json(
    endpoint: Endpoint,
    method: str,
    path: str,
    *,
    headers: dict[str, str],
    json_body: dict | None,
    timeout_ms: int,
    max_retries: int,
    idempotent: bool,
    secrets: list[bytes],
    policy: EndpointPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> HttpResponse:
    """受控 HTTP：pinned IP 直连、重试预算、重定向复核、响应体上限、
    全链路 secret 净化。"""
    if httpx is None:
        raise ProviderUnavailable(
            "Provider 不可用：未安装 httpx"
            "（可选依赖组 model-providers）")
    pol = policy or EndpointPolicy()
    attempts = (max_retries + 1) if idempotent else 1
    last_error: Exception | None = None
    current_endpoint = endpoint
    current_path = path
    redirects = 0

    for attempt in range(attempts):
        targets = current_endpoint.connect_targets()
        for ip, port in targets:
            url = (f"{current_endpoint.scheme}://{ip}:{port}"
                   f"{current_path}")
            req_headers = dict(headers)
            req_headers.setdefault("Host", current_endpoint.host)
            req_headers.setdefault("Accept", "application/json")
            req_headers.setdefault("User-Agent", "taas-model-mgmt/1.0")
            extensions = {}
            if current_endpoint.scheme == "https":
                extensions["sni_hostname"] = current_endpoint.host
            timeout_s = max(0.05, timeout_ms / 1000.0)
            try:
                with httpx.Client(
                        verify=True, follow_redirects=False,
                        timeout=httpx.Timeout(timeout_s)) as client:
                    resp = client.request(
                        method, url, headers=req_headers,
                        json=json_body if json_body is not None else None,
                        extensions=extensions or None)
            except httpx.TimeoutException as e:
                if not idempotent:
                    raise ProviderTimeout("Provider 超时") from None
                last_error = e
                continue  # 幂等操作允许重试
            except httpx.HTTPError as e:
                if not idempotent:
                    raise ProviderUnavailable(_redact(
                        "Provider 连接失败："
                        f"{type(e).__name__}", secrets)) from None
                last_error = e
                continue

            if len(resp.content) > MAX_RESPONSE_BYTES:
                raise ProviderResponseInvalid(
                    "Provider 响应体超过上限")

            if 300 <= resp.status_code < 400:
                location = resp.headers.get("location", "")
                redirects += 1
                if redirects > MAX_REDIRECTS:
                    raise ProviderResponseInvalid("重定向次数超过上限")
                try:
                    current_endpoint = pol.validate_redirect(
                        location, location=current_endpoint.location)
                except Exception:
                    raise ProviderError(
                        "重定向目标未通过 EndpointPolicy") from None
                current_path = (current_endpoint.path
                                + ("?" + current_endpoint.query
                                   if current_endpoint.query else ""))
                break  # 重新走 attempts 循环

            if resp.status_code == 429:
                retry_after = _parse_retry_after(
                    resp.headers.get("retry-after"))
                raise ProviderRateLimited(
                    "Provider 限流（429）", retry_after=retry_after)
            if resp.status_code in (401, 403):
                raise ProviderAuthFailed(
                    f"Provider 认证失败（{resp.status_code}）")
            if resp.status_code >= 500:
                msg = (f"Provider 错误（{resp.status_code}）："
                       f"{_excerpt(resp.content, secrets)}")
                if not idempotent:
                    raise ProviderUnavailable(msg)
                last_error = ProviderUnavailable(msg)
                continue  # 幂等操作允许重试
            if resp.status_code >= 400:
                raise ProviderResponseInvalid(_redact(
                    f"Provider 拒绝请求（{resp.status_code}）", secrets))

            return HttpResponse(status=resp.status_code,
                                headers=dict(resp.headers),
                                content=resp.content)
        else:
            # 所有 target 都失败
            continue

    # attempts 用尽
    if isinstance(last_error, ProviderError):
        raise last_error
    if isinstance(last_error, httpx.TimeoutException):
        raise ProviderTimeout("Provider 超时") from None
    if last_error is not None:
        raise ProviderUnavailable(_redact(
            f"Provider 连接失败：{type(last_error).__name__}",
            secrets)) from None
    raise ProviderUnavailable("Provider 无可用连接目标")


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
