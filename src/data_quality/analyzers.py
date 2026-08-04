"""照片质量分析器集（手册§八，analyzer_version=qa_v1）。

每个分析器签名统一为 (img[, roi]) -> (findings, metrics)：
- img: BGR uint8 ndarray
- roi: (x1, y1, x2, y2)，无提示时传 None（全图）

原则（Gate Q0，reject precision 优先）：
- 单一弱指标至多 warn；只有"不可恢复"或强信号组合才 reject（policy.py 负责）；
- 分析器宁可给 weak / recoverable=None（→人工），也不给错误的强 reject；
- 阈值是初值，上线前必须在独立校准集复核（禁用 diagnostic_v1，手册§一.5）。"""
from __future__ import annotations

import cv2
import numpy as np

from .contracts import Finding


def _crop(img: np.ndarray, roi):
    if roi is None:
        return img
    x1, y1, x2, y2 = roi
    h, w = img.shape[:2]
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(w, int(x2)), min(h, int(y2))
    if x2 <= x1 or y2 <= y1:
        return img
    return img[y1:y2, x1:x2]


def _gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


def _lap_var(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def analyze_blur(img: np.ndarray, roi=None):
    """手册§八.2：区分背景模糊（景深，商品仍可读）与商品主体模糊。

    有 ROI 时以 ROI 清晰度为准：
    - ROI 糊 → 商品主体不可读 → product_blur（strong，不可恢复）
    - ROI 清晰但全图糊 → 背景虚化（景深）→ background_blur（weak，保留）
    - 无 ROI 且全图糊 → blur（weak，交人工判断，不自动 reject）"""
    g = _gray(img)
    whole = _lap_var(g)
    metrics = {"laplacian_whole": round(whole, 3)}
    findings: list = []

    if roi is not None:
        g_roi = _gray(_crop(img, roi))
        roi_v = _lap_var(g_roi)
        metrics["laplacian_roi"] = round(roi_v, 3)
        if roi_v < 40.0:
            findings.append(Finding("product_blur", "strong", recoverable=False,
                                    detail=f"roi={roi_v:.1f} whole={whole:.1f}"))
        elif whole < 30.0:
            findings.append(Finding("background_blur", "weak", recoverable=True,
                                    detail=f"roi={roi_v:.1f} whole={whole:.1f}"))
    else:
        if whole < 30.0:
            findings.append(Finding("blur", "weak", recoverable=None,
                                    detail=f"whole={whole:.1f}"))
    return findings, metrics


def analyze_exposure(img: np.ndarray, roi=None):
    """手册§八.3：过曝/反光（ROI 内大面积饱和白）与欠曝（全黑不可读）。"""
    crop = _crop(img, roi)
    gray = _gray(crop)
    sat = float((gray >= 250).mean())
    dark = float((gray <= 12).mean())
    metrics = {"roi_sat_frac": round(sat, 4), "roi_dark_frac": round(dark, 4)}
    findings: list = []

    if sat >= 0.7:
        findings.append(Finding("overexposure", "strong", recoverable=False,
                                detail=f"sat={sat:.2f}"))
    elif sat >= 0.25:
        findings.append(Finding("overexposure", "weak", recoverable=True,
                                detail=f"sat={sat:.2f}"))
    if sat >= 0.25:
        findings.append(Finding("reflection", "weak", recoverable=True,
                                detail=f"sat={sat:.2f}"))
    if dark >= 0.8:
        findings.append(Finding("underexposure", "strong", recoverable=False,
                                detail=f"dark={dark:.2f}"))
    return findings, metrics


def analyze_tilt(img: np.ndarray):
    """手册§八.5：严重斜拍。对边缘方向做圆形直方图，主方向偏离 0/90°
    且方向集中度高时判 tilt。单张不自动 reject（可恢复性交人工/纠偏）。"""
    g = _gray(img)
    edges = cv2.Canny(g, 50, 150)
    metrics: dict = {"edge_density": round(float(edges.mean() / 255.0), 4)}
    if edges.mean() < 2.0:
        return [], metrics  # 无足够结构，不作判定

    ys, xs = np.nonzero(edges)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)[ys, xs]
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)[ys, xs]
    theta = np.mod(np.degrees(np.arctan2(gy, gx)), 180.0)  # 边缘切向
    deg = np.radians(theta * 2.0)
    R = float(np.hypot(np.cos(deg).mean(), np.sin(deg).mean()))  # 集中度 0..1
    dom = float(np.degrees(np.arctan2(np.sin(deg).mean(),
                                      np.cos(deg).mean())) / 2.0) % 90.0
    tilt = min(dom, 90.0 - dom)
    metrics.update({"dominant_line_deg": round(tilt, 2),
                    "direction_concentration": round(R, 3)})
    if R > 0.55 and tilt > 8.0:
        return ([Finding("tilt", "strong", recoverable=None,
                         detail=f"tilt={tilt:.1f}deg R={R:.2f}")], metrics)
    return [], metrics


