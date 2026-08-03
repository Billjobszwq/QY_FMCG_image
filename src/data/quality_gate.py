"""图像前置质量拦截器（阶段一 · 训练数据清洗护栏）。

基于 OpenCV 的三重检测，在新照片进入 Label Studio / 训练集之前拦截坏图：
  1. 模糊检测：Laplacian 方差（阈值**放宽**——330ml 小拉罐等微距目标像素不足，防误杀）
  2. 严重反光检测：HSV 高亮低饱和面积比（重点严查）
  3. 翻拍/屏幕检测：FFT 摩尔纹中频峰值能量（重点严查）

分流：通过=好图 → Label Studio；未通过=坏图 → bad_samples/ 加后缀(_blurry/_reflection/_screen)。

用法：
  from src.data.quality_gate import QualityGate
  gate = QualityGate()
  verdict = gate.check(image_bgr_or_path)  # {"pass": bool, "reasons": [...], "metrics": {...}}
"""
from __future__ import annotations

import cv2
import numpy as np


class QualityGate:
    def __init__(self, blur_thresh: float = 40.0, reflect_ratio: float = 0.18,
                 moire_ratio: float = 1.65, max_side: int = 900):
        """阈值说明（已在 40 张真实货架好图上校准）：
        blur_thresh   Laplacian 方差下限；低于则判模糊。**刻意放宽**(40)防误杀微距小罐；好图 min=291。
        reflect_ratio HSV 高亮(V>245 且 S<50)像素占比上限；超过判严重反光；好图 max=0.066。
        moire_ratio   FFT 中频环带最大峰/中位数比；好图分布 1.26-1.41，翻拍摩尔纹>1.65。
        max_side      检测前长边缩放到该尺寸（统一尺度、加速）。
        """
        self.blur_thresh = blur_thresh
        self.reflect_ratio = reflect_ratio
        self.moire_ratio = moire_ratio
        self.max_side = max_side

    def _resize(self, img):
        h, w = img.shape[:2]
        s = self.max_side / max(h, w)
        if s < 1.0:
            img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        return img

    def check_blur(self, gray) -> tuple[bool, float]:
        """Laplacian 方差；返回 (是否模糊, 方差值)。方差低=模糊。"""
        var = cv2.Laplacian(gray, cv2.CV_64F).var()
        return var < self.blur_thresh, float(var)

    def check_reflection(self, img) -> tuple[bool, float]:
        """HSV 高亮低饱和面积比；返回 (是否反光, 占比)。"""
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        v, s = hsv[:, :, 2], hsv[:, :, 1]
        # 过曝高光：亮度极高且几乎无色彩（镜面反光/强光源）
        mask = (v > 245) & (s < 50)
        ratio = float(mask.sum()) / mask.size
        return ratio > self.reflect_ratio, ratio

    def check_moire(self, gray) -> tuple[bool, float]:
        """FFT 摩尔纹检测；返回 (是否翻拍, 峰值/中位数比)。
        翻拍屏幕的规则像素栅格在中频环带产生远高于背景的离散尖峰。
        好图比值分布 1.26-1.41，摩尔纹显著更高，阈值取 1.65。"""
        f = np.fft.fft2(gray.astype(np.float32))
        fshift = np.fft.fftshift(f)
        mag = np.log1p(np.abs(fshift))
        h, w = mag.shape
        cy, cx = h // 2, w // 2
        yy, xx = np.ogrid[:h, :w]
        r = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
        rmax = min(cy, cx)
        band = (r > rmax * 0.2) & (r < rmax * 0.7)
        band_vals = mag[band]
        if band_vals.size == 0:
            return False, 0.0
        med = float(np.median(band_vals))
        peak = float(band_vals.max())
        ratio = peak / (med + 1e-6)
        return ratio > self.moire_ratio, ratio

    def check(self, image) -> dict:
        """image: BGR ndarray 或路径。返回 {"pass","reasons","metrics"}。"""
        if isinstance(image, (str,)):
            img = cv2.imread(image)
        elif isinstance(image, np.ndarray):
            img = image
        else:
            img = None
        if img is None:
            return {"pass": False, "reasons": ["unreadable"], "metrics": {}}
        img = self._resize(img)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        reasons = []
        is_blur, blur_var = self.check_blur(gray)
        is_refl, refl_ratio = self.check_reflection(img)
        is_moire, moire_ratio = self.check_moire(gray)

        if is_blur:
            reasons.append("blurry")
        if is_refl:
            reasons.append("reflection")
        if is_moire:
            reasons.append("screen")

        return {
            "pass": len(reasons) == 0,
            "reasons": reasons,
            "metrics": {
                "blur_var": round(blur_var, 2),
                "reflect_ratio": round(refl_ratio, 4),
                "moire_ratio": round(moire_ratio, 3),
            },
        }


if __name__ == "__main__":
    # 快速自测：对 batch1/2 若干真实照片跑一遍，看阈值分布
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from src.common.config import PROJECT_ROOT
    blobs = PROJECT_ROOT / ".training_data" / "blobs"
    gate = QualityGate()
    n = 0
    agg = {"blur": [], "refl": [], "moire": []}
    for sub in list(blobs.iterdir())[:6]:
        for bp in list(sub.iterdir())[:8]:
            v = gate.check(str(bp))
            agg["blur"].append(v["metrics"].get("blur_var", 0))
            agg["refl"].append(v["metrics"].get("reflect_ratio", 0))
            agg["moire"].append(v["metrics"].get("moire_ratio", 0))
            n += 1
            if n >= 40:
                break
        if n >= 40:
            break
    import numpy as _np
    for k, vals in agg.items():
        a = _np.array(vals)
        print(f"{k}: min={a.min():.3f} p25={_np.percentile(a,25):.3f} "
              f"median={_np.median(a):.3f} p75={_np.percentile(a,75):.3f} max={a.max():.3f}")
    print(f"\n样本数: {n}")
