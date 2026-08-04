"""真实框统一评估器（手册§十 / 用户要求#19/#23）。

对 E0/P0/P1（以及将来任何 detector）在同一人工真实框 GT 上做
one-to-one matching 评估：
- recall@FP/image=1/3/5 与 IoU=0.50/0.75；
- precision、proposal 数、重复框、背景误检；
- 逐实例错误账本 10 类（几何可推断部分自动分类，上下文类由人工
  复核后以 hints 合并）。

禁止把 confidence-greedy matching 与 IoU-pair matching 混用：
本模块只用 one-to-one greedy（IoU 降序）。
"""
from __future__ import annotations

ERROR_CATEGORIES = (
    "missed_detection", "duplicate_detection", "bad_localization",
    "merged_products", "partial_product", "background_shelf_edge",
    "price_tag_or_poster", "reflection_false_positive",
    "annotation_error", "taxonomy_conflict",
)

EVAL_VERSION = "truebox_eval_v2"


def _iou(a: list, b: list) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def match_one_to_one(gt: list, preds: list, iou_thresh: float) -> list:
    """one-to-one greedy：按 IoU 降序配对，GT/pred 各至多一次。

    返回 [(gt_idx, pred_idx, iou)]，确定性 tie-break (gt_idx, pred_idx)。"""
    pairs = []
    for gi, g in enumerate(gt):
        for pi, p in enumerate(preds):
            v = _iou(g["box"], p["box"])
            if v >= iou_thresh:
                pairs.append((v, gi, pi))
    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))
    used_g, used_p, out = set(), set(), []
    for v, gi, pi in pairs:
        if gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        out.append((gi, pi, v))
    return out


def _classify_unmatched(preds: list, matched_p: set,
                        gt: list, localization_iou: float = 0.3) -> dict:
    """未配对 pred 的互斥分类：duplicate / localization / background。

    每个 pred 恰属一类（TP 不在此处）；重复框判定：与任一更高
    置信度 pred（含已配对）IoU≥0.5。"""
    order = sorted(range(len(preds)),
                   key=lambda i: (-float(preds[i]["conf"]), i))
    pos = {pi: k for k, pi in enumerate(order)}
    n_dup = n_loc = n_bg = 0
    for pi in range(len(preds)):
        if pi in matched_p:
            continue
        dup = any(
            pos[pj] < pos[pi]
            and _iou(preds[pi]["box"], preds[pj]["box"]) >= 0.5
            for pj in range(len(preds)) if pj != pi)
        if dup:
            n_dup += 1
            continue
        if any(localization_iou <= _iou(preds[pi]["box"], g["box"]) < 0.5
               for g in gt):
            n_loc += 1
        else:
            n_bg += 1
    return {"duplicate": n_dup, "localization": n_loc, "background": n_bg}


def _tp_fp_at_threshold(images: list, t: float, iou_thresh: float) -> tuple:
    """全数据集在统一阈值 t（conf≥t）下的 (tp, total_fp)。"""
    tp = fp = 0
    for img in images:
        kept = [p for p in img["preds"] if float(p["conf"]) >= t]
        pairs = match_one_to_one(img["gt"], kept, iou_thresh)
        tp += len(pairs)
        c = _classify_unmatched(kept, {pi for _, pi, _ in pairs}, img["gt"])
        fp += c["duplicate"] + c["localization"] + c["background"]
    return tp, fp


def recall_at_fp(images: list, fp_budgets=(1, 3, 5),
                 iou_thresh: float = 0.5) -> dict:
    """recall@FP/image：全数据集统一置信度阈值扫描（非逐图 TopK）。

    对每个 FP 预算 b（每图）：扫描全部唯一 conf 阈值（降序），
    total FP（重复+定位+背景）≤ b×n_images 时取最大 TP。
    """
    n_gt = sum(len(img["gt"]) for img in images)
    n_images = len(images)
    thresholds = sorted({float(p["conf"]) for img in images
                         for p in img["preds"]}, reverse=True)
    out = {}
    for b in fp_budgets:
        budget = b * n_images
        best_tp = 0
        for t in thresholds:
            tp, fp = _tp_fp_at_threshold(images, t, iou_thresh)
            if fp <= budget:
                best_tp = max(best_tp, tp)
        out[b] = (best_tp / n_gt) if n_gt else 0.0
    return out


def evaluate_truebox(images: list, iou_thresholds=(0.5, 0.75),
                     fp_budgets=(1, 3, 5), localization_iou: float = 0.3,
                     hints: dict | None = None) -> dict:
    """统一评估入口。images: [{"gt": [...], "preds": [{"box","conf"}...]}]"""
    recall = {f"iou_{t:.2f}": recall_at_fp(images, fp_budgets, t)
              for t in iou_thresholds}

    n_proposals = sum(len(img["preds"]) for img in images)
    n_gt = sum(len(img["gt"]) for img in images)
    ledger = {c: 0 for c in ERROR_CATEGORIES}
    n_tp = n_dup = n_loc = n_bg = 0

    for img in images:
        gt, preds = img["gt"], img["preds"]
        pairs5 = match_one_to_one(gt, preds, 0.5)
        n_tp += len(pairs5)
        matched_p = {pi for _, pi, _ in pairs5}
        matched_g = {gi for gi, _, _ in pairs5}

        # 未配对 pred 互斥分类：重复框 / 定位差 / 背景误检
        c = _classify_unmatched(preds, matched_p, gt, localization_iou)
        n_dup += c["duplicate"]
        n_loc += c["localization"]
        n_bg += c["background"]
        ledger["duplicate_detection"] += c["duplicate"]
        ledger["bad_localization"] += c["localization"]
        ledger["background_shelf_edge"] += c["background"]

        ledger["missed_detection"] += len(gt) - len(matched_g)

    if hints:  # 人工/上下文复核结果合并（不可覆盖几何统计外的已有值）
        for k, v in hints.items():
            if k not in ERROR_CATEGORIES:
                raise KeyError(f"未知错误类别: {k}")
            ledger[k] += int(v)

    total_fp = n_dup + n_loc + n_bg
    assert n_tp + total_fp == n_proposals, "FP 守恒式被破坏（分类重叠或遗漏）"
    return {
        "eval_version": EVAL_VERSION,
        "matching": "one_to_one_greedy_iou_desc",
        "recall_definition": "global_confidence_threshold_sweep",
        "n_images": len(images),
        "n_gt": n_gt,
        "n_proposals": n_proposals,
        "n_tp_iou0.5": n_tp,
        "n_duplicates": n_dup,
        "n_localization_fp": n_loc,
        "n_background_fp": n_bg,
        "total_fp": total_fp,
        "fp_per_photo": (total_fp / len(images)) if images else 0.0,
        "precision": (n_tp / n_proposals) if n_proposals else 0.0,
        "recall_at_fp": recall,
        "error_ledger": ledger,
    }
