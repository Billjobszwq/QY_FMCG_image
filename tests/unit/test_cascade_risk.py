"""VLM-005：级联风险校准路由（禁止跨模型原始置信度直连）TDD。

红线：
- 没有校准器时 raw confidence 不得路由（CalibrationUnavailable）；
- 硬属性冲突（OCR/属性不一致）强制升级到 S4；
- NaN/Inf/缺关键字段/未识别 stage 一律转人工或受控错误，不得 accepted；
- 校准器只读取冻结 JSON 制品并验证 SHA；bootstrap_rule_v1 是规则启发式，
  不得声称是概率校准。
"""

from __future__ import annotations

import hashlib
import json
import math

import pytest

from src.modules.fmcg.cascade.policy import policy_for
from src.modules.fmcg.cascade.risk import (
    Calibrator,
    CalibrationUnavailable,
    CalibratorTamperedError,
    RiskComputationError,
    bootstrap_rule_v1,
    decide_risk,
    load_calibrator,
)


@pytest.fixture()
def calibrator() -> Calibrator:
    return bootstrap_rule_v1()


# ---------- 无校准器 fail-closed ----------

def test_raw_confidence_cannot_route_without_calibrator() -> None:
    with pytest.raises(CalibrationUnavailable):
        decide_risk(stage="S1", signals={"top1": 0.99}, calibrator=None,
                    policy=policy_for("expert"))


# ---------- 硬冲突强制升级 ----------

def test_hard_attribute_conflict_forces_escalation(calibrator) -> None:
    d = decide_risk(
        stage="S3",
        signals={"top1": 0.96, "margin": 0.7,
                 "ocr_conflicts": ["volume_ml:500!=600"]},
        calibrator=calibrator,
        policy=policy_for("expert"),
    )
    assert d.route == "escalate"
    assert d.next_stage == "S4"
    assert any("conflict" in r for r in d.reasons)


def test_hard_conflict_at_s4_goes_human(calibrator) -> None:
    d = decide_risk(
        stage="S4",
        signals={"top1": 0.96, "margin": 0.7,
                 "ocr_conflicts": ["volume_ml:500!=600"]},
        calibrator=calibrator,
        policy=policy_for("expert"),
    )
    assert d.route == "human"
    assert d.next_stage is None


def test_hard_conflict_respects_tier_max_stage(calibrator) -> None:
    """deep 档 max_stage=S3：S3 出现硬冲突不得升级进 S4，必须转人工。"""
    d = decide_risk(
        stage="S3",
        signals={"top1": 0.96, "margin": 0.7,
                 "ocr_conflicts": ["flavor:桂花!=茉莉"]},
        calibrator=calibrator,
        policy=policy_for("deep"),
    )
    assert d.route == "human"
    assert d.next_stage is None


# ---------- 常规校准路由 ----------

def test_high_confidence_low_risk_accepts(calibrator) -> None:
    d = decide_risk(
        stage="S1",
        signals={"top1": 0.99, "margin": 0.9, "entropy": 0.01},
        calibrator=calibrator, policy=policy_for("fast"),
    )
    assert d.route == "accept"
    assert d.next_stage is None
    assert 0.0 <= d.risk <= 1.0
    assert d.calibrator_version == "bootstrap_rule_v1"


def test_low_confidence_escalates_within_policy(calibrator) -> None:
    d = decide_risk(
        stage="S1",
        signals={"top1": 0.35, "margin": 0.02, "entropy": 1.8},
        calibrator=calibrator, policy=policy_for("expert"),
    )
    assert d.route == "escalate"
    assert d.next_stage == "S2"


def test_escalation_capped_by_tier_max_stage(calibrator) -> None:
    """standard 档 max_stage=S2：S2 低风险不足时不得进 S3，转人工。"""
    d = decide_risk(
        stage="S2",
        signals={"top1": 0.30, "margin": 0.01, "entropy": 1.9},
        calibrator=calibrator, policy=policy_for("standard"),
    )
    assert d.route == "human"
    assert d.next_stage is None


# ---------- NaN / Inf / 缺字段 / 非法 stage fail-closed ----------

def test_nan_signal_never_accepted(calibrator) -> None:
    d = decide_risk(
        stage="S1", signals={"top1": float("nan"), "margin": 0.9},
        calibrator=calibrator, policy=policy_for("expert"),
    )
    assert d.route != "accept"
    assert d.route == "human"


def test_inf_signal_never_accepted(calibrator) -> None:
    d = decide_risk(
        stage="S1", signals={"top1": 0.99, "margin": math.inf},
        calibrator=calibrator, policy=policy_for("expert"),
    )
    assert d.route == "human"


def test_missing_top1_fail_closed(calibrator) -> None:
    d = decide_risk(
        stage="S1", signals={"margin": 0.9},
        calibrator=calibrator, policy=policy_for("expert"),
    )
    assert d.route == "human"


def test_unknown_stage_raises_controlled_error(calibrator) -> None:
    with pytest.raises(RiskComputationError):
        decide_risk(stage="S9", signals={"top1": 0.99},
                    calibrator=calibrator, policy=policy_for("expert"))


# ---------- 校准器制品：冻结 JSON + SHA ----------

def test_bootstrap_calibrator_is_rule_not_probability() -> None:
    c = bootstrap_rule_v1()
    assert c.calibrator_version == "bootstrap_rule_v1"
    assert c.kind == "bootstrap_rule"  # 明确标注：不是概率校准


def test_load_calibrator_verifies_sha(tmp_path) -> None:
    payload = {
        "calibrator_version": "bootstrap_rule_v1",
        "kind": "bootstrap_rule",
        "params": {"w_top1": 0.6, "w_margin": 0.25, "w_entropy": 0.15,
                   "entropy_norm": 2.0},
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    path = tmp_path / "calibrator.json"
    path.write_bytes(blob)
    sha = hashlib.sha256(blob).hexdigest()

    c = load_calibrator(path, expected_sha256=sha)
    assert c.calibrator_version == "bootstrap_rule_v1"

    with pytest.raises(CalibratorTamperedError):
        load_calibrator(path, expected_sha256="0" * 64)


def test_load_missing_calibrator_raises(tmp_path) -> None:
    with pytest.raises(CalibrationUnavailable):
        load_calibrator(tmp_path / "nope.json", expected_sha256="0" * 64)
