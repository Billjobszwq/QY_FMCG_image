"""VLM-004：客户四档策略（fast/standard/deep/expert）TDD。

红线：
- 客户档位只限制预算与阶段上限，不得绕过安全门禁（require_quality_gate 恒 True）；
- 客户档位名称不得代替内部 S1–S4 阶段语义；
- 策略必须版本化，可落入 run checkpoint；运行中配置变化不得改变已启动 run。
"""

from __future__ import annotations

import json

import pytest

from src.modules.fmcg.cascade.contracts import TIERS, RiskDecision
from src.modules.fmcg.cascade.policy import (
    POLICY_VERSION,
    PolicyNotFoundError,
    budget_exhausted_decision,
    policy_for,
    policy_snapshot,
    unknown_sku_decision,
)


# ---------- 四档冻结值 ----------

def test_customer_tiers_limit_stage_without_bypassing_safety() -> None:
    fast = policy_for("fast")
    expert = policy_for("expert")
    assert fast.max_stage == "S1"
    assert expert.max_stage == "S4"
    assert fast.require_quality_gate is True
    assert expert.require_quality_gate is True
    assert expert.vlm_concurrency == 1


def test_all_four_tiers_defined_with_frozen_vocabulary() -> None:
    assert set(TIERS) == {"fast", "standard", "deep", "expert"}
    for tier in TIERS:
        p = policy_for(tier)
        assert p.tier == tier
        assert p.require_quality_gate is True
        assert p.vlm_concurrency == 1
        assert p.queue_sla_hours in (12, 48)


def test_max_stage_is_monotone_across_tiers() -> None:
    order = ["fast", "standard", "deep", "expert"]
    stages = [policy_for(t).max_stage for t in order]
    assert stages == sorted(stages)
    assert stages[0] == "S1"
    assert stages[-1] == "S4"
    # 阶段值必须是内部 S 阶段，不是档位名
    for s in stages:
        assert s.startswith("S")


def test_accept_risk_thresholds_are_valid_and_ordered() -> None:
    for tier in ("fast", "standard", "deep", "expert"):
        cp = policy_for(tier).policy
        thresholds = (
            cp.fast_accept_risk, cp.medium_accept_risk,
            cp.deep_accept_risk, cp.expert_accept_risk,
        )
        for r in thresholds:
            assert 0.0 <= r <= 1.0
        # 接受阈值递减：越深的裁决要求越低风险才接受
        assert thresholds == tuple(sorted(thresholds, reverse=True))


def test_budget_limits_defined_per_tier() -> None:
    for tier in TIERS:
        p = policy_for(tier)
        assert p.max_regions >= 1
        assert p.max_vlm_input_tokens >= 1


def test_fast_tier_never_reaches_vlm_stage() -> None:
    assert policy_for("fast").max_stage < "S4"
    assert policy_for("standard").max_stage < "S4"


# ---------- 未知档位 fail-closed ----------

def test_unknown_tier_raises_fail_closed() -> None:
    with pytest.raises(PolicyNotFoundError):
        policy_for("vip")


# ---------- 版本化与 checkpoint ----------

def test_policy_is_versioned_and_snapshottable() -> None:
    p = policy_for("expert")
    assert p.policy_version == POLICY_VERSION
    snap = policy_snapshot(p)
    assert snap["policy_version"] == POLICY_VERSION
    assert snap["tier"] == "expert"
    # 快照 JSON 可序列化且可重建（落入 checkpoint 后可恢复）
    rebuilt = json.loads(json.dumps(snap))
    assert rebuilt["max_stage"] == p.max_stage


def test_policy_is_frozen_immutable() -> None:
    p = policy_for("fast")
    with pytest.raises(Exception):
        p.max_stage = "S4"  # type: ignore[misc]


# ---------- 预算耗尽与未知商品必须转人工 ----------

def test_budget_exhausted_routes_to_human() -> None:
    d = budget_exhausted_decision(policy_for("fast"), reason="max_regions_exceeded")
    assert isinstance(d, RiskDecision)
    assert d.route == "budget_exhausted"
    assert d.next_stage is None
    assert "max_regions_exceeded" in d.reasons


def test_unknown_sku_must_go_to_human() -> None:
    d = unknown_sku_decision(policy_for("expert"), stage="S1")
    assert d.route == "human"
    assert d.next_stage is None
    assert d.calibrator_version == "none"
