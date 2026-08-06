"""VLM-001：FMCG 级联统一契约（冻结，extra=forbid + frozen）。

口径（2026-08-06 级联设计规格 §5/§6/§9 + 实施计划 Task 1）：
- 所有识别阶段统一输出 PredictionEnvelope；raw score 不得跨模型路由，
  只有 calibrated_risk 才能路由；缺模型版本/校准版本/证据 fail-closed；
- accepted 必须携带 sku_id 与 evidence_ids；
- Qwen 输出契约 qwen-sku-decision.v1：闭集重排/裁决，sku 不在
  CandidateSet 内不得 accepted；
- 契约升级必须显式 bump SCHEMA 版本并补迁移测试。
"""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION_PREDICTION = "prediction-envelope.v1"
SCHEMA_VERSION_QWEN_DECISION = "qwen-sku-decision.v1"

STAGES = ("S1", "S2", "S3", "S4", "S5")
DECISIONS = ("accepted", "needs_review", "unknown", "new_package")
ROUTES = ("accept", "escalate", "human", "budget_exhausted")
TIERS = ("fast", "standard", "deep", "expert")
QWEN_DECISIONS = ("accepted", "unknown", "same_sku_new_package",
                  "possible_new_sku", "insufficient_evidence")


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Candidate(_Frozen):
    """候选 SKU（必须来自 SKU Registry；score 为模型原始分，不得当概率承诺）。"""

    sku_id: str
    score: float
    source: str = "model"


class RegionRef(_Frozen):
    """图像区域引用：原始像素框 + 图像宽高 + 原图 SHA（不存路径本体）。"""

    region_id: str
    asset_id: str
    sha256: str
    box_px: tuple[float, float, float, float]
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)

    @model_validator(mode="after")
    def _box_valid(self) -> "RegionRef":
        x1, y1, x2, y2 = self.box_px
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"region 框退化: {self.box_px}")
        if x1 < 0 or y1 < 0 or x2 > self.image_width or y2 > self.image_height:
            raise ValueError(f"region 框越界: {self.box_px}")
        return self


class PredictionEnvelope(_Frozen):
    """统一识别输出（§5.1）。calibrated_risk∈[0,1] 才能用于跨模型路由。"""

    schema_version: str = SCHEMA_VERSION_PREDICTION
    prediction_id: str
    run_id: str
    asset_id: str
    region_id: str
    stage: Literal["S1", "S2", "S3", "S4", "S5"]
    model_id: str
    model_version: str
    registry_version: str
    policy_version: str
    topk: list[Candidate]
    signals: dict[str, Any]
    calibrated_risk: float = Field(ge=0.0, le=1.0)
    decision: Literal["accepted", "needs_review", "unknown", "new_package"]
    sku_id: str | None = None
    package_version_id: str | None = None
    abstain_reason: str | None = None
    latency_ms: float = Field(ge=0.0)
    evidence_ids: list[str]

    @model_validator(mode="after")
    def accepted_has_identity_and_evidence(self) -> "PredictionEnvelope":
        if self.decision == "accepted" and (
                not self.sku_id or not self.evidence_ids):
            raise ValueError("accepted requires sku_id and evidence")
        return self


class CandidateSet(_Frozen):
    """检索召回的闭集候选（全部必须来自 registry；版本必填）。"""

    candidate_set_id: str
    region_id: str
    registry_version: str
    retrieval_version: str
    candidates: list[Candidate]


class RiskDecision(_Frozen):
    """校准风险路由决策（§6）。NaN/Inf/缺校准版本一律 fail-closed。"""

    route: Literal["accept", "escalate", "human", "budget_exhausted"]
    risk: float = Field(ge=0.0, le=1.0)
    next_stage: Literal["S1", "S2", "S3", "S4", "S5"] | None = None
    calibrator_version: str = Field(min_length=1)
    reasons: list[str]

    @model_validator(mode="after")
    def _risk_finite(self) -> "RiskDecision":
        if not math.isfinite(self.risk):
            raise ValueError(f"risk 必须为有限数: {self.risk}")
        return self


class CascadePolicy(_Frozen):
    """客户档位策略（fast/standard/deep/expert）。运行中冻结入 checkpoint。"""

    policy_version: str
    tier: Literal["fast", "standard", "deep", "expert"]
    max_stage: Literal["S1", "S2", "S3", "S4", "S5"]
    fast_accept_risk: float = Field(ge=0.0, le=1.0)
    medium_accept_risk: float = Field(ge=0.0, le=1.0)
    deep_accept_risk: float = Field(ge=0.0, le=1.0)
    expert_accept_risk: float = Field(ge=0.0, le=1.0)
    require_quality_gate: bool = True
    vlm_concurrency: int = Field(default=1, ge=1)
    queue_sla_hours: float = Field(default=48.0, gt=0.0)


class QwenSkuDecision(_Frozen):
    """qwen-sku-decision.v1（§9）。Qwen 只做闭集裁决，不得自由生成 accepted。"""

    schema_version: Literal["qwen-sku-decision.v1"]
    decision: Literal["accepted", "unknown", "same_sku_new_package",
                      "possible_new_sku", "insufficient_evidence"]
    sku_id: str | None = None
    package_version_id: str | None = None
    candidate_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    conflicts: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    abstain_reason: str | None = None

    @model_validator(mode="after")
    def accepted_requires_sku(self) -> "QwenSkuDecision":
        if self.decision == "accepted" and not self.sku_id:
            raise ValueError("qwen accepted requires sku_id")
        return self


def assert_sku_within_candidates(
    decision: QwenSkuDecision, candidate_set: CandidateSet
) -> None:
    """闭集守卫：accepted 的 sku 必须在 CandidateSet 内，否则拒绝（红线）。

    abstain/unknown/新包装等非 accepted 结论不受候选约束。
    """
    if decision.decision != "accepted":
        return
    ids = {c.sku_id for c in candidate_set.candidates}
    if decision.sku_id not in ids:
        raise ValueError(
            f"sku 不在候选闭集内，不得 accepted: {decision.sku_id!r}"
            f"（候选 {sorted(ids)}）"
        )
