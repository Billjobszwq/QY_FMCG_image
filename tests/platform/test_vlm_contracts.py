"""VLM-001：FMCG 级联统一契约冻结测试。

口径（实施计划 Task 1 + 设计规格 §5/§6/§9）：
- 全部契约 extra="forbid" + frozen；未知字段/赋值即破坏性变更；
- PredictionEnvelope：accepted 必须携带 sku_id 与 evidence_ids；
  calibrated_risk∈[0,1]；stage 限 S1–S5；
- RiskDecision：NaN/Inf 风险 fail-closed；route 限四值；
- QwenSkuDecision：schema 版本冻结 qwen-sku-decision.v1，
  accepted 必须带 sku_id；闭集外 sku 校验函数拒绝 accepted；
- 平台契约不依赖 Domain Pack 具体模型名。
"""

import pytest
from pydantic import ValidationError

from src.modules.fmcg.cascade.contracts import (
    Candidate,
    CandidateSet,
    CascadePolicy,
    PredictionEnvelope,
    QwenSkuDecision,
    RegionRef,
    RiskDecision,
    assert_sku_within_candidates,
)


def _envelope(**over) -> PredictionEnvelope:
    base = dict(
        prediction_id="p1", run_id="r1", asset_id="a1", region_id="g1",
        stage="S1", model_id="resnet18", model_version="sha",
        registry_version="reg1", policy_version="pol1",
        topk=[Candidate(sku_id="SKU-1", score=0.7)],
        signals={}, calibrated_risk=0.1, decision="accepted",
        sku_id="SKU-1", latency_ms=2.0, evidence_ids=["ev1"],
    )
    base.update(over)
    return PredictionEnvelope(**base)


def test_prediction_rejects_unknown_extra_fields():
    with pytest.raises(ValidationError):
        PredictionEnvelope(
            prediction_id="p1", run_id="r1", asset_id="a1", region_id="g1",
            stage="S1", model_id="resnet18", model_version="sha",
            registry_version="reg1", policy_version="pol1",
            topk=[Candidate(sku_id="SKU-1", score=0.7)],
            signals={}, calibrated_risk=0.1, decision="accepted",
            latency_ms=2.0, evidence_ids=[], unexpected=True,
        )


def test_accepted_requires_sku_and_evidence():
    with pytest.raises(ValidationError):
        PredictionEnvelope(
            prediction_id="p1", run_id="r1", asset_id="a1", region_id="g1",
            stage="S1", model_id="resnet18", model_version="sha",
            registry_version="reg1", policy_version="pol1", topk=[], signals={},
            calibrated_risk=0.1, decision="accepted", latency_ms=2.0,
            evidence_ids=[],
        )


def test_envelope_is_frozen():
    env = _envelope()
    with pytest.raises(ValidationError):
        env.decision = "needs_review"


def test_stage_limited_to_s1_s5():
    with pytest.raises(ValidationError):
        _envelope(stage="S6")
    with pytest.raises(ValidationError):
        _envelope(stage="S0")


def test_decision_vocab_frozen():
    assert _envelope().decision == "accepted"
    for d in ("needs_review", "unknown", "new_package"):
        ev = _envelope(decision=d, sku_id=None, evidence_ids=[])
        assert ev.decision == d
    with pytest.raises(ValidationError):
        _envelope(decision="rejected")


def test_calibrated_risk_bounds():
    with pytest.raises(ValidationError):
        _envelope(calibrated_risk=1.5)
    with pytest.raises(ValidationError):
        _envelope(calibrated_risk=-0.1)


def test_region_ref_geometry():
    r = RegionRef(region_id="g1", asset_id="a1", sha256="ab" * 32,
                  box_px=(1.0, 2.0, 10.0, 20.0),
                  image_width=100, image_height=200)
    assert r.box_px == (1.0, 2.0, 10.0, 20.0)
    with pytest.raises(ValidationError):
        RegionRef(region_id="g1", asset_id="a1", sha256="x",
                  box_px=(10.0, 2.0, 1.0, 20.0),  # 退化框
                  image_width=100, image_height=200)
    with pytest.raises(ValidationError):
        RegionRef(region_id="g1", asset_id="a1", sha256="x",
                  box_px=(1.0, 2.0, 10.0, 20.0),
                  image_width=0, image_height=200)


