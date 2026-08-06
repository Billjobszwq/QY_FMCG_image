"""VLM-004：客户四档策略（fast/standard/deep/expert）。

红线（规格 2026-08-06 §7）：
- 客户档位与内部阶段分离：档位只限制阶段上限与预算，
  不得用档位名代替 S1–S4 内部阶段语义；
- require_quality_gate 恒 True：任何档位不得绕过质量门禁；
- vlm_concurrency 初期固定 1（sleeping guardian）；
- queue_sla_hours（12/48）是队列业务 SLA，不是单次模型推理 timeout；
- 策略版本化（POLICY_VERSION），run 启动时快照落入 checkpoint，
  运行中配置变化不影响已启动 run；
- 预算耗尽与未知商品必须转人工，不得静默接受。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.modules.fmcg.cascade.contracts import (
    TIERS,
    CascadePolicy,
    RiskDecision,
)

POLICY_VERSION = "cascade-policy.v1"


class PolicyNotFoundError(Exception):
    """未知客户档位（fail-closed，不得回落默认高档）。"""


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TierBudget(_Frozen):
    """档位预算上限（区域数与 VLM token 预算）。"""

    max_regions: int = Field(ge=1)
    max_vlm_input_tokens: int = Field(ge=1)


class ResolvedPolicy(_Frozen):
    """档位完整策略：冻结契约 CascadePolicy + 预算。"""

    policy: CascadePolicy
    budget: TierBudget

    # 透传常用字段，便于 graph/API 直接读取
    @property
    def policy_version(self) -> str:
        return self.policy.policy_version

    @property
    def tier(self) -> str:
        return self.policy.tier

    @property
    def max_stage(self) -> str:
        return self.policy.max_stage

    @property
    def require_quality_gate(self) -> bool:
        return self.policy.require_quality_gate

    @property
    def vlm_concurrency(self) -> int:
        return self.policy.vlm_concurrency

    @property
    def queue_sla_hours(self) -> float:
        return self.policy.queue_sla_hours

    @property
    def max_regions(self) -> int:
        return self.budget.max_regions

    @property
    def max_vlm_input_tokens(self) -> int:
        return self.budget.max_vlm_input_tokens


# 冻结档位表：accept_risk 四档为「阶段内部快/中/深/专家级接受阈值」，
# 数值越小越保守。fast 档不进入 S4，因此不依赖 VLM。
_POLICIES: dict[str, ResolvedPolicy] = {}


def _define(
    tier: str,
    *,
    max_stage: str,
    fast_accept: float,
    medium_accept: float,
    deep_accept: float,
    expert_accept: float,
    queue_sla_hours: float,
    max_regions: int,
    max_vlm_input_tokens: int,
) -> None:
    _POLICIES[tier] = ResolvedPolicy(
        policy=CascadePolicy(
            policy_version=POLICY_VERSION,
            tier=tier,  # type: ignore[arg-type]
            max_stage=max_stage,  # type: ignore[arg-type]
            fast_accept_risk=fast_accept,
            medium_accept_risk=medium_accept,
            deep_accept_risk=deep_accept,
            expert_accept_risk=expert_accept,
            require_quality_gate=True,
            vlm_concurrency=1,
            queue_sla_hours=queue_sla_hours,
        ),
        budget=TierBudget(
            max_regions=max_regions,
            max_vlm_input_tokens=max_vlm_input_tokens,
        ),
    )


_define("fast", max_stage="S1",
        fast_accept=0.10, medium_accept=0.08, deep_accept=0.06, expert_accept=0.05,
        queue_sla_hours=12.0, max_regions=8, max_vlm_input_tokens=1024)
_define("standard", max_stage="S2",
        fast_accept=0.12, medium_accept=0.10, deep_accept=0.08, expert_accept=0.06,
        queue_sla_hours=12.0, max_regions=16, max_vlm_input_tokens=2048)
_define("deep", max_stage="S3",
        fast_accept=0.15, medium_accept=0.12, deep_accept=0.10, expert_accept=0.08,
        queue_sla_hours=48.0, max_regions=32, max_vlm_input_tokens=4096)
_define("expert", max_stage="S4",
        fast_accept=0.18, medium_accept=0.15, deep_accept=0.12, expert_accept=0.10,
        queue_sla_hours=48.0, max_regions=64, max_vlm_input_tokens=8192)


def policy_for(tier: str) -> ResolvedPolicy:
    """按客户档位返回冻结策略；未知档位 fail-closed。"""
    if tier not in _POLICIES:
        raise PolicyNotFoundError(
            f"未知客户档位: {tier!r}（合法值: {', '.join(TIERS)}）"
        )
    return _POLICIES[tier]


def policy_snapshot(policy: ResolvedPolicy) -> dict[str, Any]:
    """run 启动时落入 checkpoint 的不可变快照（JSON 可序列化）。"""
    return {
        "policy_version": policy.policy.policy_version,
        "tier": policy.policy.tier,
        "max_stage": policy.policy.max_stage,
        "policy": policy.policy.model_dump(),
        "budget": policy.budget.model_dump(),
    }


def budget_exhausted_decision(
    policy: ResolvedPolicy, *, reason: str, risk: float = 1.0
) -> RiskDecision:
    """预算耗尽：路由 budget_exhausted → 人工，不得静默接受或继续升级。"""
    return RiskDecision(
        route="budget_exhausted",
        risk=risk,
        next_stage=None,
        calibrator_version="policy",
        reasons=[reason, f"policy_version={policy.policy_version}"],
    )


def unknown_sku_decision(policy: ResolvedPolicy, *, stage: str) -> RiskDecision:
    """未知商品（闭集外/无候选）必须转人工，不得自动建档或 accepted。"""
    return RiskDecision(
        route="human",
        risk=1.0,
        next_stage=None,
        calibrator_version="none",
        reasons=[f"unknown_sku_at_{stage}", f"policy_version={policy.policy_version}"],
    )
