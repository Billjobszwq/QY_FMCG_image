"""VLM-006：SAM mask/crop 精修适配器（S2）。

红线：
- SAM 只输出 mask/crop/证据，不输出 SKU 决策；
- 输出三种引用：原粗框 crop、mask crop、带 10%–20% 上下文 crop；
- 任何 mask 失败保留原框证据并返回 needs_review，不伪造 mask。
"""

from __future__ import annotations

from typing import Any, Callable

from src.modules.fmcg.cascade.manifest import CAP_SAM

CONTEXT_RATIO_DEFAULT = 0.15  # 上下文外扩比例（10%–20% 区间内）


class SamRefinerAdapter:
    capability_id = CAP_SAM

    def __init__(self, backend: Callable[[dict, list], dict] | None = None) -> None:
        self._backend = backend

    def refine(
        self,
        image_ref: dict[str, Any],
        box: list[float],
        *,
        context_ratio: float = CONTEXT_RATIO_DEFAULT,
    ) -> dict[str, Any]:
        if not (0.10 <= context_ratio <= 0.20):
            from src.modules.fmcg.adapters import CapabilityAdapterError

            raise CapabilityAdapterError(
                f"context_ratio 必须在 10%–20%: {context_ratio}"
            )
        coarse = [float(v) for v in box]
        w_img = float(image_ref["image_width"])
        h_img = float(image_ref["image_height"])
        bw = coarse[2] - coarse[0]
        bh = coarse[3] - coarse[1]
        context = [
            max(0.0, coarse[0] - bw * context_ratio),
            max(0.0, coarse[1] - bh * context_ratio),
            min(w_img, coarse[2] + bw * context_ratio),
            min(h_img, coarse[3] + bh * context_ratio),
        ]
        crops: dict[str, Any] = {"coarse": coarse, "mask": None, "context": context}
        evidence = {"sha256": image_ref.get("sha256"), "source_box": coarse}

        if self._backend is None:
            return {"crops": crops, "needs_review": True,
                    "failure_reason": "sam_backend_unavailable",
                    "evidence": evidence}
        try:
            raw = self._backend(image_ref, coarse) or {}
        except Exception as e:
            # mask 失败：保留原框证据，不伪造 mask
            return {"crops": crops, "needs_review": True,
                    "failure_reason": str(e), "evidence": evidence}
        mask_box = raw.get("mask_box")
        if mask_box:
            crops["mask"] = [float(v) for v in mask_box]
        needs_review = crops["mask"] is None
        return {
            "crops": crops,
            "needs_review": needs_review,
            "failure_reason": None if not needs_review else "mask_empty",
            "evidence": evidence,
        }
