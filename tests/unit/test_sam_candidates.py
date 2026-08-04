"""SAM 候选硬约束契约（手册§六.5-9）：multimask 候选筛选、降级与 manual_required，
无合格候选时绝不回退固定比例框。"""
import numpy as np
import pytest

from src.sam_assist.candidates import (
    CandidateDecision,
    PhysicalLimits,
    filter_candidates,
    mask_to_boxes,
)
from src.sam_assist.contracts import SamCandidate


def _rect_mask(h, w, x1, y1, x2, y2):
    m = np.zeros((h, w), dtype=np.uint8)
    m[int(y1):int(y2), int(x1):int(x2)] = 1
    return m


def _cand(mask, score=0.9, iid=None):
    return SamCandidate(candidate_id=iid or "c1", mask=mask, iou_score=score,
                        stability_score=0.9)


LIMITS = PhysicalLimits(min_area_px=200.0, max_area_px=200_000.0,
                        min_aspect=0.15, max_aspect=6.0)
POS = (500.0, 800.0)


def test_valid_candidate_accepted():
    mask = _rect_mask(2000, 1500, 480, 700, 520, 900)  # 含正点 (500,800)
    res = filter_candidates([_cand(mask)], positive=POS, other_points=[],
                            roi=(400, 600, 600, 1000), limits=LIMITS,
                            selected_masks=[])
    assert res.decision == CandidateDecision.ACCEPTED
    assert res.best is not None and res.best.reject_reasons == []


def test_mask_must_contain_positive_point():
    mask = _rect_mask(2000, 1500, 100, 100, 200, 200)  # 不含正点
    res = filter_candidates([_cand(mask)], positive=POS, other_points=[],
                            roi=(0, 0, 1500, 2000), limits=LIMITS,
                            selected_masks=[])
    assert res.decision == CandidateDecision.MANUAL_REQUIRED
    assert any("missing_positive" in c.reject_reasons for c in res.candidates)


def test_mask_must_not_contain_other_instance_point():
    mask = _rect_mask(2000, 1500, 450, 700, 600, 900)  # 含正点也含邻近点 (560,810)
    res = filter_candidates([_cand(mask)], positive=POS,
                            other_points=[(560.0, 810.0)],
                            roi=(0, 0, 1500, 2000), limits=LIMITS,
                            selected_masks=[])
    assert res.decision == CandidateDecision.MANUAL_REQUIRED
    assert any("contains_other_instance" in c.reject_reasons for c in res.candidates)


def test_area_and_aspect_within_calibrated_physical_range():
    tiny = _rect_mask(2000, 1500, 498, 798, 502, 802)  # 16px² < 200
    res = filter_candidates([_cand(tiny)], positive=POS, other_points=[],
                            roi=(0, 0, 1500, 2000), limits=LIMITS,
                            selected_masks=[])
    assert any("area_out_of_range" in c.reject_reasons for c in res.candidates)

    # 极细长 mask：10x600 → aspect=60 > 6
    thin = np.zeros((2000, 1500), dtype=np.uint8)
    thin[500:1100, 495:505] = 1
    res2 = filter_candidates([_cand(thin)], positive=(500.0, 800.0), other_points=[],
                             roi=(0, 0, 1500, 2000), limits=LIMITS,
                             selected_masks=[])
    assert any("aspect_out_of_range" in c.reject_reasons for c in res2.candidates)


def test_multi_component_and_boundary_touch_downgrade_to_manual():
    two = np.zeros((2000, 1500), dtype=np.uint8)
    two[750:850, 480:520] = 1   # 含正点的一块
    two[300:350, 480:520] = 1   # 分离的另一块
    res = filter_candidates([_cand(two)], positive=POS, other_points=[],
                            roi=(0, 0, 1500, 2000), limits=LIMITS,
                            selected_masks=[])
    assert any("multi_component" in c.reject_reasons for c in res.candidates)

    edge = _rect_mask(2000, 1500, 480, 700, 520, 2000)  # 触 ROI 底边
    res2 = filter_candidates([_cand(edge)], positive=POS, other_points=[],
                             roi=(400, 600, 600, 2000), limits=LIMITS,
                             selected_masks=[])
    assert any("touches_roi_boundary" in c.reject_reasons for c in res2.candidates)


def test_large_overlap_with_selected_downgrades():
    sel = _rect_mask(2000, 1500, 480, 700, 520, 900)
    dup = _rect_mask(2000, 1500, 481, 701, 521, 901)  # 与已选几乎重合
    res = filter_candidates([_cand(dup)], positive=POS, other_points=[],
                            roi=(0, 0, 1500, 2000), limits=LIMITS,
                            selected_masks=[sel])
    assert any("overlap_selected" in c.reject_reasons for c in res.candidates)


def test_no_valid_candidate_is_manual_required_never_fallback_ratio_box():
    """手册§六.9：无合格候选 → manual_required，禁止回退固定比例框。"""
    bad = _rect_mask(2000, 1500, 100, 100, 200, 200)
    res = filter_candidates([_cand(bad)], positive=POS, other_points=[],
                            roi=(0, 0, 1500, 2000), limits=LIMITS,
                            selected_masks=[])
    assert res.decision == CandidateDecision.MANUAL_REQUIRED
    assert res.best is None
    assert res.fallback_box is None, "禁止用固定比例框伪装真实框"


def test_empty_candidate_list_manual_required():
    res = filter_candidates([], positive=POS, other_points=[],
                            roi=(0, 0, 1500, 2000), limits=LIMITS,
                            selected_masks=[])
    assert res.decision == CandidateDecision.MANUAL_REQUIRED
    assert res.fallback_box is None


def test_mask_to_boxes_separates_tight_and_context():
    """手册§六.8：visible_tight_box 与 classifier 用 context_box 分开保存，
    context_box 只是派生框。"""
    mask = _rect_mask(2000, 1500, 480, 700, 520, 900)
    boxes = mask_to_boxes(mask, context_pad=0.15)
    assert boxes["visible_tight_box"] == (480.0, 700.0, 520.0, 900.0)
    cx1, cy1, cx2, cy2 = boxes["context_box"]
    assert cx1 < 480 and cy1 < 700 and cx2 > 520 and cy2 > 900
    assert boxes["context_is_derived"] is True
    assert boxes["context_box"] != boxes["visible_tight_box"]


def test_candidate_keeps_scores_and_reject_reason_fields():
    mask = _rect_mask(2000, 1500, 480, 700, 520, 900)
    c = _cand(mask, score=0.77)
    assert c.iou_score == 0.77
    assert hasattr(c, "stability_score")
    res = filter_candidates([c], positive=POS, other_points=[],
                            roi=(0, 0, 1500, 2000), limits=LIMITS,
                            selected_masks=[])
    kept = res.candidates[0]
    assert kept.area_px > 0
    assert kept.centroid is not None
    assert kept.bbox is not None
