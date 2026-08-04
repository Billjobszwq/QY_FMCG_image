"""UMT-001 红测试：recall@FP 必须是全数据集统一置信度阈值扫描。

手册 §3.1 UMT-001 验收口径：
- 不得逐图取 top-K proposal（当前 recall_at_fp 的缺陷行为）；
- 扫描全数据集统一置信度阈值，逐阈值按 conf 降序 one-to-one 配对；
- FP 预算 = 全数据集 total FP（重复框 + 定位错误 + 背景误检等）；
- 对抗用例：「2 TP 后才出现第 1 个 FP」时 FP1 必须允许 2 TP，
  不得只取 1 个 proposal。

本文件在当前逐图 TopK 实现下必须失败（RED），修复后全绿。
独立参考实现内嵌于测试，与主实现互验。
"""
from __future__ import annotations

import pytest

from src.eval.truebox_eval import _iou, match_one_to_one


# ---------- 独立参考实现（测试内建，用于互验） ----------

def reference_recall_at_fp(images: list, fp_budgets=(1, 3, 5),
                           iou_thresh: float = 0.5) -> dict:
    """参考实现：全数据集统一置信度阈值扫描。

    对每个 FP 预算 b：扫描全部唯一 conf 阈值 t（降序），在
    preds(conf >= t) 上做逐图 one-to-one 配对；total FP = 未配对
    且非重复的 proposal 总数；取满足 FP <= b * n_images 的最大
    TP，recall = TP / n_gt。
    """
    all_preds = sorted(
        ((float(p["conf"]), img_i, pi)
         for img_i, img in enumerate(images)
         for pi, p in enumerate(img["preds"])),
        key=lambda t: (-t[0], t[1], t[2]),
    )
    n_images = len(images)
    n_gt = sum(len(img["gt"]) for img in images)
    thresholds = sorted({c for c, _, _ in all_preds}, reverse=True)
    out = {}
    for b in fp_budgets:
        budget = b * n_images
        best_tp = 0
        for t in thresholds:
            tp = 0
            fp = 0
            for img in images:
                kept = [p for p in img["preds"] if float(p["conf"]) >= t]
                pairs = match_one_to_one(img["gt"], kept, iou_thresh)
                tp += len(pairs)
                matched_p = {pi for _, pi, _ in pairs}
                order = sorted(range(len(kept)),
                               key=lambda i: (-float(kept[i]["conf"]), i))
                for k, pi in enumerate(order):
                    if pi in matched_p:
                        continue
                    dup = any(_iou(kept[pi]["box"], kept[pj]["box"]) >= 0.5
                              for pj in order[:k])
                    if not dup:
                        fp += 1
            if fp <= budget:
                best_tp = max(best_tp, tp)
        out[b] = (best_tp / n_gt) if n_gt else 0.0
    return out


def _box(x1, y1, x2, y2):
    return {"box": [x1, y1, x2, y2]}


def _adversarial_images():
    """手册对抗用例：2 TP 后才出现第 1 个 FP（单图）。"""
    gts = [_box(0, 0, 10, 10), _box(30, 0, 40, 10)]
    preds = [
        {"box": [0, 0, 10, 10], "conf": 0.90},        # TP1
        {"box": [30, 0, 40, 10], "conf": 0.80},       # TP2
        {"box": [200, 200, 210, 210], "conf": 0.50},  # 第 1 个 FP
    ]
    return [{"gt": gts, "preds": preds}]


