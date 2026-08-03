"""知识库构建编排：入库 + 去重 + VLM 结构化卡 + 促销图剔除 + 文本向量 + 检索自检。

运行：python -m src.catalog.build_kb
所有模型调用走本地 omlx；单图失败不中断整批，记入 flags。"""
from __future__ import annotations

import json
from pathlib import Path

from ..common import hashing, omlx
from ..common.config import get_settings
from .alias_registry import build_registry
from .ingest import JPG, collect, skeleton_record
from .store import LocalStore

ALIAS = Path(__file__).resolve().parents[2] / "data" / "sku_aliases.json"
CARD_PROMPT = (
    "读取瓶身标签信息，仅输出JSON：{\"brand\",\"product\",\"flavor\",\"sugar\",\"volume_ml\",\"other_text\"}。"
    "看不到的字段填 null，不要解释。"
)


def _representative(rec, paths):
    for i, r in enumerate(rec.refs):
        if r["ext"] in JPG:
            return paths[i]
    return paths[0] if paths else None


def main() -> dict:
    s = get_settings()
    ref = Path(s.reference_dir)
    store = LocalStore(Path(s.data_dir))
    kb_names = sorted(p.name for p in ref.iterdir() if p.is_dir())
    build_registry(kb_names, ALIAS)  # 校验别名表与 KB 一致（冲突会抛错）

    skus = []
    n_blobs = n_dedup = n_promo = 0
    for folder in sorted(p for p in ref.iterdir() if p.is_dir()):
        items = collect(folder)
        rec = skeleton_record(folder.name, items)
        paths = [p for (_e, _n, p) in items]
        for i, (ext, name, path) in enumerate(items):
            data = path.read_bytes()
            h = hashing.sha256_bytes(data)
            _, existed = store.put_blob(data, h)
            n_blobs += 1
            n_dedup += int(existed)
            rec.refs[i]["sha256"] = h
            if ext not in JPG:  # png 需判定是否促销合成图
                try:
                    ans = omlx.vlm_classify(
                        data,
                        "判断这张图：是单个产品干净/白底图，还是 多瓶/促销合成/带装饰背景图？",
                        ["single_plain", "multi_or_promo"],
                    )
                    promo = ("multi" in ans) or ("promo" in ans)
                except Exception as e:
                    promo = False
                    rec.flags.append(f"png_classify_err:{name}:{type(e).__name__}")
                rec.refs[i]["role"] = "promo_composite" if promo else "standard_single"
                if promo:
                    rec.refs[i]["excluded"] = True
                    n_promo += 1
        rep = _representative(rec, paths)
        card: dict = {}
        if rep is not None:
            rb = rep.read_bytes()
            try:
                card = omlx.vlm_extract(rb, CARD_PROMPT)
            except Exception as e:
                rec.flags.append(f"card_err:{type(e).__name__}")
            try:
                card["ocr"] = omlx.ocr_text(rb)
            except Exception as e:
                rec.flags.append(f"ocr_err:{type(e).__name__}")
        rec.card = card
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
            ]
            if x not in (None, "", "null")
        ]
        parts += [rec.attrs.get("flavor_core") or "", rec.display]
        rec.embedding_text = " ".join(p for p in parts if p)
        if not [r for r in rec.refs if not r["excluded"]]:
            rec.flags.append("no_clean_reference")
        skus.append(rec)

    texts = [r.embedding_text or r.display for r in skus]
    vecs = omlx.embed(texts)
    ids = [r.id for r in skus]
    store.save([r.to_dict() for r in skus], ids, vecs)

    summary = {
        "skus": len(skus),
        "reference_images": n_blobs,
        "blobs_deduped": n_dedup,
        "promo_excluded": n_promo,
        "no_clean_reference": [r.id for r in skus if "no_clean_reference" in r.flags],
        "embed_dim": len(vecs[0]) if vecs else 0,
        "data_dir": str(store.root),
    }
    print("KB_BUILD_SUMMARY", json.dumps(summary, ensure_ascii=False))

    ids2, mat = store.load_vectors()
    for q in ["茉莉乌龙 无糖 500ml", "拿铁 咖啡 480ml", "沁 桃 水 550ml", "维C 樱桃 饮料"]:
        qv = omlx.embed([q])[0]
        print("SEARCH", q, "->", store.search(qv, ids2, mat, topk=3))
    return summary


if __name__ == "__main__":
    main()
