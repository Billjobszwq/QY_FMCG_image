"""N2 Task 6：点提示 SAM 几何门（02 设计 §4.2，fail-closed）。

拒绝条件：不含正点、吞并其他正点、多主要连通域、过小、极端长宽比、
相对图像过大、与邻接 mask 大面积重叠。候选选择只依据几何/稳定性
与 SAM 原始分，绝不使用目标 SKU 名称（防泄漏选择）。
"""
from __future__ import annotations

from typing import Any

import numpy as np


class GateRejection(RuntimeError):
    """几何门拒绝（reason 作为消息前缀）。"""


def _components(mask: np.ndarray) -> int:
    import cv2
    n, _ = cv2.connectedComponents(mask.astype(np.uint8))
    return max(n - 1, 0)


def validate_mask(mask: np.ndarray, *, positive: tuple[float, float],
                  other_positives: list[tuple[float, float]],
                  width: int, height: int,
                  min_area_px: int = 120,
                  max_rel_area: float = 0.9,
                  max_aspect: float = 4.0,
                  neighbor_masks: list[np.ndarray] | None = None,
                  max_overlap: float = 0.3) -> dict[str, Any]:
    px, py = int(positive[0]), int(positive[1])
    if not (0 <= px < mask.shape[1] and 0 <= py < mask.shape[0]) \
            or not mask[py, px]:
        raise GateRejection("positive_point_not_in_mask")
    for (ox, oy) in other_positives:
        oxi, oyi = int(ox), int(oy)
        if 0 <= oxi < mask.shape[1] and 0 <= oyi < mask.shape[0] \
                and mask[oyi, oxi]:
            raise GateRejection("swallows_other_positive_point")
    if _components(mask) > 1:
        raise GateRejection("multiple_components")
    ys, xs = np.nonzero(mask)
    area = int(len(xs))
    if area < min_area_px:
        raise GateRejection("too_small")
    if area > max_rel_area * width * height:
        raise GateRejection("too_large_relative_to_image")
    x1, y1 = int(xs.min()), int(ys.min())
    x2, y2 = int(xs.max()) + 1, int(ys.max()) + 1
    bw, bh = max(x2 - x1, 1), max(y2 - y1, 1)
    aspect = max(bw / bh, bh / bw)
    if aspect > max_aspect:
        raise GateRejection("extreme_aspect_ratio")
    for nb in neighbor_masks or []:
        inter = int(np.logical_and(mask, nb).sum())
        if inter > max_overlap * area:
            raise GateRejection("overlap_with_neighbor_mask")
    return {"tight_box": [x1, y1, x2, y2], "area_px": area,
            "aspect": round(aspect, 3),
            "fill_ratio": round(area / (bw * bh), 4)}


def score_multimask(candidates: list[tuple[np.ndarray, float]], *,
                    positive: tuple[float, float],
                    other_positives: list[tuple[float, float]],
                    width: int, height: int,
                    **gate_kw) -> tuple[dict | None, dict]:
    """multimask 候选打分选择（禁 SKU 名称参与）。

    返回 (chosen, why)；全部被拒 → (None, {"rejections": [...]})。
    """
    scored: list[tuple[float, dict]] = []
    rejections: list[str] = []
    for i, (m, raw) in enumerate(candidates):
        try:
            out = validate_mask(m, positive=positive,
                                other_positives=other_positives,
                                width=width, height=height, **gate_kw)
        except GateRejection as e:
            rejections.append(f"cand{i}:{e}")
            continue
        # 综合分：SAM 原始分 × 填充率（几何稳定性），不用 SKU 语义
        score = float(raw) * out["fill_ratio"]
        scored.append((score, {"index": i, "raw_score": float(raw),
                               **out}))
    if not scored:
        return None, {"rejections": rejections,
                      "selected_reason": "all_rejected"}
    scored.sort(key=lambda t: t[0], reverse=True)
    best_score, best = scored[0]
    return best, {"selected_reason": "gated_geometric_plus_raw_score",
                  "score": best_score, "rejections": rejections}
