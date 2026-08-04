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

EVAL_VERSION = "truebox_eval_v1"


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


def recall_at_fp(images: list, fp_budgets=(1, 3, 5),
                 iou_thresh: float = 0.5) -> dict:
    """recall@FP/image：每图按 conf 降序取前 budget 个 proposal 后配对。"""
    n_gt = sum(len(img["gt"]) for img in images)
    out = {}
    for b in fp_budgets:
        tp = 0
        for img in images:
            top = sorted(img["preds"], key=lambda p: -float(p["conf"]))[:b]
            tp += len(match_one_to_one(img["gt"], top, iou_thresh))
        out[b] = (tp / n_gt) if n_gt else 0.0
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
    n_tp = n_dup = n_bg = 0

    for img in images:
        gt, preds = img["gt"], img["preds"]
        pairs5 = match_one_to_one(gt, preds, 0.5)
        n_tp += len(pairs5)
        matched_p = {pi for _, pi, _ in pairs5}
        matched_g = {gi for gi, _, _ in pairs5}

        # 重复框：低置信度 pred 与任一更高置信度 pred IoU≥0.5
        order = sorted(range(len(preds)),
                       key=lambda i: (-float(preds[i]["conf"]), i))
        dup_flags = {}
        for k, pi in enumerate(order):
            dup_flags[pi] = any(
                _iou(preds[pi]["box"], preds[pj]["box"]) >= 0.5
                for pj in order[:k])
        n_dup += sum(dup_flags.values())
        ledger["duplicate_detection"] += sum(dup_flags.values())

        # 背景误检：未配对且非重复框
        for pi in range(len(preds)):
            if pi in matched_p or dup_flags[pi]:
                continue
            n_bg += 1
            ledger["background_shelf_edge"] += 1

        # 坏定位：IoU∈[0.3,0.5) 的 one-to-one 配对
        for gi, pi, v in match_one_to_one(gt, preds, localization_iou):
            if v < 0.5:
                ledger["bad_localization"] += 1

        ledger["missed_detection"] += len(gt) - len(matched_g)

    if hints:  # 人工/上下文复核结果合并（不可覆盖几何统计外的已有值）
        for k, v in hints.items():
            if k not in ERROR_CATEGORIES:
                raise KeyError(f"未知错误类别: {k}")
            ledger[k] += int(v)

    return {
        "eval_version": EVAL_VERSION,
        "matching": "one_to_one_greedy_iou_desc",
        "n_images": len(images),
        "n_gt": n_gt,
        "n_proposals": n_proposals,
        "n_tp_iou0.5": n_tp,
        "n_duplicates": n_dup,
        "n_background_fp": n_bg,
        "precision": (n_tp / n_proposals) if n_proposals else 0.0,
        "recall_at_fp": recall,
        "error_ledger": ledger,
    }
