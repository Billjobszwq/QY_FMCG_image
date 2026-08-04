"""W6/M2：平台契约冻结（Asset / Evidence / Audit / Usage）。

规则：
- extra="forbid"：未知字段即破坏性变更，直接拒绝；
- 版本号冻结：升级契约必须显式 bump CONTRACT_VERSION 并补迁移测试；
- 不依赖任何 Domain Pack。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = "1.0.0"


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssetRef(_FrozenContract):
    """内容寻址资产引用（W8 CAS 落库后统一使用；数据库不存路径本体）。"""

    asset_id: str
    sha256: str
    kind: str
    size_bytes: int = Field(ge=0)
    media_type: str | None = None


class EvidenceItem(_FrozenContract):
    role: str
    asset: AssetRef


class EvidenceManifest(_FrozenContract):
    evidence_id: str
    run_id: str
    kind: str
    items: list[EvidenceItem] = Field(default_factory=list)


class AuditRecord(_FrozenContract):
    ts: str
    actor: str
    action: str
    subject_type: str
    subject_id: str
    detail: dict = Field(default_factory=dict)


class UsageRecord(_FrozenContract):
    ts: str
    capability: str
    run_id: str | None = None
    quantity: float
    unit: str