class TestTrueFpSemantics:
    def test_fp1_allows_two_tp_before_first_fp(self):
        """FP1 应允许 2 TP：阈值切在第一个 FP 之前，两个 TP 都在列。"""
        from src.eval.truebox_eval import recall_at_fp
        r = recall_at_fp(_adversarial_images(), fp_budgets=(1,),
                         iou_thresh=0.5)
        assert r[1] == pytest.approx(1.0), (
            "FP1 只计 1 个 proposal（逐图 TopK 缺陷）；"
            "统一阈值扫描下 2 TP 均应先于第 1 个 FP 被接受")

    def test_cross_image_unified_threshold(self):
        """统一阈值：低置信 TP 图不得因其它图的高置信 FP 被挤掉。"""
        from src.eval.truebox_eval import recall_at_fp
        img_a = {"gt": [_box(0, 0, 10, 10)],
                 "preds": [{"box": [200, 200, 210, 210], "conf": 0.99},
                           {"box": [0, 0, 10, 10], "conf": 0.40}]}
        img_b = {"gt": [_box(0, 0, 10, 10)],
                 "preds": [{"box": [0, 0, 10, 10], "conf": 0.30}]}
        # FP 预算 1/photo：阈值 0.40 时 TP=1 FP=1；0.30 时 TP=2 FP=1 → 全接受
        r = recall_at_fp([img_a, img_b], fp_budgets=(1,), iou_thresh=0.5)
        assert r[1] == pytest.approx(1.0), (
            "逐图 TopK 下 img_b 的 TP 与 img_a 的低置信 TP 被错误丢弃")

    def test_total_fp_counts_duplicates_and_localization(self):
        """total FP 必须含重复框与定位错误，不只是背景误检。"""
        from src.eval.truebox_eval import evaluate_truebox
        gts = [_box(0, 0, 10, 10)]
        preds = [
            {"box": [0, 0, 10, 10], "conf": 0.9},
            {"box": [0.5, 0.5, 10.5, 10.5], "conf": 0.8},  # 重复框
            {"box": [0, 4, 10, 14], "conf": 0.7},           # IoU 0.375 定位差
            {"box": [200, 200, 215, 215], "conf": 0.6},     # 背景
        ]
        rep = evaluate_truebox([{"gt": gts, "preds": preds}])
        total = rep["total_fp"]
        assert total == 3, "FP_total = duplicate + localization + background"
        assert (rep["n_duplicates"] + rep["n_background_fp"]
                + rep["n_localization_fp"]) == total

    def test_fp_conservation(self):
        """FP 守恒式：n_proposals = TP + FP_total（无重叠无遗漏）。"""
        from src.eval.truebox_eval import evaluate_truebox
        images = _adversarial_images() + [{
            "gt": [_box(0, 0, 10, 10), _box(30, 0, 40, 10)],
            "preds": [{"box": [0, 0, 10, 10], "conf": 0.5},
                      {"box": [30, 0, 40, 10], "conf": 0.4},
                      {"box": [100, 100, 110, 110], "conf": 0.3}],
        }]
        rep = evaluate_truebox(images)
        assert (rep["n_tp_iou0.5"] + rep["total_fp"]
                == rep["n_proposals"]), "FP 守恒式被破坏"


class TestReferenceCrossCheck:
    def test_reference_matches_main_on_random_cases(self):
        """修复后主实现必须与独立参考实现在对抗/随机案例上一致。"""
        import random

        from src.eval.truebox_eval import recall_at_fp
        rng = random.Random(20260805)
        cases = list(_adversarial_images())
        for _ in range(20):
            n_gt = rng.randint(0, 4)
            gts = [_box(rng.randint(0, 300), rng.randint(0, 300),
                        0, 0) for _ in range(n_gt)]
            gts = [{"box": [g["box"][0], g["box"][1],
                            g["box"][0] + 12, g["box"][1] + 12]}
                   for g in gts]
            preds = []
            for g in gts:
                if rng.random() < 0.7:
                    preds.append({"box": list(g["box"]),
                                  "conf": round(rng.random(), 2)})
            for _ in range(rng.randint(0, 3)):
                preds.append({"box": [rng.randint(0, 400),
                                      rng.randint(0, 400),
                                      rng.randint(0, 400) + 10,
                                      rng.randint(0, 400) + 10],
                              "conf": round(rng.random(), 2)})
            cases.append({"gt": gts, "preds": preds})
        got = recall_at_fp(cases, fp_budgets=(1, 3, 5), iou_thresh=0.5)
        ref = reference_recall_at_fp(cases, fp_budgets=(1, 3, 5),
                                     iou_thresh=0.5)
        for b in (1, 3, 5):
            assert got[b] == pytest.approx(ref[b]), (
                f"FP{b}: 主实现 {got[b]} != 独立参考 {ref[b]}")
