"""拒识门禁与 unknown 契约回归测试（RA-004 / unknown 契约）。

任何 `sku_id=__unknown__` 且 `status=accepted` 的组合都必须失败。"""
import pytest

from src.cascade.cascade_inference import (
    UNKNOWN_CLASS, gate_decision, _match_one_to_one,
)


def test_unknown_never_accepted_high_conf():
    """高置信 __unknown__ 也不得 accepted（未来 209 类模型的核心防线）。"""
    for conf in (0.6, 0.9, 0.99, 1.0):
        status, source = gate_decision(UNKNOWN_CLASS, conf, 0.5)
        assert status == "needs_review", f"conf={conf} 时 unknown 被 accepted"
        assert source == "unknown_class"


def test_unknown_never_accepted_at_thresholds():
    status, _ = gate_decision(UNKNOWN_CLASS, 0.6, 0.05)
    assert status == "needs_review"


def test_known_accepted_when_gate_passes():
    status, source = gate_decision("SKU0001", 0.9, 0.2)
    assert (status, source) == ("accepted", "classifier")


def test_known_low_conf_rejected():
    status, source = gate_decision("SKU0001", 0.59, 0.2)
    assert status == "needs_review" and source == "needs_review_lowconf"


def test_known_low_margin_rejected():
    status, source = gate_decision("SKU0001", 0.9, 0.04)
    assert status == "needs_review" and source == "needs_review_lowmargin"


def test_custom_thresholds_respected():
    status, _ = gate_decision("SKU0001", 0.5, 0.1, conf_thr=0.4, margin_thr=0.05)
    assert status == "accepted"
    status, _ = gate_decision(UNKNOWN_CLASS, 0.5, 0.1, conf_thr=0.4, margin_thr=0.05)
    assert status == "needs_review"


def test_one_to_one_matching_consumes_gt_once():
    """RA-005：每个 GT 只被一个预测消费，多余预测计 FP。"""
    gts = [(100, 100), (300, 300)]
    preds = [
        {"box": [80, 80, 120, 120], "classifier_conf": 0.9},
        {"box": [90, 90, 130, 130], "classifier_conf": 0.5},  # 同一 GT，低置信
    ]
    r = _match_one_to_one(preds, gts)
    assert len(r["matches"]) == 1 and r["matches"][0][0] == 0  # 高置信先匹配
    assert r["fp"] == [1]
    assert len(r["fn"]) == 1  # 第二个 GT 未覆盖
