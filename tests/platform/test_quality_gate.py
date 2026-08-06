"""SAM 精修前置质量门禁纯函数测试（TDD 红测试先行）。

三维：模糊（blur）、反光（reflection）、货架倾斜（tilt）。
口径：分数越高问题越严重，score > threshold → 该维 fail；
任一维 fail → 整图 reject。用户指令：可适当提高门槛（更严）。"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageFilter

from src.training.quality_gate import (
    assess_quality,
    blur_score,
    decide_quality,
    gate_decision,
    reflection_score,
    tilt_score,
    THRESHOLDS,
)


def _sharp_shelf(size=(640, 480), angle=0.0) -> Image.Image:
    """合成清晰货架图：水平层板线 + 竖直瓶身条纹。angle 为整体旋转角。"""
    w, h = size
    arr = np.full((h, w), 40, dtype=np.uint8)  # 暗背景
    # 五条水平亮层板线
    for y in range(60, h, 80):
        arr[y:y + 4, :] = 230
    # 竖直瓶身条纹
    for x in range(20, w, 40):
        arr[60:, x:x + 12] = 180
    img = Image.fromarray(arr)
    if angle:
        img = img.rotate(angle, expand=False, fillcolor=40)
    return img.convert("RGB")


class TestBlurScore:
    def test_sharp_lower_than_blurred(self):
        img = _sharp_shelf()
        sharp = blur_score(np.asarray(img.convert("L"), dtype=np.float64))
        blurred = blur_score(np.asarray(
            img.filter(ImageFilter.GaussianBlur(6)).convert("L"),
            dtype=np.float64))
        assert blurred > sharp

    def test_score_bounds(self):
        img = _sharp_shelf()
        s = blur_score(np.asarray(img.convert("L"), dtype=np.float64))
        assert 0.0 <= s <= 1.0

    def test_uniform_image_is_blurry(self):
        gray = np.full((200, 200), 128.0)
        assert blur_score(gray) > 0.99  # 零纹理 → 接近最大模糊分


class TestReflectionScore:
    def test_overexposed_higher(self):
        base = np.asarray(_sharp_shelf().convert("L"), dtype=np.float64)
        glare = base.copy()
        glare[:, :glare.shape[1] // 3] = 255  # 三分之一画面过曝
        assert reflection_score(glare) > reflection_score(base)

    def test_no_glare_near_zero(self):
        base = np.asarray(_sharp_shelf().convert("L"), dtype=np.float64)
        assert reflection_score(base) < 0.05


class TestTiltScore:
    def test_straight_low(self):
        img = _sharp_shelf(angle=0.0)
        s = tilt_score(np.asarray(img.convert("L"), dtype=np.float64))
        assert s < THRESHOLDS["tilt"]

    def test_tilted_higher_than_straight(self):
        straight = tilt_score(np.asarray(
            _sharp_shelf(angle=0.0).convert("L"), dtype=np.float64))
        tilted = tilt_score(np.asarray(
            _sharp_shelf(angle=10.0).convert("L"), dtype=np.float64))
        assert tilted > straight

    def test_severe_tilt_fails(self):
        s = tilt_score(np.asarray(
            _sharp_shelf(angle=15.0).convert("L"), dtype=np.float64))
        assert s > THRESHOLDS["tilt"]

    def test_score_bounds(self):
        s = tilt_score(np.asarray(
            _sharp_shelf(angle=7.0).convert("L"), dtype=np.float64))
        assert 0.0 <= s <= 1.0


class TestGateDecision:
    def _scores(self, **kw):
        base = {"blur": 0.1, "reflection": 0.05, "tilt": 0.05}
        base.update(kw)
        return base

    def test_all_pass(self):
        ok, reasons = gate_decision(self._scores())
        assert ok is True and reasons == []

    def test_blur_fail(self):
        ok, reasons = gate_decision(self._scores(blur=THRESHOLDS["blur"] + 0.01))
        assert ok is False and "blur" in reasons

    def test_reflection_fail(self):
        ok, reasons = gate_decision(
            self._scores(reflection=THRESHOLDS["reflection"] + 0.01))
        assert ok is False and "reflection" in reasons

    def test_tilt_fail(self):
        ok, reasons = gate_decision(self._scores(tilt=THRESHOLDS["tilt"] + 0.01))
        assert ok is False and "tilt" in reasons

    def test_multiple_fail_reasons(self):
        ok, reasons = gate_decision(self._scores(blur=0.99, tilt=0.99))
        assert ok is False and set(reasons) == {"blur", "tilt"}

    def test_boundary_equal_threshold_passes(self):
        # 口径：score > threshold 才 fail；等于阈值不 fail
        ok, _ = gate_decision(self._scores(blur=THRESHOLDS["blur"]))
        assert ok is True


class TestDispositionPolicyV2:
    """VLM-008：缺水平线→manual_review；单一弱启发式不得自动 reject。"""

    def test_missing_horizontal_lines_requires_review_not_auto_reject(self):
        out = assess_quality(np.zeros((64, 64), dtype=np.uint8))
        assert out.disposition == "manual_review"
        assert "tilt_unobservable" in out.reason_codes

    def test_single_weak_heuristic_cannot_auto_reject(self):
        out = decide_quality({"blur": 0.46, "reflection": 0.0, "tilt": None})
        assert out.disposition in {"warn", "manual_review"}

    def test_single_fail_all_observable_is_warn(self):
        out = decide_quality({"blur": 0.5, "reflection": 0.0, "tilt": 0.1})
        assert out.disposition == "warn"

    def test_multi_strong_signals_reject(self):
        out = decide_quality({"blur": 0.9, "reflection": 0.8, "tilt": 0.9})
        assert out.disposition == "reject"

    def test_all_observable_pass(self):
        out = decide_quality({"blur": 0.1, "reflection": 0.0, "tilt": 0.1})
        assert out.disposition == "pass" and out.reason_codes == ()

    def test_sharp_shelf_not_auto_rejected(self):
        gray = np.asarray(_sharp_shelf().convert("L"))
        out = assess_quality(gray)
        assert "tilt_unobservable" not in out.reason_codes
        assert out.disposition != "reject"

    def test_verdict_keeps_evidence(self):
        out = decide_quality({"blur": 0.46, "reflection": 0.0, "tilt": None})
        assert out.policy_version
        assert out.scores["tilt"] is None
        assert out.thresholds == THRESHOLDS
