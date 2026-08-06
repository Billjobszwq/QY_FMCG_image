"""VLM-006：场景/价签分类适配器（S0 场景检查）。

红线：没有足够模型或人工证据时必须输出 unknown 并交人工/后续能力，
不得用文件名、目录名或默认值伪造具体场景和价签结论。
"""

from __future__ import annotations

from typing import Any, Callable

from src.modules.fmcg.cascade.manifest import CAP_SCENE

SCENES = (
    "shelf",        # 货架
    "freezer",      # 冰柜
    "cold_case",    # 冷风柜
    "floor_pile",   # 地堆
    "stack_box",    # 堆箱
    "small_shelf",  # 小货架
    "unknown",
)
PRICE_TAG_STATES = ("present", "absent", "unknown")


class SceneAdapter:
    capability_id = CAP_SCENE

    def __init__(self, backend: Callable[[dict], dict] | None = None) -> None:
        self._backend = backend

    def classify(self, image_ref: dict[str, Any]) -> dict[str, Any]:
        # 无后端：诚实 unknown（不得从 filename/dirname 推断）
        if self._backend is None:
            return {"scene": "unknown", "price_tag": "unknown",
                    "source": "no_model"}
        try:
            raw = self._backend(image_ref) or {}
        except Exception:
            return {"scene": "unknown", "price_tag": "unknown",
                    "source": "backend_error"}
        scene = raw.get("scene")
        tag = raw.get("price_tag")
        return {
            "scene": scene if scene in SCENES else "unknown",
            "price_tag": tag if tag in PRICE_TAG_STATES else "unknown",
            "source": "model",
        }
