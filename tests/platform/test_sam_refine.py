"""SAM 精修标注纯函数测试（TDD 红测试先行）。

口径：数据集现有 YOLO 粗框作为 SAM box prompt，SAM 输出 mask 的紧框
（tight box）替换原框几何，SKU 类别沿用原框；SAM 框不合法时回退原框。"""
from __future__ import annotations

import math

import pytest

from src.training.sam_refine import (
    clamp_bbox,
    is_valid_bbox,
    parse_yolo_label,
    refine_one,
    to_yolo_line,
    write_yolo_label,
)


class TestParseYoloLabel:
    def test_normal_lines(self):
        text = "106 0.068 0.337 0.07 0.18\n37 0.61 0.4965 0.07 0.18\n"
        rows = parse_yolo_label(text, width=1000, height=2000)
        assert len(rows) == 2
        assert rows[0]["class_id"] == 106
        assert rows[0]["box_px"] == (68.0 - 35.0, 674.0 - 180.0, 68.0 + 35.0, 674.0 + 180.0)

    def test_empty_and_blank(self):
        assert parse_yolo_label("", width=100, height=100) == []
        assert parse_yolo_label("  \n", width=100, height=100) == []

    def test_bad_line_raises(self):
        with pytest.raises(ValueError):
            parse_yolo_label("abc 0.5 0.5 0.1 0.1", width=100, height=100)
        with pytest.raises(ValueError):
            parse_yolo_label("3 0.5 0.5 0.1", width=100, height=100)

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError):
            parse_yolo_label("3 1.2 0.5 0.1 0.1", width=100, height=100)


class TestIsValidBbox:
    def test_normal(self):
        assert is_valid_bbox((10, 10, 50, 80), width=1000, height=1000)

    def test_degenerate(self):
        assert not is_valid_bbox((10, 10, 10, 80), width=1000, height=1000)
        assert not is_valid_bbox((50, 80, 10, 10), width=1000, height=1000)

    def test_area_too_small(self):
        # 40*1=40 < 64
        assert not is_valid_bbox((0, 0, 40, 1), width=1000, height=1000,
                                 min_area_px=64)

    def test_too_large_share(self):
        # 90% 面积视为背景误分割
        assert not is_valid_bbox((0, 0, 900, 1000), width=1000, height=1000,
                                 max_area_share=0.5)

    def test_extreme_aspect_ratio(self):
        # 1000x10 → ratio 100 超 max_ratio 30
        assert not is_valid_bbox((0, 0, 1000, 10), width=1000, height=1000,
                                 max_area_share=1.0)


class TestClampBbox:
    def test_clamp_to_image(self):
        assert clamp_bbox((-5, -3, 1200, 1100), width=1000, height=900) == (0, 0, 1000, 900)

    def test_no_change_inside(self):
        assert clamp_bbox((10, 20, 30, 40), width=1000, height=900) == (10, 20, 30, 40)


class TestToYoloLine:
    def test_roundtrip(self):
        line = to_yolo_line(37, (400, 300, 600, 700), width=1000, height=1000)
        assert line == "37 0.500000 0.500000 0.200000 0.400000"

    def test_bounds_check(self):
        with pytest.raises(ValueError):
            to_yolo_line(0, (-1, 0, 10, 10), width=100, height=100)


class TestRefineOne:
    """refine_one(orig_box, sam_box, img_size, tol) → (final_box, source)。"""

    def test_accept_tight_box(self):
        final, src = refine_one((100, 100, 200, 300), (110, 120, 190, 290),
                                width=1000, height=1000)
        assert final == (110, 120, 190, 290)
        assert src == "sam"

    def test_sam_none_fallback(self):
        final, src = refine_one((100, 100, 200, 300), None, width=1000, height=1000)
        assert final == (100, 100, 200, 300)
        assert src == "orig"

    def test_sam_invalid_fallback(self):
        # SAM 给了个退化框
        final, src = refine_one((100, 100, 200, 300), (50, 50, 50, 50),
                                width=1000, height=1000)
        assert final == (100, 100, 200, 300)
        assert src == "orig"

    def test_sam_escapes_too_far_fallback(self):
        # SAM 框几乎完全跑出原框（中心都不在原框内）→ 拒绝
        final, src = refine_one((100, 100, 200, 200), (500, 500, 600, 600),
                                width=1000, height=1000)
        assert final == (100, 100, 200, 200)
        assert src == "orig"

    def test_sam_slightly_outside_clipped(self):
        # SAM 框略微超出原框但在容忍带内：接受并裁剪到原框+容忍带与图像交集
        final, src = refine_one((100, 100, 200, 300), (90, 105, 210, 295),
                                width=1000, height=1000, tol=0.25)
        assert src == "sam"
        assert final == (90, 105, 210, 295)

    def test_sam_much_larger_fallback(self):
        # SAM 框面积超过原框 4 倍 → 背景误分割，回退
        orig = (100, 100, 200, 200)  # 100x100=10000
        final, src = refine_one(orig, (0, 0, 300, 300), width=1000, height=1000)  # 90000 > 4x
        assert final == orig
        assert src == "orig"

    def test_center_must_stay_inside(self):
        # 中心点保留在原框内才接受（即使面积合法）
        final, src = refine_one((100, 100, 200, 200), (150, 150, 400, 400),
                                width=1000, height=1000)
        # 中心 (275,275) 不在原框 → 回退
        assert src == "orig"


class TestWriteYoloLabel:
    def test_write_and_parse_roundtrip(self, tmp_path):
        rows = [("37", (400, 300, 600, 700)), ("106", (100, 100, 200, 300))]
        p = tmp_path / "a.txt"
        write_yolo_label(p, rows, width=1000, height=1000)
        text = p.read_text(encoding="utf-8")
        assert text.splitlines()[0] == "37 0.500000 0.500000 0.200000 0.400000"
        assert len(text.splitlines()) == 2
