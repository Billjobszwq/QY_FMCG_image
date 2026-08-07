"""N2 Task 4：严格质量 Pipeline（02 设计 §3）。

多维 analyzer：模糊/反光/曝光/倾斜/摩尔纹/点越界。四级结论；
不确定一律 manual_review（fail-closed）；policy 版本化，阈值变化
生成新版本不覆盖旧结论。自动结论必须经人工校准后才能作为过滤
终局（校准门见 02 §3.3）。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


class QualityDecisionError(RuntimeError):
    """质量判定错误（fail-closed）。"""


@dataclass(frozen=True)
class QualityPolicy:
    TIERS = ("accepted", "hard_valid", "manual_review", "rejected")

    version: str = "qpol_n2_v1"
    thresholds: dict[str, float] = field(default_factory=lambda: {
        "blur_min": 40.0,        # Laplacian 方差下限
        "blur_hard": 15.0,       # 严重模糊直接 rejected
        "reflection_max": 0.18,  # 高光像素占比上限
        "reflection_hard": 0.35,
        "exposure_lo": 40.0,     # 平均亮度区间
        "exposure_hi": 235.0,
        "tilt_max": 0.45,        # 主导角度集中度（越高越斜）
        "moire_max": 0.30,       # 高频能量占比上限
        "min_points": 1.0,
    })

    def with_threshold(self, **changes: float) -> "QualityPolicy":
        th = {**self.thresholds, **changes}
        sig = hashlib.sha256(
            str(sorted(th.items())).encode()).hexdigest()[:8]
        base = self.version.split("+")[0]
        return replace(self, thresholds=th, version=f"{base}+{sig}")


def _blur_score(gray) -> float:
    import cv2
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _reflection_score(gray) -> float:
    return float((gray > 245).mean())


def _exposure_score(gray) -> float:
    return float(gray.mean())


def _tilt_score(gray) -> float:
    """边缘方向集中度：货架正拍以水平/竖直为主，斜拍分布发散。"""
    import cv2
    import numpy as np
    edges = cv2.Canny(gray, 50, 150)
    pts = np.column_stack(np.where(edges > 0))
    if len(pts) < 200:
        return 0.0
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    ang = np.arctan2(gy[edges > 0], gx[edges > 0]) % np.pi
    hist, _ = np.histogram(ang, bins=18)
    return float(1.0 - hist.max() / hist.sum())


def _moire_score(gray) -> float:
    import cv2
    import numpy as np
    f = np.fft.rfft2(gray.astype(np.float32))
    mag = np.abs(f)
    h, w = mag.shape
    total = mag.sum() + 1e-9
    hi = mag[int(h * 0.35):, int(w * 0.35):]
    return float(hi.sum() / total)


def analyze_image(path: Path | str, *, points: list,
                  width: int, height: int,
                  policy: QualityPolicy,
                  strict_bounds: bool = False) -> dict[str, Any]:
    import cv2
    import numpy as np
    from PIL import Image

    path = Path(path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        img = Image.open(path)
        real_w, real_h = img.size
    except Exception as e:
        raise QualityDecisionError(f"解码失败: {path}: {e}")

    if strict_bounds:
        for (x, y) in points:
            if not (0 <= float(x) <= width and 0 <= float(y) <= height):
                raise QualityDecisionError(
                    f"坐标点越界: ({x},{y}) 超出 {width}x{height}")

    gray = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2GRAY)
    th = policy.thresholds
    scores = {
        "blur": _blur_score(gray),
        "reflection": _reflection_score(gray),
        "exposure": _exposure_score(gray),
        "tilt": _tilt_score(gray),
        "moire": _moire_score(gray),
        "n_points": len(points),
        "width": real_w, "height": real_h,
    }
    reasons: list[str] = []
    hard = False
    soft = 0

    if scores["blur"] < th["blur_hard"]:
        reasons.append("severe_blur"); hard = True
    elif scores["blur"] < th["blur_min"]:
        reasons.append("blur"); soft += 1
    if scores["reflection"] > th["reflection_hard"]:
        reasons.append("severe_reflection"); hard = True
    elif scores["reflection"] > th["reflection_max"]:
        reasons.append("reflection"); soft += 1
    if not (th["exposure_lo"] <= scores["exposure"] <= th["exposure_hi"]):
        reasons.append("exposure_out_of_range"); soft += 1
    if scores["tilt"] > th["tilt_max"]:
        reasons.append("tilt_suspect"); soft += 1
    if scores["moire"] > th["moire_max"]:
        reasons.append("moire_suspect"); soft += 1
    if len(points) < int(th["min_points"]):
        reasons.append("no_points_not_truth")

    if hard:
        conclusion = "rejected"
    elif not points:
        conclusion = "manual_review"
    elif soft >= 2:
        conclusion = "manual_review"
    elif soft == 1:
        conclusion = "hard_valid"
    else:
        conclusion = "accepted"

    return {"sha256": sha, "width": real_w, "height": real_h,
            "conclusion": conclusion, "scores": scores,
            "reasons": reasons, "policy_version": policy.version}
