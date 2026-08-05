"""U3-5：qpol_v2 质量策略（十一维 + 全字段证据 + waiting_human fail-closed）。

口径（手册 §5/U4 指令）：
- 覆盖 11 维：斜拍、反光、翻拍、屏摄、摩尔纹、模糊、商品大头照误导、
  裁切、遮挡、场景、价签。
- 每条结论保留：原图 SHA、策略版本、各维分数、阈值、自动结论、
  人工结论、模型版本、证据（追加式不可变 quality_decision_v1）。
- 当前尚无训练好的质量模型：model_version=heuristic_v1，只有
  blur/reflection 两个启发式维度；其余维度自动结论一律
  waiting_human（禁止伪造通过）；整体判定：任一 fail→fail；
  全部维度高置信 pass→pass；否则 waiting_human。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

POLICY_VERSION = "qpol_v2"
MODEL_VERSION = "heuristic_v1"

DIMENSIONS: list[dict[str, Any]] = [
    {"name": "tilt", "label": "斜拍", "heuristic": False},
    {"name": "reflection", "label": "反光", "heuristic": True},
    {"name": "rephoto", "label": "翻拍", "heuristic": False},
    {"name": "screen_capture", "label": "屏摄", "heuristic": False},
    {"name": "moire", "label": "摩尔纹", "heuristic": False},
    {"name": "blur", "label": "模糊", "heuristic": True},
    {"name": "product_closeup_mislead", "label": "商品大头照误导",
     "heuristic": False},
    {"name": "cropped", "label": "裁切", "heuristic": False},
    {"name": "occlusion", "label": "遮挡", "heuristic": False},
    {"name": "scene", "label": "场景", "heuristic": False},
    {"name": "price_tag", "label": "价签", "heuristic": False},
]

# 分数 > 阈值 → 该维度判 fail（分数越高问题越严重）
THRESHOLDS: dict[str, float] = {
    "blur": 0.5,
    "reflection": 0.4,
}


def _blur_score(gray) -> float:
    """Laplacian 方差越低越模糊；归一为 [0,1] 的模糊分。"""
    import numpy as np
    from scipy.ndimage import convolve

    kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float64)
    lap = convolve(gray.astype(np.float64), kernel)
    var = float(lap.var())
    return max(0.0, 1.0 - var / 120.0)


def _reflection_score(gray) -> float:
    """近白像素占比作为反光/过曝信号。"""
    import numpy as np

    return float((gray > 250).mean())


def evaluate_image(store, *, sha256: str, path: Path) -> dict[str, Any]:
    """对一张图跑 qpol_v2，落库不可变结论并返回全字段视图。"""
    import numpy as np
    from PIL import Image

    gray = np.asarray(Image.open(path).convert("L"), dtype=np.float64)
    signals = {"blur": _blur_score(gray),
               "reflection": _reflection_score(gray)}

    score: dict[str, float] = {}
    threshold: dict[str, float] = {}
    evidence: dict[str, Any] = {}
    for dim in DIMENSIONS:
        name = dim["name"]
        if dim["heuristic"]:
            s = signals[name]
            th = THRESHOLDS[name]
            score[name] = round(s, 6)
            threshold[name] = th
            if s > th:
                auto, conf = "fail", "high"
            elif s < th * 0.5:
                auto, conf = "pass", "high"
            else:
                auto, conf = "waiting_human", "low"
            evidence[name] = {
                "auto": auto, "confidence": conf,
                "score": round(s, 6), "threshold": th,
                "analyzer": "heuristic_v1",
                "label": dim["label"],
            }
        else:
            # 尚无启发式/模型：不得伪造通过，交人工
            score[name] = 0.0
            evidence[name] = {
                "auto": "waiting_human", "confidence": "low",
                "score": None, "threshold": None,
                "analyzer": "none", "label": dim["label"],
                "note": "qpol_v2 暂无该维度自动分析器，等待人工金标准",
            }

    autos = [e["auto"] for e in evidence.values()]
    if any(a == "fail" for a in autos):
        overall = "fail"
    elif all(a == "pass" for a in autos):
        overall = "pass"
    else:
        overall = "waiting_human"

    rec = store.record_quality_decision(
        sha256=sha256, policy_version=POLICY_VERSION, score=score,
        threshold=threshold, auto_decision=overall, human_decision=None,
        model_version=MODEL_VERSION, evidence=evidence)
    return {
        "id": rec["id"],
        "sha256": sha256,
        "policy_version": POLICY_VERSION,
        "model_version": MODEL_VERSION,
        "score": score,
        "threshold": threshold,
        "auto_decision": overall,
        "human_decision": None,
        "evidence": evidence,
        "created_at": rec["created_at"],
        "note": ("人工结论未完成前，waiting_human 为唯一可信出口；"
                 "禁止把自动 heuristic 结论当作人工通过"),
    }
