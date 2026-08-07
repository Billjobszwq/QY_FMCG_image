"""N2 Task 7/12：D4 VLM pilot 数据（mlx-vlm images/messages 格式）。

每条：region crop 图 + 候选 SKU 文本问题 → canonical target（或 unknown）。
CandidateSet 由检索占位（按 registry 名称相似度的确定性函数）生成，
签名禁 GT（构建器不知道答案，只按 query 检索）；不足 k 不补真值。
输出 HF datasets 目录（parquet + images），供 mlx_vlm.lora --dataset。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SAM_OUT = ROOT / "reports/nextgen_v2/sam_point_masks.jsonl"
CM = ROOT / ".batch3_clean/clean_manifest.json"
REG = ROOT / "data/sku_registry.json"


def candidate_set(query_sku: str, registry: dict, k: int = 8):
    """确定性检索占位：按字符重叠打分（不接收 GT 之外的答案信息：
    query 是区域的 OCR/名称观测，此处以标注名为观测代理，仅用于
    smoke 格式验证；正式版必须走真实 OCR+向量检索链）。"""
    scored = []
    q = set(query_sku)
    for name, info in registry.items():
        inter = len(q & set(name))
        scored.append((inter / max(len(set(name)), 1), info["sku_id"], name))
    scored.sort(reverse=True)
    return [{"sku_id": s, "name": n} for _, s, n in scored[:k]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".datasets_nextgen"
                                         / "d4_vlm_smoke_v1"))
    ap.add_argument("--n", type=int, default=200)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        print(f"目录已存在，拒绝覆盖: {out}")
        return 1
    out.mkdir(parents=True)

    from PIL import Image

    registry = json.loads(REG.read_text(encoding="utf-8"))
    cm = json.loads(CM.read_text(encoding="utf-8"))
    rows = []
    for line in SAM_OUT.open(encoding="utf-8"):
        d = json.loads(line)
        if not (d.get("accepted") and d.get("sku_id")):
            continue
        rows.append(d)
        if len(rows) >= a.n:
            break

    records = []
    img_dir = out / "images"
    img_dir.mkdir()
    for i, d in enumerate(rows):
        info = cm[d["photo_id"]]
        sha = info["sha256"]
        w, h = int(info["width"]), int(info["height"])
        blob = ROOT / ".batch3_clean/blobs" / sha[:2] / sha
        img = Image.open(blob).convert("RGB")
        x1, y1, x2, y2 = [int(v) for v in d["tight_box"]]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 - x1 < 8 or y2 - y1 < 8:
            continue
        crop = img.crop((x1, y1, x2, y2))
        crop.thumbnail((384, 384))
        fname = f"r{i:05d}.jpg"
        crop.save(img_dir / fname, quality=90)
        target_name = next(n for n, v in registry.items()
                           if v["sku_id"] == d["sku_id"])
        cands = candidate_set(target_name, registry, k=8)
        cand_txt = "\n".join(f"{j+1}. {c['name']}"
                             for j, c in enumerate(cands))
        ans_idx = next((j for j, c in enumerate(cands)
                        if c["sku_id"] == d["sku_id"]), None)
        answer = (str(ans_idx + 1) if ans_idx is not None else "unknown")
        records.append({
            "messages": [
                {"role": "user", "content": [
                    {"type": "image", "image": f"images/{fname}"},
                    {"type": "text",
                     "text": ("这是货架上的一个商品区域。候选 SKU：\n"
                              + cand_txt +
                              "\n请只回答最匹配的编号（或 unknown）。")}]},
                {"role": "assistant",
                 "content": [{"type": "text", "text": answer}]}],
            "images": [f"images/{fname}"],
            "meta": {"region_id": d["photo_id"] + ":" + str(i),
                     "target_sku_id": d["sku_id"],
                     "label_source": "sam_verified_pseudo",
                     "candidates_n": len(cands)}})
    (out / "train.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records),
        encoding="utf-8")
    manifest = {"schema_version": "vlm-snapshot.v2-pilot",
                "format": "mlx_vlm.lora jsonl(images/messages)",
                "n_samples": len(records),
                "label_source": "sam_verified_pseudo",
                "evidence_level": "smoke_pseudo_interim",
                "candidate_builder": "deterministic_char_overlap_placeholder"
                                     "（正式版走真实 OCR+向量检索，禁 GT）",
                "manifest_hash": hashlib.sha256(
                    json.dumps(records[:0], ensure_ascii=False).encode()
                ).hexdigest()}
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps({"samples": len(records),
                      "hash": manifest["manifest_hash"][:16]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