def test_candidate_set_registry_version_required():
    cs = CandidateSet(candidate_set_id="c1", region_id="g1",
                      registry_version="reg1", retrieval_version="ret1",
                      candidates=[Candidate(sku_id="SKU-1", score=0.8)])
    assert len(cs.candidates) == 1
    with pytest.raises(ValidationError):
        CandidateSet(candidate_set_id="c1", region_id="g1",
                     retrieval_version="ret1", candidates=[])


def test_risk_decision_rejects_nan_and_inf():
    with pytest.raises(ValidationError):
        RiskDecision(route="accept", risk=float("nan"),
                     calibrator_version="bootstrap_rule_v1",
                     reasons=[])
    with pytest.raises(ValidationError):
        RiskDecision(route="accept", risk=float("inf"),
                     calibrator_version="bootstrap_rule_v1",
                     reasons=[])


def test_risk_decision_route_vocab():
    for route in ("accept", "escalate", "human", "budget_exhausted"):
        rd = RiskDecision(route=route, risk=0.5,
                          calibrator_version="bootstrap_rule_v1",
                          reasons=["r"])
        assert rd.route == route
    with pytest.raises(ValidationError):
        RiskDecision(route="skip", risk=0.5,
                     calibrator_version="bootstrap_rule_v1", reasons=[])
    with pytest.raises(ValidationError):
        RiskDecision(route="accept", risk=0.5, calibrator_version="",
                     reasons=["r"])  # 缺校准版本 fail-closed


def test_cascade_policy_tiers():
    p = CascadePolicy(policy_version="pol1", tier="fast", max_stage="S1",
                      fast_accept_risk=0.2, medium_accept_risk=0.35,
                      deep_accept_risk=0.5, expert_accept_risk=0.65)
    assert p.require_quality_gate is True
    assert p.vlm_concurrency == 1
    with pytest.raises(ValidationError):
        CascadePolicy(policy_version="pol1", tier="gold", max_stage="S1",
                      fast_accept_risk=0.2, medium_accept_risk=0.35,
                      deep_accept_risk=0.5, expert_accept_risk=0.65)
    with pytest.raises(ValidationError):
        CascadePolicy(policy_version="pol1", tier="fast", max_stage="S9",
                      fast_accept_risk=0.2, medium_accept_risk=0.35,
                      deep_accept_risk=0.5, expert_accept_risk=0.65)


def test_qwen_decision_schema_frozen():
    d = QwenSkuDecision(
        schema_version="qwen-sku-decision.v1", decision="accepted",
        sku_id="SKU-1", candidate_id="SKU-1", attributes={},
        conflicts=[], evidence=["ev1"], abstain_reason=None,
    )
    assert d.decision == "accepted"
    with pytest.raises(ValidationError):
        QwenSkuDecision(schema_version="qwen-sku-decision.v2",
                        decision="accepted", sku_id="SKU-1")
    # accepted 必须带 sku_id
    with pytest.raises(ValidationError):
        QwenSkuDecision(schema_version="qwen-sku-decision.v1",
                        decision="accepted", sku_id=None)
    # decision 词汇冻结
    with pytest.raises(ValidationError):
        QwenSkuDecision(schema_version="qwen-sku-decision.v1",
                        decision="approved", sku_id="SKU-1")


def test_qwen_decision_outside_candidate_set_rejected():
    cs = CandidateSet(candidate_set_id="c1", region_id="g1",
                      registry_version="reg1", retrieval_version="ret1",
                      candidates=[Candidate(sku_id="SKU-1", score=0.8)])
    d = QwenSkuDecision(schema_version="qwen-sku-decision.v1",
                        decision="accepted", sku_id="SKU-999",
                        candidate_id="SKU-999")
    with pytest.raises(ValueError):
        assert_sku_within_candidates(d, cs)
    ok = QwenSkuDecision(schema_version="qwen-sku-decision.v1",
                         decision="accepted", sku_id="SKU-1",
                         candidate_id="SKU-1")
    assert_sku_within_candidates(ok, cs)
    # abstain 不受候选约束
    abst = QwenSkuDecision(schema_version="qwen-sku-decision.v1",
                           decision="unknown", sku_id=None,
                           abstain_reason="blurry")
    assert_sku_within_candidates(abst, cs)
