"""四级照片质量策略契约（手册§八 / Gate Q0）：
accept / warn / manual_review / reject。
- reject precision 优先：不可恢复才 reject；
- 单一弱指标绝不自动 reject；
- 困难但有效照片打 hard_valid 标签保留（不只训练完美照片）。"""
import numpy as np

from src.data_quality.analyzers import (
    analyze_blur,
    analyze_exposure,
    analyze_readability,
    analyze_tilt,
)
from src.data_quality.contracts import Finding, QualityVerdict, VERDICTS
from src.data_quality.policy import POLICY_VERSION, decide


def _f(name, severity, recoverable=True, detail=""):
    return Finding(name=name, severity=severity, recoverable=recoverable, detail=detail)


def test_verdict_levels_are_exactly_four():
    assert VERDICTS == ("accept", "warn", "manual_review", "reject")


def test_clean_image_accepts():
    v = decide([], metrics={}, image_sha256="a" * 64)
    assert v.verdict == "accept"
    assert isinstance(v, QualityVerdict)
    assert v.policy_version == POLICY_VERSION
    assert v.image_sha256 == "a" * 64


def test_single_weak_signal_never_rejects():
    """手册§八：任何照片只因单一弱指标触发时不得自动 reject。"""
    v = decide([_f("blur", "weak")], metrics={}, image_sha256="a" * 64)
    assert v.verdict in ("warn", "manual_review")
    assert v.verdict != "reject"


def test_weak_signals_become_hard_valid_warn():
    """手册§一.12：困难但可识别照片保留为带质量标签的 hard-valid。"""
    v = decide([_f("reflection", "weak")], metrics={}, image_sha256="a" * 64)
    assert v.verdict == "warn"
    assert "hard_valid" in v.quality_tags
    assert "reflection" in v.quality_tags


def test_single_strong_recoverable_goes_manual_review():
    v = decide([_f("tilt", "strong", recoverable=True)], metrics={}, image_sha256="a" * 64)
    assert v.verdict == "manual_review"


def test_uncertain_recoverability_goes_manual_review():
    v = decide([_f("tilt", "weak", recoverable=None)], metrics={}, image_sha256="a" * 64)
    assert v.verdict == "manual_review"


def test_unrecoverable_strong_signal_rejects():
    v = decide([_f("decode_fail", "strong", recoverable=False)],
               metrics={}, image_sha256="a" * 64)
    assert v.verdict == "reject"
    assert "decode_fail" in v.reasons


def test_two_strong_signals_reject_but_one_weak_plus_one_weak_not():
    v = decide([_f("product_blur", "strong", recoverable=False),
                _f("moire", "strong", recoverable=False)],
               metrics={}, image_sha256="a" * 64)
    assert v.verdict == "reject"
    v2 = decide([_f("blur", "weak"), _f("moire", "weak")],
                metrics={}, image_sha256="a" * 64)
    assert v2.verdict != "reject"


def test_reject_keeps_original_never_moves_bytes():
    """手册§八：reject 只从训练 manifest 排除，原图保留。"""
    v = decide([_f("decode_fail", "strong", recoverable=False)],
               metrics={}, image_sha256="a" * 64)
    assert v.keep_original is True


def test_verdict_carries_metrics_and_versions():
    v = decide([_f("blur", "weak")], metrics={"laplacian": 12.3},
               image_sha256="b" * 64)
    assert v.metrics["laplacian"] == 12.3
    assert v.policy_version
    assert v.analyzer_version


# ---- 分析器（合成图像）----

def test_readability_extreme_aspect_flags_weak():
    img = np.full((100, 2000, 3), 128, np.uint8)  # 1:20 极端长宽比
    findings, metrics = analyze_readability(img)
    names = [f.name for f in findings]
    assert "extreme_aspect" in names


def test_blur_roi_vs_background_distinction():
    """手册§八.2：区分背景模糊但商品可读 vs 商品主体不可读。"""
    img = np.random.default_rng(0).integers(0, 255, (400, 300, 3), dtype=np.uint8)
    roi = (100, 100, 200, 300)
    import cv2
    sharp_roi = img.copy()
    findings, metrics = analyze_blur(sharp_roi, roi)
    assert not any(f.name == "product_blur" for f in findings)

    blurred = cv2.GaussianBlur(img, (0, 0), 12)
    findings2, metrics2 = analyze_blur(blurred, roi)
    names = [f.name for f in findings2]
    assert any(n in names for n in ("product_blur", "blur"))


def test_exposure_reflection_in_roi_flags_weak_or_strong():
    img = np.full((400, 300, 3), 100, np.uint8)
    roi = (50, 50, 250, 350)
    img[50:350, 50:250] = 252  # ROI 内大面积过曝（反光遮挡）
    findings, metrics = analyze_exposure(img, roi)
    names = [f.name for f in findings]
    assert any(n in names for n in ("reflection", "overexposure"))


def test_tilt_straight_image_no_finding():
    img = np.zeros((400, 300, 3), np.uint8)
    img[:, :] = 60
    img[100:110, :] = 250   # 水平货架线
    img[250:260, :] = 250
    findings, metrics = analyze_tilt(img)
    strong = [f for f in findings if f.severity == "strong"]
    assert not strong
