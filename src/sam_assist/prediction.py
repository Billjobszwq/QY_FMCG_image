"""SAM 结果 → Label Studio prediction 纯格式化（手册§一.6）。

本模块只产生 prediction 结构（score/model_version/result），从不产生
annotation；最终 annotation 由人工在 LS 中确认并经第二人审核后生成。"""
from __future__ import annotations

import uuid


def to_ls_prediction(width: int, height: int, visible_tight_box: tuple,
                     model_version: str, score: float) -> dict:
    if visible_tight_box is None:
        raise ValueError("缺少 visible_tight_box，manual_required 实例不得生成 prediction 框")
    if not (0.0 <= float(score) <= 1.0):
        raise ValueError(f"score 越界: {score}")
    x1, y1, x2, y2 = visible_tight_box
    rid = f"sam_{uuid.uuid4().hex[:12]}"
    value = {
        "x": x1 / width * 100,
        "y": y1 / height * 100,
        "width": (x2 - x1) / width * 100,
        "height": (y2 - y1) / height * 100,
        "rotation": 0,
        "rectanglelabels": ["product"],
    }
    return {
        "score": float(score),
        "model_version": model_version,
        "result": [{
            "id": rid,
            "from_name": "box",
            "to_name": "image",
            "type": "rectanglelabels",
            "value": value,
        }],
        "metadata": {
            "source": "sam_prediction",
            "is_final_annotation": False,
        },
    }
