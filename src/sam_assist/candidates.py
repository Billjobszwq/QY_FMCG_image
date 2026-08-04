"""SAM multimask 候选硬约束筛选（手册§六.5-9）。

规则：
- mask 必须包含 positive point，不得包含其他实例点；
- 面积与长宽比必须在校准的物理范围内；
- 多连通域、触碰 ROI 边界、与已选实例大面积重叠 → 降级人工；
- 无合格候选 → MANUAL_REQUIRED，绝不回退固定比例框。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import cv2
import numpy as np

from .contracts import SamCandidate

OVERLAP_WITH_SELECTED_IOU = 0.5  # 与已选实例重叠超过该比例即降级


class CandidateDecision(Enum):
    ACCEPTED = "accepted"
    MANUAL_REQUIRED = "manual_required"


@dataclass(frozen=True)
class PhysicalLimits:
    """经校准的物理范围（面积/长宽比），阈值版本随证据保存。"""
    min_area_px: float
    max_area_px: float
    min_aspect: float   # bbox_h / bbox_w 下限
    max_aspect: float


@dataclass
class FilterResult:
    decision: CandidateDecision
    candidates: list          # 全部候选（含拒绝原因）
    best: Optional[SamCandidate]
    fallback_box: Optional[tuple] = None  # 恒为 None（禁止比例框回退）


def _contains(mask: np.ndarray, pt: tuple) -> bool:
    x, y = int(round(pt[0])), int(round(pt[1]))
    if not (0 <= y < mask.shape[0] and 0 <= x < mask.shape[1]):
        return False
    return bool(mask[y, x] > 0)


def _mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = int(np.count_nonzero(a.astype(bool) & b.astype(bool)))
    if inter == 0:
        return 0.0
    union = int(np.count_nonzero(a.astype(bool) | b.astype(bool)))
    return inter / union if union else 0.0


def _touches_roi_boundary(mask: np.ndarray, roi: tuple) -> bool:
    x1, y1, x2, y2 = (int(v) for v in roi)
    x2 = min(x2, mask.shape[1])
    y2 = min(y2, mask.shape[0])
    x1, y1 = max(0, x1), max(0, y1)
    if x2 <= x1 or y2 <= y1:
        return False
    return bool(
        np.any(mask[y1, x1:x2]) or np.any(mask[y2 - 1, x1:x2])
        or np.any(mask[y1:y2, x1]) or np.any(mask[y1:y2, x2 - 1])
    )


def filter_candidates(candidates: list,
                      positive: tuple,
                      other_points: list,
                      roi: tuple,
                      limits: PhysicalLimits,
                      selected_masks: list) -> FilterResult:
    annotated = []
    for c in candidates:
        mask = c.mask
        ys, xs = np.nonzero(mask)
        area = float(len(xs))
        reasons = []
        if area > 0:
            bx1, bx2 = float(xs.min()), float(xs.max() + 1)
            by1, by2 = float(ys.min()), float(ys.max() + 1)
            c.bbox = (bx1, by1, bx2, by2)
            c.centroid = (float(xs.mean()), float(ys.mean()))
            c.area_px = area
            bw, bh = bx2 - bx1, by2 - by1
            aspect = bh / bw if bw > 0 else float("inf")
            if not (limits.min_area_px <= area <= limits.max_area_px):
                reasons.append("area_out_of_range")
            if not (limits.min_aspect <= aspect <= limits.max_aspect):
                reasons.append("aspect_out_of_range")
        else:
            reasons.append("empty_mask")

        if not _contains(mask, positive):
            reasons.append("missing_positive")
        if any(_contains(mask, p) for p in other_points):
            reasons.append("contains_other_instance")
        n_comp, _ = cv2.connectedComponents(mask.astype(np.uint8))
        if n_comp - 1 > 1:
            reasons.append("multi_component")
        if _touches_roi_boundary(mask, roi):
            reasons.append("touches_roi_boundary")
        if any(_mask_iou(mask, s) > OVERLAP_WITH_SELECTED_IOU for s in selected_masks):
            reasons.append("overlap_selected")

        c.reject_reasons = reasons
        c.downgraded = bool(reasons)
        annotated.append(c)

    valid = [c for c in annotated if not c.reject_reasons]
    if valid:
        best = max(valid, key=lambda c: (c.iou_score, c.stability_score, c.area_px))
        return FilterResult(CandidateDecision.ACCEPTED, annotated, best, None)
    # 手册§六.9：无合格候选 → manual_required，禁止回退固定比例框
    return FilterResult(CandidateDecision.MANUAL_REQUIRED, annotated, None, None)


def mask_to_boxes(mask: np.ndarray, context_pad: float = 0.15) -> dict:
    """mask → visible_tight_box（真实可见框）与 context_box（classifier 派生框）。

    手册§六.8：两框分开保存，context_box 只是派生框，不得覆盖真实框。"""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise ValueError("空 mask 无法导出框")
    x1, x2 = float(xs.min()), float(xs.max() + 1)
    y1, y2 = float(ys.min()), float(ys.max() + 1)
    tight = (x1, y1, x2, y2)
    bw, bh = x2 - x1, y2 - y1
    cx = (max(0.0, x1 - context_pad * bw), max(0.0, y1 - context_pad * bh),
          min(float(mask.shape[1]), x2 + context_pad * bw),
          min(float(mask.shape[0]), y2 + context_pad * bh))
    return {"visible_tight_box": tight, "context_box": cx,
            "context_is_derived": True}
