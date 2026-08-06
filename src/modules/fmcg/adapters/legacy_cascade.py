"""VLM-006：legacy Cascade（8091）分阶段适配器。

包装 CascadeRecognizer 的只读 detect_regions()/classify_region()；
recognize() 兼容入口不受影响。异常统一映射为 CapabilityAdapterError。
"""

from __future__ import annotations

from typing import Any

from src.modules.fmcg.adapters import CapabilityAdapterError
from src.modules.fmcg.cascade.manifest import CAP_DETECT, CAP_FAST_SKU


class LegacyCascadeAdapter:
    """覆盖 CAP_DETECT（检测）与 CAP_FAST_SKU（快速闭集分类）两项能力。"""

    capability_ids = (CAP_DETECT, CAP_FAST_SKU)

    def __init__(self, recognizer: Any) -> None:
        self._r = recognizer

    def detect_regions(self, image_bytes: bytes, *, conf: float = 0.25) -> list[dict]:
        try:
            return self._r.detect_regions(image_bytes, conf=conf)
        except Exception as e:
            raise CapabilityAdapterError(f"detect_regions 失败: {e}") from e

    def classify_region(self, image_bytes: bytes, box, *, topk: int = 5) -> dict:
        try:
            return self._r.classify_region(image_bytes, box, topk=topk)
        except Exception as e:
            raise CapabilityAdapterError(f"classify_region 失败: {e}") from e

    def model_versions(self) -> dict[str, str]:
        mv = getattr(self._r, "model_versions", None)
        if mv is None:
            return {}
        try:
            return mv() if callable(mv) else dict(mv)
        except Exception as e:
            raise CapabilityAdapterError(f"model_versions 读取失败: {e}") from e
