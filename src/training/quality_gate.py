"""SAM 精修前置质量门禁纯函数：模糊 / 反光 / 货架倾斜。

口径（用户指令：全照片先筛反光、货架倾斜、模糊，可适当提高门槛）：
- 分数越高问题越严重；score > threshold → 该维 fail；任一维 fail → reject。
- blur/reflection 沿用 qpol_v2 启发式口径（Laplacian 方差、近白占比），
  阈值相对 qpol_v2 收紧（更严）；tilt 为 HoughLinesP 直线角度启发式。
- fail-closed：无法估计倾斜（水平直线段不足）时 tilt_score 返回最高分。

V2 处置口径（VLM-008，计划 §Task 8）：
- “检测不到足够水平线”是 unobservable，不是“严重倾斜”，
  必须进 manual_review，不得自动 reject；
- 单一弱启发式不得自动 reject；自动 reject 需多强信号（≥2 维 fail）
  或人工 final verdict；旧 934 张 tilt reject 保留历史证据不改写。
gate_decision（V1 口径）保留向后兼容，新链路一律用 decide_quality。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

QUALITY_GATE_VERSION = "quality-gate.v2"
DISPOSITIONS = ("pass", "warn", "manual_review", "reject")

# 分数 > 阈值 → 该维 fail（相对 qpol_v2 的 0.5/0.4 收紧）
THRESHOLDS: dict[str, float] = {
    "blur": 0.45,
    "reflection": 0.35,
    "tilt": 0.40,
}

BLUR_VAR_REF = 120.0        # qpol_v2 同款归一参考
GLARE_GRAY = 250            # 近白判定灰度
MAX_TILT_DEG = 15.0         # tilt_score 归一满刻度（度）
HORIZ_BAND_DEG = 25.0       # 只统计与水平夹角小于该值的直线段
MIN_HORIZ_LINES = 5         # 水平直线段不足 → fail-closed


def blur_score(gray: np.ndarray) -> float:
    """Laplacian 方差越低越模糊；归一为 [0,1]（qpol_v2 同款）。"""
    from scipy.ndimage import convolve

    kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float64)
    lap = convolve(gray.astype(np.float64), kernel)
    var = float(lap.var())
    return float(max(0.0, min(1.0, 1.0 - var / BLUR_VAR_REF)))


def reflection_score(gray: np.ndarray) -> float:
    """近白像素占比作为反光/过曝信号（qpol_v2 同款）。"""
    return float((gray > GLARE_GRAY).mean())


def tilt_observed(gray: np.ndarray,
                  *, max_tilt_deg: float = MAX_TILT_DEG) -> float | None:
    """同 tilt_score，但水平直线段不足时返回 None（unobservable）而非 1.0。"""
    import cv2

    g = gray.astype(np.uint8) if gray.dtype != np.uint8 else gray
    edges = cv2.Canny(g, 50, 150)
    min_len = max(int(g.shape[1] * 0.02), 16)   # 至少 2% 图宽
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=60,
                            minLineLength=min_len, maxLineGap=12)
    if lines is None:
        return None
    segs = lines.reshape(-1, 4).astype(np.float64)
    dx = segs[:, 2] - segs[:, 0]
    dy = segs[:, 3] - segs[:, 1]
    ang = np.degrees(np.arctan2(dy, dx))            # [-180, 180]
    ang = (ang + 90.0) % 180.0 - 90.0               # 线方向归到 [-90, 90)
    horiz = np.abs(ang) < HORIZ_BAND_DEG
    if int(horiz.sum()) < MIN_HORIZ_LINES:
        return None
    w = np.hypot(dx, dy)
    dev = float(abs(np.average(ang[horiz], weights=w[horiz])))
    return float(max(0.0, min(1.0, dev / max_tilt_deg)))


def tilt_score(gray: np.ndarray, *, max_tilt_deg: float = MAX_TILT_DEG) -> float:
    """货架倾斜分：HoughLinesP 检出的近水平直线段，按长度加权取主导
    方向与水平的夹角（度）/ max_tilt_deg。[0,1]。

    层板线应为水平；整体偏离越大分越高。
    fail-closed：检出的水平直线段不足时返回 1.0（V1 口径；
    新链路请用 tilt_observed/decide_quality，unobservable 进人工复核）。"""
    t = tilt_observed(gray, max_tilt_deg=max_tilt_deg)
    return 1.0 if t is None else t


def gate_decision(scores: dict[str, float],
                  thresholds: dict[str, float] | None = None) -> tuple[bool, list[str]]:
    """整图门禁：任一维 score > threshold → reject。

    返回 (ok, reject_reasons)。score == threshold 不 fail（严格大于才 fail）。
    V1 口径保留向后兼容；新链路请用 decide_quality（V2 处置）。"""
    th = thresholds or THRESHOLDS
    reasons = [name for name, t in th.items() if scores.get(name, 0.0) > t]
    return (len(reasons) == 0), sorted(reasons)


@dataclass(frozen=True)
class QualityVerdict:
    """V2 处置结果：disposition + 原因码 + 全部证据（分数/阈值/规则版本）。"""

    disposition: str                     # pass / warn / manual_review / reject
    reason_codes: tuple[str, ...]
    scores: dict[str, float | None]      # None = unobservable
    thresholds: dict[str, float]
    policy_version: str = QUALITY_GATE_VERSION


def decide_quality(scores: dict[str, float | None],
                   thresholds: dict[str, float] | None = None) -> QualityVerdict:
    """V2 处置（VLM-008 红线）：

    - 任一维 None（不可观测，如缺水平线）→ manual_review，不得自动 reject；
    - 单一弱启发式（仅 1 维 fail）→ warn，不得自动 reject；
    - 自动 reject 需要 ≥2 维 fail（多强信号）；人工 final verdict 另行裁决；
    - 全部可观测且无超阈 → pass。
    """
    th = thresholds or THRESHOLDS
    failed: list[str] = []
    codes: list[str] = []
    for name in th:
        v = scores.get(name)
        if v is None:
            codes.append(f"{name}_unobservable")
        elif v > th[name]:
            failed.append(name)
            codes.append(f"{name}_fail")
    if any(c.endswith("_unobservable") for c in codes):
        disposition = "manual_review"
    elif len(failed) >= 2:
        disposition = "reject"
    elif len(failed) == 1:
        disposition = "warn"
    else:
        disposition = "pass"
    return QualityVerdict(disposition, tuple(sorted(codes)),
                          dict(scores), dict(th))


def assess_quality(gray: np.ndarray,
                   thresholds: dict[str, float] | None = None) -> QualityVerdict:
    """三维打分 + V2 处置：倾斜不可观测时返回 None（manual_review），
    不再以 tilt=1.0 自动 reject。"""
    g = gray.astype(np.float64) if gray.dtype != np.float64 else gray
    scores: dict[str, float | None] = {
        "blur": blur_score(g),
        "reflection": reflection_score(g),
        "tilt": tilt_observed(gray),
    }
    return decide_quality(scores, thresholds)
