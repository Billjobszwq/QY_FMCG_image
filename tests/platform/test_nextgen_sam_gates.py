"""N2 Task 6：点提示 SAM 几何门契约（02 设计 §4.2 fail-closed）。"""
from __future__ import annotations

import numpy as np
import pytest

from src.modules.nextgen_data.sam_gates import (
    GateRejection,
    score_multimask,
    validate_mask,
)


def _mask(rects, h=200, w=200):
    m = np.zeros((h, w), dtype=bool)
    for (x1, y1, x2, y2) in rects:
        m[y1:y2, x1:x2] = True
    return m


class TestGeometricGates:
    def test_mask_must_contain_positive_point(self):
        m = _mask([(10, 10, 50, 60)])
        with pytest.raises(GateRejection, match="positive"):
            validate_mask(m, positive=(120, 120),
                          other_positives=[], width=200, height=200)

    def test_mask_must_not_swallow_other_positive(self):
        m = _mask([(10, 10, 150, 150)])  # 吞并相邻商品
        with pytest.raises(GateRejection, match="other_positive"):
            validate_mask(m, positive=(20, 20),
                          other_positives=[(100, 100)],
                          width=200, height=200)

    def test_multiple_components_rejected(self):
        m = _mask([(10, 10, 40, 40), (120, 120, 160, 160)])
        with pytest.raises(GateRejection, match="components"):
            validate_mask(m, positive=(20, 20),
                          other_positives=[], width=200, height=200)

    def test_too_small_rejected(self):
        m = _mask([(10, 10, 14, 14)])  # 16 px
        with pytest.raises(GateRejection, match="small"):
            validate_mask(m, positive=(11, 11), other_positives=[],
                          width=200, height=200, min_area_px=50)

    def test_extreme_aspect_ratio_rejected(self):
        m = _mask([(10, 10, 190, 14)])  # 180x4 极端条状
        with pytest.raises(GateRejection, match="aspect"):
            validate_mask(m, positive=(100, 11), other_positives=[],
                          width=200, height=200)

    def test_valid_mask_returns_tight_box(self):
        m = _mask([(40, 50, 90, 150)])
        out = validate_mask(m, positive=(60, 100), other_positives=[],
                            width=200, height=200)
        assert out["tight_box"] == [40, 50, 90, 150]
        assert out["area_px"] == 50 * 100

    def test_overlap_with_neighbor_rejected(self):
        m = _mask([(10, 10, 100, 100)])
        neighbor = _mask([(60, 60, 150, 150)])
        with pytest.raises(GateRejection, match="overlap"):
            validate_mask(m, positive=(20, 20), other_positives=[],
                          width=200, height=200,
                          neighbor_masks=[neighbor], max_overlap=0.2)


class TestCandidateSelection:
    def test_score_selection_without_sku_leakage(self):
        # 三个候选：中间得分最高；选择只依据几何/稳定性分数
        m_ok = _mask([(40, 50, 90, 150)])
        m_bad = _mask([(0, 0, 200, 200)])     # 全图
        m_small = _mask([(40, 50, 44, 54)])   # 过小
        cands = [(m_bad, 0.99), (m_ok, 0.9), (m_small, 0.8)]
        pick, why = score_multimask(cands, positive=(60, 100),
                                    other_positives=[],
                                    width=200, height=200)
        assert pick is not None
        assert why["selected_reason"] != "raw_score_only"

    def test_all_candidates_rejected_returns_none(self):
        m_bad = _mask([(0, 0, 200, 200)])
        pick, why = score_multimask([(m_bad, 0.99)], positive=(60, 100),
                                    other_positives=[],
                                    width=200, height=200)
        assert pick is None and why["rejections"]
