"""统一模型管理：fail-closed Pydantic 合同与稳定错误码（M2/G1）。

纪律：
- 所有输入模型 ``extra="forbid"``；未知字段、非法枚举、非法范围一律拒绝。
- 凭据只能经 ``SecretSubmit`` 一次性提交（SecretStr），任何 dump/repr/
  JSON 均不回显明文。
- Connection ``config`` 在 V1 只允许空对象：任意 headers/api_key/模板/
  代码都是未知字段而被拒绝（02 §3.1）。
- 错误码为稳定字符串常量，HTTP 语义见 02 §2。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

# ---------------- 稳定错误码（02-API-PROVIDER-AND-SECURITY §2/§8） --------

MODEL_AUTH_FAILED = "MODEL_AUTH_FAILED"
MODEL_ENDPOINT_BLOCKED = "MODEL_ENDPOINT_BLOCKED"
MODEL_DISCOVERY_UNSUPPORTED = "MODEL_DISCOVERY_UNSUPPORTED"
MODEL_CAPABILITY_MISMATCH = "MODEL_CAPABILITY_MISMATCH"
MODEL_DIMENSION_MISMATCH = "MODEL_DIMENSION_MISMATCH"
MODEL_RATE_LIMITED = "MODEL_RATE_LIMITED"
MODEL_TIMEOUT = "MODEL_TIMEOUT"
MODEL_METERING_INCOMPLETE = "MODEL_METERING_INCOMPLETE"
MODEL_BUDGET_EXHAUSTED = "MODEL_BUDGET_EXHAUSTED"
MODEL_SECRET_UNAVAILABLE = "MODEL_SECRET_UNAVAILABLE"
MODEL_PROVIDER_UNAVAILABLE = "MODEL_PROVIDER_UNAVAILABLE"
MODEL_IDENTITY_MISMATCH = "MODEL_IDENTITY_MISMATCH"
MODEL_CAS_CONFLICT = "MODEL_CAS_CONFLICT"
MODEL_STATE_INVALID = "MODEL_STATE_INVALID"

_HTTP_BY_CODE = {
    MODEL_AUTH_FAILED: 401,
    MODEL_ENDPOINT_BLOCKED: 422,
    MODEL_DISCOVERY_UNSUPPORTED: 503,
    MODEL_CAPABILITY_MISMATCH: 422,
    MODEL_DIMENSION_MISMATCH: 409,
    MODEL_RATE_LIMITED: 429,
    MODEL_TIMEOUT: 503,
    MODEL_METERING_INCOMPLETE: 500,
    MODEL_BUDGET_EXHAUSTED: 429,
    MODEL_SECRET_UNAVAILABLE: 503,
    MODEL_PROVIDER_UNAVAILABLE: 503,
    MODEL_IDENTITY_MISMATCH: 409,
    MODEL_CAS_CONFLICT: 409,
    MODEL_STATE_INVALID: 409,
}


class ModelManagementError(Exception):
    """模型管理稳定错误基类：携带稳定错误码与安全 HTTP 语义。

    message 不得包含 secret、Provider 完整响应体或内部堆栈细节。
    """

    code: str = "MODEL_ERROR"
    http_status: int = 500

    def __init__(self, message: str = "", *,
                 retry_after: float | None = None) -> None:
        super().__init__(message or self.code)
        self.retry_after = retry_after

    def safe_payload(self) -> dict:
        payload = {"error_code": self.code, "message": str(self)}
        if self.retry_after is not None:
            payload["retry_after"] = self.retry_after
        return payload


def http_status_for(code: str) -> int:
    return _HTTP_BY_CODE.get(code, 500)


class ContractError(ModelManagementError):
    code = "MODEL_CONTRACT_INVALID"
    http_status = 422


class StateMachineError(ModelManagementError):
    code = MODEL_STATE_INVALID
    http_status = 409


class CasConflictError(ModelManagementError):
    code = MODEL_CAS_CONFLICT
    http_status = 409


class IdentityMismatchError(ModelManagementError):
    """模型/索引身份不匹配（fail-closed，不得跨身份混用）。"""

    code = MODEL_IDENTITY_MISMATCH
    http_status = 409


# ---------------- 枚举 -----------------------------------------------------


class Location(str, Enum):
    local = "local"
    api = "api"


class AdapterKind(str, Enum):
    openai_compatible = "openai_compatible"
    anthropic = "anthropic"


class Capability(str, Enum):
    embedding = "embedding"
    chat = "chat"
    reasoning = "reasoning"
    vision = "vision"
    ocr_text = "ocr_text"
    ocr_boxes = "ocr_boxes"
    rerank = "rerank"


class SubjectKind(str, Enum):
    system_capability = "system_capability"
    module = "module"


CONNECTION_STATUSES = (
    "draft", "testing", "ready", "pending_approval", "active",
    "superseded", "disabled", "rejected", "failed",
)
BINDING_STATUSES = (
    "draft", "validated", "pending_approval", "canary", "active",
    "superseded", "rejected", "failed", "disabled", "rolled_back",
)
PROBE_STATUSES = ("unprobed", "probing", "ready", "failed")
SECRET_STATUSES = ("active", "rotated", "revoked")

ApiFlavor = Literal["", "responses", "chat_completions", "auto"]


# ---------------- 输入合同 --------------------------------------------------


class BaseStrict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConnectionConfig(BaseStrict):
    """Connection 非敏感参数。

    V1 不开放任何自定义字段：任意 headers/api_key/模板/代码/未知字段
    都因 extra='forbid' 被拒绝。确有额外 header 需求时必须进入加密
    Secret payload 并由 adapter allowlist 验证（02 §3.1）。
    """


def _validate_http_url(value: str) -> str:
    if not value or len(value) > 2048:
        raise ValueError("base_url 长度非法（1..2048）")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https"):
        raise ValueError("base_url 仅允许 http/https scheme")
    if not parts.hostname:
        raise ValueError("base_url 缺少 host")
    if parts.username is not None or parts.password is not None:
        raise ValueError("base_url 不得包含 userinfo")
    return value


class ConnectionDraft(BaseStrict):
    name: str = Field(min_length=1, max_length=128)
    location: Location
    adapter_kind: AdapterKind
    api_flavor: ApiFlavor = ""
    base_url: str
    timeout_ms: int = Field(gt=0, le=600_000)
    max_retries: int = Field(ge=0, le=5)
    config: ConnectionConfig = Field(default_factory=ConnectionConfig)

    _url = field_validator("base_url")(_validate_http_url)


class SecretSubmit(BaseStrict):
    """API Key 一次性提交：write-only，dump/repr 永不回显。"""

    secret_value: SecretStr = Field(min_length=1, max_length=8192)


class CatalogManualEntry(BaseStrict):
    model_id: str = Field(min_length=1, max_length=256)
    model_revision: str = Field(default="", max_length=128)
    capabilities: list[Capability] = Field(min_length=1)
    embedding_dimension: int | None = Field(default=None, gt=0)
    normalization_version: str | None = Field(default=None, max_length=32)

    @field_validator("capabilities")
    @classmethod
    def _unique(cls, v: list[Capability]) -> list[Capability]:
        if len(set(v)) != len(v):
            raise ValueError("capabilities 不得重复")
        return v


class FallbackTarget(BaseStrict):
    connection_id: str = Field(min_length=1, max_length=128)
    connection_version: int = Field(ge=1)
    model_id: str = Field(min_length=1, max_length=256)


class BindingDraft(BaseStrict):
    customer_id: str = Field(default="", max_length=128)
    project_id: str = Field(default="", max_length=128)
    subject_kind: SubjectKind
    subject_id: str = Field(min_length=1, max_length=128)
    capability: Capability
    connection_id: str = Field(min_length=1, max_length=128)
    connection_version: int = Field(ge=1)
    model_id: str = Field(min_length=1, max_length=256)
    fallback: list[FallbackTarget] = Field(default_factory=list)


def _validate_as_of(value: str) -> str:
    try:
        datetime.fromisoformat(value)
    except (TypeError, ValueError) as e:
        raise ValueError("as_of 必须是 ISO-8601 时间") from e
    return value


class ResolveRequest(BaseStrict):
    principal_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    customer_id: str = Field(default="", max_length=128)
    project_id: str = Field(default="", max_length=128)
    subject_kind: SubjectKind
    subject_id: str = Field(min_length=1, max_length=128)
    capability: Capability
    as_of: str

    _as_of = field_validator("as_of")(_validate_as_of)
