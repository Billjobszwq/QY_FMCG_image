"""SKU 裁决（双模式）。固化：检索只召回，裁决=硬过滤+VLM 终审（不取 embedding top1）。

模式 B（prior_name 给定）：校验/纠错种子名。一致=validated；给另一 canonical=corrected(转复核)；无法确认=unconfirmed(保留+复核)。
模式 A（无 prior）：discovered；低置信/unknown/conflict 转复核。任何路径都不回写原始数据。"""
from __future__ import annotations

import io
import re

from PIL import Image

from ..catalog import naming
from ..common import omlx

SUGARS = naming.SUGARS
_VOL = re.compile(r"(\d{3,4})\s*(?:ml|ML|毫升)")
PICK_PROMPT = (
    "这是货架上一个饮料瓶的裁剪。候选SKU：{opts}。"
    "请读取标签，选最匹配的候选；无匹配选 unknown；多个冲突选 conflict。"
    '仅输出JSON：{{"brand","product","flavor","sugar","volume_ml","pick"}}，pick 必须是候选之一或 unknown/conflict。'
)


def _enc(img, max_side=640):
    w, h = img.size
    s = min(1.0, max_side / max(w, h))
    if s < 1.0:
        img = img.resize((int(w * s), int(h * s)))
    if img.mode != "RGB":
        img = img.convert("RGB")
    b = io.BytesIO()
    img.save(b, "JPEG", quality=85)
    return b.getvalue()


def _ocr_attrs(ocr):
    m = _VOL.search(ocr or "")
    return {"volume_ml": int(m.group(1)) if m else None, "sugar": next((s for s in SUGARS if s in (ocr or "")), None)}


def _hard_filter(hits, attrs, reg):
    out = []
    for cid, _sc in hits:
        c = reg.canonicals.get(cid)
        if not c:
            continue
        p = naming.parse(c.display)
        if attrs.get("volume_ml") and p["volume_ml"] != attrs["volume_ml"]:
            continue
        if attrs.get("sugar") and p["sugar"] != attrs["sugar"]:
            continue
        out.append(cid)
    return out


def _vlm_pick(jb, option_ids, reg, prior_name):
    opts = [reg.canonicals[i].display for i in option_ids] + ["unknown", "conflict"]
    prompt = PICK_PROMPT.format(opts=opts)
    if prior_name:
        prompt += f"\n参考系统给出的名称（仅供核对，可能错误）：{prior_name}"
    try:
        d = omlx.vlm_extract(jb, prompt, mime="image/jpeg")
    except Exception:
        d = {}
    pick = d.get("pick")
    if pick in ("unknown", "conflict", None):
        return {"pick": pick or "unknown", "fields": d}
    rid = reg.resolve(pick)
    resolved = rid[0] if rid else None
    # ISSUE-009：硬过滤边界 —— VLM 只能从候选集中选择；
    # 候选外结果一律转 conflict 强制人工复核，不得进入训练提案
    if resolved is None or resolved not in set(option_ids):
        return {"pick": "conflict", "out_of_candidates": True, "fields": d}
    return {"pick": resolved, "fields": d}


def decide(pick, prior_canon, option_ids, score, attrs, reg,
           thr_train=0.5, thr_review=0.25) -> dict:
    """ISSUE-009：纯函数决策规则（表驱动可测）。

    模式 B：仅 pick == prior_canon 才能 validated；进入 top3 只作证据不作验证。
    模式 A：置信度基于所选候选自身的检索分数 + 属性证据，不用 top1 分数套到其他候选。"""
    if prior_canon:  # 模式 B
        if pick == prior_canon:
            return {"decision": prior_canon, "method": "seeded_validated",
                    "needs_review": False, "confidence": "high"}
        if pick in reg.canonicals:
            return {"decision": pick, "method": "seeded_corrected",
                    "needs_review": True, "confidence": "medium"}
        return {"decision": prior_canon, "method": "seeded_unconfirmed",
                "needs_review": True, "confidence": "low"}
    # 模式 A
    decision, method = pick, "discovered"
    if decision == "conflict":
        return {"decision": decision, "method": method,
                "needs_review": True, "confidence": "low"}
    has_attr = bool(attrs.get("sugar") or attrs.get("volume_ml"))
    in_cand = decision in set(option_ids)
    high = score >= thr_train and decision in reg.canonicals and has_attr and in_cand
    medium = score >= thr_review
    conf = "high" if high else ("medium" if medium else "low")
    needs_review = (decision not in reg.canonicals) or (conf != "high") or (not has_attr)
    return {"decision": decision, "method": method,
            "needs_review": bool(needs_review), "confidence": conf}


def assign(crop_img, store, ids, vec, reg, prior_name=None, topk=10, thr_train=0.5, thr_review=0.25):
    jb = _enc(crop_img)
    try:
        ocr = omlx.ocr_text(jb, mime="image/jpeg")
    except Exception:
        ocr = ""
    attrs = _ocr_attrs(ocr)
    qtext = (ocr + " " + (prior_name or "")).strip() or "beverage bottle"
    try:
        qv = omlx.embed([qtext])[0]
        hits = store.search(qv, ids, vec, topk=topk)
    except Exception:
        hits = []
    cand = _hard_filter(hits, attrs, reg)
    option_ids = cand if cand else [h[0] for h in hits]
    vlm = _vlm_pick(jb, option_ids, reg, prior_name)
    pick, fields = vlm["pick"], vlm["fields"]
    prior_canon = reg.resolve(prior_name)[0] if prior_name else None
    # ISSUE-009：置信度使用所选候选自身的检索分数，不再用 top1 分数评估另一候选
    hit_map = {cid: sc for cid, sc in hits}
    score = float(hit_map.get(pick, 0.0)) if pick in hit_map else (float(hits[0][1]) if hits else 0.0)

    d = decide(pick, prior_canon, option_ids, score, attrs, reg, thr_train, thr_review)
    decision, method, needs_review, conf = d["decision"], d["method"], d["needs_review"], d["confidence"]

    return {
        "decision": decision, "prior_canon": prior_canon,
        "agree": (pick == prior_canon) if prior_canon else None,
        "method": method, "confidence": conf, "needs_review": bool(needs_review), "score": score,
        "evidence": {"ocr": (ocr or "")[:200], "attrs": attrs, "candidates": option_ids[:5],
                     "vlm_pick": pick, "fields": fields,
                     "out_of_candidates": bool(vlm.get("out_of_candidates"))},
    }
