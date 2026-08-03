"""单裁剪识别：OCR + VLM 结构化卡 → Qwen3 向量检索 KB → 取 top1 或判未知。

裁剪先压到 max_side 再编 JPEG，降低本地模型负载与载荷。mime 传 jpeg（omlx 亦按魔数自纠）。"""
from __future__ import annotations

import io

from PIL import Image

from ..catalog.store import LocalStore
from ..common import omlx

CARD_PROMPT = (
    "读取瓶身标签，仅输出JSON：{\"brand\",\"product\",\"flavor\",\"sugar\",\"volume_ml\",\"other_text\"}。"
    "看不到的字段填 null，不要解释。"
)


def _encode_jpeg(img: Image.Image, max_side: int = 768) -> bytes:
    w, h = img.size
    s = min(1.0, max_side / max(w, h))
    if s < 1.0:
        img = img.resize((int(w * s), int(h * s)))
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def recognize(crop_img: Image.Image, store: LocalStore, ids, vec, topk: int = 5, unknown_thr: float = 0.30) -> dict:
    jb = _encode_jpeg(crop_img)
    card: dict = {}
    try:
        card = omlx.vlm_extract(jb, CARD_PROMPT, mime="image/jpeg")
    except Exception:
        card = {}
    ocr = ""
    try:
        ocr = omlx.ocr_text(jb, mime="image/jpeg")
    except Exception:
        ocr = ""
    c = card or {}
    parts = [
        str(x)
        for x in [
            c.get("brand"),
            c.get("product"),
            c.get("flavor"),
            c.get("sugar"),
            (str(c.get("volume_ml")) + "ml") if c.get("volume_ml") else None,
            c.get("other_text"),
            ocr,
        ]
        if x not in (None, "", "null")
    ]
    qtext = " ".join(parts) or "beverage bottle"
    qv = omlx.embed([qtext])[0]
    hits = store.search(qv, ids, vec, topk=topk)
    top_id, top_score = (hits[0] if hits else (None, 0.0))
    decision = top_id if (top_id and top_score >= unknown_thr) else "unknown"
    return {"query_text": qtext, "card": card, "ocr": ocr[:200], "topk": hits, "decision": decision, "score": float(top_score)}
