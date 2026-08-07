"""GLTC-010 红测试：通道评估口径与候选登记（任务书 Task 10）。

- 四 lane 最低评估指标集冻结；
- 只有同口径冻结集 + 完整 error ledger 才能生成 Candidate；
- 训练完成不得修改 CURRENT bundle（publish 分离，本契约层再保险）。
"""
from __future__ import annotations

import pytest

from src.modules.training_control import evaluation as E


class TestFrozenMetricSets:
    def test_lane_metrics_frozen(self):
        m = E.LANE_MIN_METRICS
        assert {"recall_at_fp1", "recall_at_fp3", "iou_050", "iou_075",
                "duplicate_fp", "background_fp", "localization_err"} \
            <= set(m["detector"])
        assert {"top1", "macro_f1", "unknown_far"} <= set(m["classifier"])
        assert {"mask_iou", "boundary_f"} <= set(m["segmenter"])
        assert {"candidate_recall_at_k", "accepted_precision", "coverage",
                "abstain_rate", "registry_escape"} <= set(m["vlm"])

    def test_report_missing_metrics_rejected(self):
        with pytest.raises(E.EvaluationError):
            E.validate_evaluation_report("detector", {"recall_at_fp1": 0.7})

    def test_full_report_with_ledger_accepted(self):
        rep = {k: 0.5 for k in E.LANE_MIN_METRICS["detector"]}
        out = E.validate_evaluation_report(
            "detector", rep, frozen_set_hash="abc",
            error_ledger=[{"kind": "miss", "count": 3}])
        assert out["ok"] is True


class TestCandidateRegistration:
    def test_candidate_requires_frozen_set_and_ledger(self):
        rep = {k: 0.5 for k in E.LANE_MIN_METRICS["classifier"]}
        with pytest.raises(E.EvaluationError):
            E.register_candidate("run1", "classifier", rep,
                                 frozen_set_hash="", error_ledger=[])
        c = E.register_candidate("run1", "classifier", rep,
                                 frozen_set_hash="h" * 8,
                                 error_ledger=[{"kind": "x", "count": 1}])
        assert c["status"] == "CANDIDATE_READY"
        assert c["production_switch"] is False, \
            "candidate 登记绝不切换生产"

    def test_failing_gate_rejects_candidate(self):
        rep = {k: 0.0 for k in E.LANE_MIN_METRICS["vlm"]}
        with pytest.raises(E.EvaluationError):
            E.register_candidate("run2", "vlm", rep,
                                 frozen_set_hash="h" * 8,
                                 error_ledger=[{"kind": "x", "count": 1}],
                                 gate=E.vlm_gate(rep))
