"""N2 Task 4：严格质量 Pipeline 契约（02 设计 §3）。

- 多维 analyzer（模糊/反光/倾斜/曝光/摩尔纹/主体过小/点越界）；
- 四级结论 accepted/hard_valid/manual_review/rejected；
- policy 版本化：阈值变化产生新 policy_version，不覆盖旧结论；
- 不确定 → manual_review（fail-closed，不静默放行）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.modules.nextgen_data.quality import (
    QualityDecisionError,
    QualityPolicy,
    analyze_image,
)


def _write_img(tmp_path: Path, name: str, kind: str) -> Path:
    import numpy as np
    from PIL import Image
    h, w = 480, 360
    if kind == "normal":
        rng = np.random.default_rng(7)
        arr = rng.integers(60, 200, (h, w, 3), dtype=np.uint8)
        # 加清晰竖直边缘（货架感）
        for x in range(0, w, 40):
            arr[:, x:x+4] = (30, 30, 30)
    elif kind == "blur":
        arr = np.full((h, w, 3), 128, dtype=np.uint8)
        arr = np.repeat(np.repeat(arr[::8, ::8], 8, 0), 8, 1)[:h, :w]
    elif kind == "overexposed":
        arr = np.full((h, w, 3), 252, dtype=np.uint8)
    elif kind == "white_wall":
        arr = np.full((h, w, 3), 240, dtype=np.uint8)
    else:
        raise ValueError(kind)
    p = tmp_path / name
    Image.fromarray(arr).save(p)
    return p


class TestDecisions:
    def test_four_tiers_frozen(self):
        assert QualityPolicy.TIERS == (
            "accepted", "hard_valid", "manual_review", "rejected")

    def test_blurry_image_not_accepted(self, tmp_path):
        p = _write_img(tmp_path, "blur.jpg", "blur")
        d = analyze_image(p, points=[(100, 100)] * 5,
                          width=360, height=480,
                          policy=QualityPolicy(version="qpol_n2_v1"))
        assert d["conclusion"] in ("manual_review", "rejected")
        assert d["scores"]["blur"] is not None
        assert d["policy_version"] == "qpol_n2_v1"

    def test_overexposed_flagged(self, tmp_path):
        p = _write_img(tmp_path, "over.jpg", "overexposed")
        d = analyze_image(p, points=[(10, 10)], width=360, height=480,
                          policy=QualityPolicy(version="qpol_n2_v1"))
        assert d["conclusion"] != "accepted" or d["scores"]["exposure"] > 0

    def test_out_of_bounds_points_rejected(self, tmp_path):
        p = _write_img(tmp_path, "n.jpg", "normal")
        with pytest.raises(QualityDecisionError):
            analyze_image(p, points=[(5000, 90)], width=360, height=480,
                          policy=QualityPolicy(version="qpol_n2_v1"),
                          strict_bounds=True)

    def test_no_points_manual_review(self, tmp_path):
        # 空点照片不能当无商品真值，进人工
        p = _write_img(tmp_path, "n2.jpg", "normal")
        d = analyze_image(p, points=[], width=360, height=480,
                          policy=QualityPolicy(version="qpol_n2_v1"))
        assert d["conclusion"] == "manual_review"

    def test_policy_version_change_is_new_version(self):
        p1 = QualityPolicy(version="qpol_n2_v1")
        p2 = p1.with_threshold(blur_max=p1.thresholds["blur_max"] * 0.5)
        assert p2.version != p1.version
        assert p2.version.startswith("qpol_n2_v1+")


class TestEvidence:
    def test_decision_has_analyzer_evidence(self, tmp_path):
        p = _write_img(tmp_path, "n3.jpg", "normal")
        d = analyze_image(p, points=[(50, 60), (100, 120)],
                          width=360, height=480,
                          policy=QualityPolicy(version="qpol_n2_v1"))
        for k in ("conclusion", "scores", "policy_version", "reasons",
                  "sha256", "width", "height"):
            assert k in d
        assert isinstance(d["reasons"], list)