def analyze_readability(img: np.ndarray):
    """手册§八.7/远近距离与画幅异常：极端长宽比/超大图通常来自裁切或翻拍，
    只打 weak 标签，不自动 reject。"""
    h, w = img.shape[:2]
    aspect = max(w, h) / max(1, min(w, h))
    metrics = {"width": int(w), "height": int(h), "aspect": round(aspect, 3)}
    findings: list = []
    if aspect >= 4.0:
        findings.append(Finding("extreme_aspect", "weak", recoverable=None,
                                detail=f"aspect={aspect:.1f}"))
    return findings, metrics


def analyze_moire(img: np.ndarray):
    """手册§八.4：翻拍屏幕的摩尔纹（中频周期性能量异常）。
    启发式初值，误报走 manual_review（recoverable=None）。"""
    g = cv2.resize(_gray(img), (512, 512))
    f = np.fft.fftshift(np.fft.fft2(g.astype(np.float32)))
    mag = np.abs(f)
    H, W = mag.shape
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.hypot(yy - H / 2, xx - W / 2) / (H / 2)
    mid = float(mag[(r > 0.12) & (r < 0.55)].mean())
    base = float(mag[r > 0.12].mean() + 1e-6)
    ratio = mid / base
    metrics = {"moire_midband_ratio": round(ratio, 4)}
    if ratio > 1.35:
        return ([Finding("moire", "strong", recoverable=None,
                         detail=f"ratio={ratio:.2f}")], metrics)
    return [], metrics


def analyze_coverage(img: np.ndarray, roi=None):
    """手册§八.7：商品占比过小（远距离）→ weak distance_far；
    占比过大且贴边 → 裁切风险 weak crop_risk。"""
    h, w = img.shape[:2]
    metrics: dict = {}
    if roi is None:
        return [], metrics
    x1, y1, x2, y2 = roi
    frac = max(0.0, (x2 - x1) * (y2 - y1)) / max(1, w * h)
    metrics["roi_area_frac"] = round(float(frac), 4)
    findings: list = []
    if frac < 0.01:
        findings.append(Finding("distance_far", "weak", recoverable=True,
                                detail=f"frac={frac:.4f}"))
    touches = int(x1 <= 1) + int(y1 <= 1) + int(x2 >= w - 1) + int(y2 >= h - 1)
    if frac > 0.45 and touches >= 2:
        findings.append(Finding("crop_risk", "weak", recoverable=None,
                                detail=f"frac={frac:.2f} touches={touches}"))
    return findings, metrics


def analyze_big_foreground(img: np.ndarray):
    """手册§八.6：大头照/单一前景占满（非货架场景）。
    启发式：中心区域与边缘差异大且整体低纹理 → weak，交人工。"""
    g = _gray(img)
    h, w = g.shape
    center = g[h // 4: 3 * h // 4, w // 4: 3 * w // 4]
    border = np.concatenate([g[: h // 8].ravel(), g[-h // 8:].ravel()])
    diff = abs(float(center.mean()) - float(border.mean()))
    tex = _lap_var(g)
    metrics = {"center_border_diff": round(diff, 2), "texture": round(tex, 2)}
    if diff > 60.0 and tex < 40.0:
        return ([Finding("big_foreground", "weak", recoverable=None,
                         detail=f"diff={diff:.0f}")], metrics)
    return [], metrics
