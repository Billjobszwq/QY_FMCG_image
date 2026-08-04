"""真实框统一评估器测试（手册§十，2026-08-05 审计纠偏后口径）。

锁定行为：
- one-to-one greedy matching（按 IoU 降序，GT 与 pred 各至多一次配对）；
- recall@FP/image 为全数据集统一置信度阈值扫描（非逐图 TopK）；
- FP 为 total FP：重复框 + 定位错误 + 背景误检；守恒式 TP+FP=proposals；
- 逐实例错误账本覆盖 10 类；同一 evaluator/配置可复现。
"""
from __future__ import annotations

import pytest

from src.eval.truebox_eval import (
    ERROR_CATEGORIES,
    evaluate_truebox,
    match_one_to_one,
    recall_at_fp,
)


def _box(x1, y1, x2, y2):
    return {"box": [x1, y1, x2, y2]}


class TestOneToOneMatching:
    def test_each_gt_matched_at_most_once(self):
        gt = [_box(0, 0, 10, 10), _box(0, 0, 10.5, 10.5)]
        preds = [{"box": [0, 0, 10, 10], "conf": 0.9}]
        pairs = match_one_to_one(gt, preds, iou_thresh=0.5)
        assert len(pairs) == 1  # 同一 pred 不得配两个 GT

    def test_greedy_prefers_best_iou(self):
        gt = [_box(0, 0, 10, 10)]
        preds = [{"box": [0, 0, 10, 10], "conf": 0.2},
                 {"box": [5, 5, 15, 15], "conf": 0.99}]
        pairs = match_one_to_one(gt, preds, iou_thresh=0.2)
        assert pairs[0][0] == 0 and pairs[0][1] == 0  # 完美框优先于高置信度

    def test_iou_threshold_respected(self):
        gt = [_box(0, 0, 10, 10)]
        preds = [{"box": [6, 6, 16, 16], "conf": 0.9}]  # IoU≈0.041
        assert match_one_to_one(gt, preds, iou_thresh=0.5) == []


class TestRecallAtFp:
    def _one_image(self, n_gt=3, n_good=2, n_fp=4):
        gts = [_box(i * 20, 0, i * 20 + 10, 10) for i in range(n_gt)]
        preds = [{"box": list(g["box"]), "conf": 0.9 - i * 0.01}
                 for i, g in enumerate(gts[:n_good])]
        preds += [{"box": [200 + i * 30, 200, 210 + i * 30, 210],
                   "conf": 0.3 - i * 0.01} for i in range(n_fp)]
        return {"gt": gts, "preds": preds}

    def test_recall_at_budgets(self):
        # 统一阈值扫描：预算内阈值切在全部 FP 之前，2 TP 全计入
        img = self._one_image()
        r = recall_at_fp([img], fp_budgets=(1, 3, 5), iou_thresh=0.5)
        assert r[1] == pytest.approx(2 / 3)   # 预算1：FP 均为低置信，不影响 2 TP
        assert r[3] == pytest.approx(2 / 3)
        assert r[5] == pytest.approx(2 / 3)

    def test_high_conf_fp_consumes_budget(self):
        gts = [_box(0, 0, 10, 10), _box(30, 0, 40, 10)]
        preds = [{"box": [200, 200, 210, 210], "conf": 0.99},  # 高置信 FP
                 {"box": [0, 0, 10, 10], "conf": 0.5},
                 {"box": [30, 0, 40, 10], "conf": 0.4}]
        # 预算 0：任何阈值下 FP=1 > 0 → recall 0（验证预算约束真实生效）
        r = recall_at_fp([{"gt": gts, "preds": preds}],
                         fp_budgets=(0, 1), iou_thresh=0.5)
        assert r[0] == 0.0
        assert r[1] == pytest.approx(1.0)  # 预算1：FP 恰好 1，两 TP 全收


class TestEvaluateTruebox:
    def test_report_keys_and_metrics(self):
        gts = [_box(0, 0, 10, 10), _box(30, 0, 40, 10)]
        preds = [{"box": [0, 0, 10, 10], "conf": 0.9},
                 {"box": [0.5, 0.5, 10.5, 10.5], "conf": 0.8},  # 重复框
                 {"box": [200, 200, 215, 215], "conf": 0.7}]     # 背景误检
        rep = evaluate_truebox([{"gt": gts, "preds": preds}])
        for k in ("recall_at_fp", "precision", "n_proposals",
                  "n_duplicates", "n_background_fp", "error_ledger"):
            assert k in rep
        for t in ("iou_0.50", "iou_0.75"):
            assert t in rep["recall_at_fp"]
        assert rep["n_duplicates"] == 1
        assert rep["n_background_fp"] == 1
        assert rep["error_ledger"]["missed_detection"] == 1  # gt[1] 漏检
        assert rep["error_ledger"]["duplicate_detection"] == 1

    def test_error_categories_are_the_ten_from_manual(self):
        assert set(ERROR_CATEGORIES) == {
            "missed_detection", "duplicate_detection", "bad_localization",
            "merged_products", "partial_product", "background_shelf_edge",
            "price_tag_or_poster", "reflection_false_positive",
            "annotation_error", "taxonomy_conflict"}

    def test_bad_localization_bucket(self):
        # IoU 在 [0.3, 0.5)：配对成功记定位差，但不计 IoU0.50 TP
        gts = [_box(0, 0, 10, 10)]
        preds = [{"box": [0, 4, 10, 14], "conf": 0.9}]  # IoU=0.6*... =0.375
        rep = evaluate_truebox([{"gt": gts, "preds": preds}])
        assert rep["error_ledger"]["bad_localization"] == 1
        assert rep["recall_at_fp"]["iou_0.50"][1] == 0.0

    def test_deterministic(self):
        gts = [_box(0, 0, 10, 10)]
        preds = [{"box": [0, 0, 10, 10], "conf": 0.9}]
        a = evaluate_truebox([{"gt": gts, "preds": preds}])
        b = evaluate_truebox([{"gt": gts, "preds": preds}])
        assert a == b
