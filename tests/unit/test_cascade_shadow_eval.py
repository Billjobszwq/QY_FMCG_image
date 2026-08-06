"""Cascade shadow 评估计算测试（计划 §Task 17）。

锁定行为：
- accepted precision 与 coverage 必须同时报告（缺一即不可晋级）；
- 检测使用 truebox one-to-one 匹配（IoU 降序贪心，GT/pred 各至多一次）；
- 重复框、背景误检、拒识、错分、新包装、unknown、人工率、延迟、成本
  全部进入逐实例账本；
- 四套对照 E0/E1/C1/C2 共享同一 frozen data、region matching 与 SKU Registry；
- 没有足够人工真值 → not_evaluable，绝不得产生 pass；
- 真实执行门禁：存在活跃训练 → BLOCKED_BY_ACTIVE_TRAINING（fail-closed）。

测试只覆盖纯计算与门禁逻辑，不加载任何模型、不运行真实推理。
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from src.eval.cascade_shadow import (
    ARM_IDS,
    LEDGER_LABELS,
    build_ledger,
    define_arms,
    evaluate_arm,
    match_one_to_one,
    promotion_gate,
    shadow_execution_gate,
    validate_arms,
)


def _truth(box, sku, verified=True):
    return {"box": box, "sku_id": sku, "human_verified": verified}


def _pred(box, sku, status="accepted", latency_ms=10.0, cost=0.01):
    return {"box": box, "sku_id": sku, "status": status,
            "latency_ms": latency_ms, "cost": cost}


def _record(photo_id="p1", truths=(), preds=(), human_routed=False):
    return {"photo_id": photo_id, "sha256": f"sha-{photo_id}",
            "truths": list(truths), "predictions": list(preds),
            "human_routed": human_routed}


# ---------------------------------------------------------------- matching


class TestOneToOneMatching:
    def test_higher_iou_wins(self):
        truths = [_truth([0, 0, 10, 10], "a")]
        preds = [_pred([0, 0, 10.5, 10.5], "a"), _pred([0, 0, 10, 10], "a")]
        pairs = match_one_to_one(truths, preds, iou_threshold=0.5)
        assert len(pairs) == 1
        assert pairs[0][1] == 1  # 完全重合的 pred 胜出

    def test_truth_matched_at_most_once(self):
        truths = [_truth([0, 0, 10, 10], "a")]
        preds = [_pred([0, 0, 10, 10], "a"), _pred([0, 0, 10, 10], "a")]
        pairs = match_one_to_one(truths, preds, iou_threshold=0.5)
        assert len(pairs) == 1

    def test_below_threshold_not_matched(self):
        truths = [_truth([0, 0, 10, 10], "a")]
        preds = [_pred([8, 8, 18, 18], "a")]  # IoU 远低于阈值
        assert match_one_to_one(truths, preds, iou_threshold=0.5) == []


# ---------------------------------------------------------------- ledger


class TestBuildLedger:
    def test_correct_accepted_and_misclassification(self):
        rec = _record(
            truths=[_truth([0, 0, 10, 10], "sku-a"),
                    _truth([20, 20, 30, 30], "sku-b")],
            preds=[_pred([0, 0, 10, 10], "sku-a"),
                   _pred([20, 20, 30, 30], "sku-x")])
        labels = [e["label"] for e in build_ledger(rec)]
        assert "correct_accepted" in labels
        assert "misclassification" in labels

    def test_duplicate_box_and_background_fp(self):
        rec = _record(
            truths=[_truth([0, 0, 10, 10], "sku-a")],
            preds=[_pred([0, 0, 10, 10], "sku-a"),
                   _pred([0.5, 0.5, 10.5, 10.5], "sku-a"),  # 与已配对方重叠
                   _pred([100, 100, 110, 110], "sku-z")])   # 背景
        labels = [e["label"] for e in build_ledger(rec)]
        assert labels.count("duplicate_box") == 1
        assert labels.count("background_fp") == 1

    def test_abstain_unknown_new_package_manual_labels(self):
        rec = _record(
            truths=[_truth([0, 0, 10, 10], "sku-a")],
            preds=[_pred([0, 0, 10, 10], None, status="abstain"),
                   _pred([20, 20, 30, 30], None, status="unknown"),
                   _pred([40, 40, 50, 50], None, status="new_package"),
                   _pred([60, 60, 70, 70], None, status="manual_review")])
        labels = [e["label"] for e in build_ledger(rec)]
        for want in ("abstain", "unknown", "new_package", "manual_review"):
            assert want in labels

    def test_missed_truth_recorded(self):
        rec = _record(truths=[_truth([0, 0, 10, 10], "sku-a")], preds=[])
        labels = [e["label"] for e in build_ledger(rec)]
        assert labels == ["missed_truth"]

    def test_ledger_labels_frozen(self):
        assert set(LEDGER_LABELS) >= {
            "correct_accepted", "misclassification", "duplicate_box",
            "background_fp", "missed_truth", "abstain", "unknown",
            "new_package", "manual_review"}


# ---------------------------------------------------------------- metrics


class TestEvaluateArm:
    ARM = {"id": "C2", "frozen_data_hash": "fd", "registry_hash": "rg",
           "region_matching": {"method": "one_to_one_iou", "iou_threshold": 0.5}}

    def test_precision_and_coverage_both_reported(self):
        records = [
            _record("p1",
                    truths=[_truth([0, 0, 10, 10], "a"),
                            _truth([20, 20, 30, 30], "b")],
                    preds=[_pred([0, 0, 10, 10], "a"),
                           _pred([20, 20, 30, 30], "b")]),
            _record("p2", truths=[_truth([0, 0, 10, 10], "c")], preds=[]),
        ]
        m = evaluate_arm(self.ARM, records)
        assert "accepted_precision" in m and "coverage" in m
        assert m["accepted_precision"] == pytest.approx(1.0)
        assert m["coverage"] == pytest.approx(2 / 3)
        assert m["evaluable"] is True

    def test_latency_p95_and_cost_aggregated(self):
        preds = [_pred([i * 20, 0, i * 20 + 10, 10], "a",
                       latency_ms=float(i + 1), cost=0.02)
                 for i in range(20)]
        rec = _record(truths=[_truth(p["box"], "a") for p in preds], preds=preds)
        m = evaluate_arm(self.ARM, [rec])
        assert m["total_cost"] == pytest.approx(20 * 0.02)
        # p95 必须接近最大值（≥19ms），而非均值
        assert m["p95_latency_ms"] >= 19.0

    def test_human_rate_counts_routed_photos(self):
        records = [
            _record("p1", preds=[_pred([0, 0, 10, 10], None,
                                       status="manual_review")]),
            _record("p2"), _record("p3", human_routed=True),
            _record("p4"),
        ]
        m = evaluate_arm(self.ARM, records)
        assert m["human_rate"] == pytest.approx(2 / 4)

    def test_label_counts_cover_all_instances(self):
        rec = _record(
            truths=[_truth([0, 0, 10, 10], "a"), _truth([50, 50, 60, 60], "b")],
            preds=[_pred([0, 0, 10, 10], "a"),
                   _pred([100, 100, 110, 110], "z")])
        m = evaluate_arm(self.ARM, [rec])
        counts = m["label_counts"]
        assert counts["correct_accepted"] == 1
        assert counts["background_fp"] == 1
        assert counts["missed_truth"] == 1


# ---------------------------------------------------------------- arms


class TestArms:
    def test_four_arms_share_frozen_config(self):
        arms = define_arms(frozen_data_hash="fd-1", registry_hash="rg-1")
        assert tuple(sorted(arms)) == tuple(sorted(ARM_IDS))
        ref = arms["E0"]
        for aid in ARM_IDS:
            arm = arms[aid]
            assert arm["frozen_data_hash"] == ref["frozen_data_hash"]
            assert arm["registry_hash"] == ref["registry_hash"]
            assert arm["region_matching"] == ref["region_matching"]

    def test_c2_is_qwen_arm_and_e1_not_publishable(self):
        arms = define_arms(frozen_data_hash="fd", registry_hash="rg")
        assert arms["C2"]["uses_qwen"] is True
        assert arms["C2"]["qwen_model"] == "qwen3-vl:4b"
        assert arms["C1"]["uses_qwen"] is False
        assert arms["E1"]["publishable_baseline"] is False

    def test_validate_arms_rejects_mismatch(self):
        arms = define_arms(frozen_data_hash="fd", registry_hash="rg")
        validate_arms(arms)  # 一致时不抛
        arms["C2"] = dict(arms["C2"], frozen_data_hash="other")
        with pytest.raises(ValueError):
            validate_arms(arms)


# ---------------------------------------------------------------- gate


class TestPromotionGate:
    def _good_metrics(self, **over):
        m = {"arm_id": "C2", "photos": 100, "evaluable_truths": 120,
             "evaluable": True, "accepted": 110,
             "accepted_precision": 0.97, "coverage": 0.95,
             "fp_per_photo": 0.02, "p95_latency_ms": 900.0,
             "total_cost": 3.5, "human_rate": 0.05,
             "unknown_or_new_rate": 0.03,
             "label_counts": {}}
        m.update(over)
        return m

    def test_pass_when_all_constraints_met(self):
        verdict = promotion_gate(self._good_metrics())
        assert verdict["status"] == "pass"

    def test_fail_when_coverage_low_even_if_precision_high(self):
        verdict = promotion_gate(self._good_metrics(coverage=0.50))
        assert verdict["status"] == "fail"
        assert any("coverage" in r for r in verdict["reasons"])

    def test_fail_when_precision_below_line(self):
        verdict = promotion_gate(self._good_metrics(accepted_precision=0.94))
        assert verdict["status"] == "fail"

    def test_fail_when_precision_missing(self):
        # accepted=0：precision 无法报告 → 不得晋级
        verdict = promotion_gate(self._good_metrics(
            accepted=0, accepted_precision=None))
        assert verdict["status"] != "pass"

    def test_not_evaluable_without_human_truths(self):
        verdict = promotion_gate(self._good_metrics(
            evaluable=False, evaluable_truths=0, coverage=None))
        assert verdict["status"] == "not_evaluable"
        assert verdict["status"] != "pass"

    def test_not_evaluable_when_truths_below_minimum(self):
        verdict = promotion_gate(self._good_metrics(evaluable_truths=3),
                                 min_evaluable_truths=20)
        assert verdict["status"] == "not_evaluable"


# ---------------------------------------------------------------- execution gate


class TestShadowExecutionGate:
    def test_blocked_by_active_training(self):
        gate = shadow_execution_gate(
            processes=["python3 -m src.training.train_v1 --epochs 120"],
            active_training_leases=0)
        assert gate["ok"] is False
        assert "BLOCKED_BY_ACTIVE_TRAINING" in gate["blockers"]

    def test_blocked_by_training_lease(self):
        gate = shadow_execution_gate(processes=[], active_training_leases=1)
        assert gate["ok"] is False
        assert "BLOCKED_BY_ACTIVE_TRAINING" in gate["blockers"]

    def test_ok_without_training(self):
        gate = shadow_execution_gate(processes=["vim README.md"],
                                     active_training_leases=0)
        assert gate["ok"] is True
        assert gate["blockers"] == []


# ---------------------------------------------------------------- script CLI


class TestScriptCli:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "scripts.run_cascade_shadow_eval", *args],
            capture_output=True, text=True, timeout=60)

    def test_evaluate_mode_writes_report(self, tmp_path):
        ledger = {
            "arms": define_arms(frozen_data_hash="fd", registry_hash="rg"),
            "runs": {"C2": [_record(
                truths=[_truth([0, 0, 10, 10], "a")],
                preds=[_pred([0, 0, 10, 10], "a")])]},
        }
        inp = tmp_path / "ledger.json"
        out = tmp_path / "report.json"
        inp.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
        res = self._run("--mode", "evaluate", "--input", str(inp),
                        "--output", str(out))
        assert res.returncode == 0, res.stderr
        report = json.loads(out.read_text(encoding="utf-8"))
        m = report["metrics"]["C2"]
        assert "accepted_precision" in m and "coverage" in m
        assert report["gate"]["C2"]["status"] in ("pass", "fail", "not_evaluable")

    def test_run_mode_blocked_by_active_training(self):
        res = self._run("--mode", "run", "--simulate-processes",
                        "python3 -m src.training.train_v1")
        assert res.returncode != 0
        assert "BLOCKED_BY_ACTIVE_TRAINING" in res.stdout + res.stderr

    def test_run_mode_never_runs_without_authorization(self):
        # 即使无训练进程，真实 shadow 也需要明确授权（默认拒绝）
        res = self._run("--mode", "run", "--simulate-processes", "")
        assert res.returncode != 0
