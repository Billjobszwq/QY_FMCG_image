"""N2 Task 7/12：D3 classifier crop 数据集物化（SAM tight box）。

输出 ImageFolder 结构：<out>/<split>/<sku_id>/*.jpg（224 保比例 pad）。
只用 mapped canonical sku_id；unknown/new_packaging 进独立 unknown 桶。
派生 crop 继承原图 split（与 D1 同一 photo 划分，防泄漏）。
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".datasets_nextgen"
                                         / "d3_classifier_smoke_v1"))
    ap.add_argument("--val-ratio", type=float, default=0.1)
    ap.add_argument("--size", type=int, default=224)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        print(f"目录已存在，拒绝覆盖: {out}")
        return 1

    from PIL import Image

    cm = json.loads(CM.read_text(encoding="utf-8"))
    by_photo: dict[str, list] = defaultdict(list)
    for line in SAM_OUT.open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("accepted") and d.get("sku_id"):
            by_photo[d["photo_id"]].append(d)
    photos = sorted(by_photo)
    n_val = max(1, int(len(photos) * a.val_ratio))
    val_set = set(photos[len(photos) - n_val:])

    manifest = {"schema_version": "classifier-snapshot.v2-crops",
                "label_source": "sam_verified_pseudo",
                "evidence_level": "smoke_pseudo_interim",
                "classes": {}, "n_crops": 0, "split_report": {}}
    img_cache: dict[str, Image.Image] = {}
    n = 0
    for pid in photos:
        info = cm[pid]
        sha = info["sha256"]
        split = "val" if pid in val_set else "train"
        blob = ROOT / ".batch3_clean/blobs" / sha[:2] / sha
        if sha not in img_cache:
            img_cache = {sha: Image.open(blob).convert("RGB")}  # 单图缓存
        img = img_cache[sha]
        for j, d in enumerate(by_photo[pid]):
            x1, y1, x2, y2 = [int(v) for v in d["tight_box"]]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(img.width, x2), min(img.height, y2)
            if x2 - x1 < 8 or y2 - y1 < 8:
                continue
            crop = img.crop((x1, y1, x2, y2))
            crop.thumbnail((a.size, a.size))
            canvas = Image.new("RGB", (a.size, a.size), (114, 114, 114))
            canvas.paste(crop, ((a.size - crop.width) // 2,
                                (a.size - crop.height) // 2))
            cls_dir = out / split / d["sku_id"]
            cls_dir.mkdir(parents=True, exist_ok=True)
            canvas.save(cls_dir / f"{pid}_{j}.jpg", quality=90)
            manifest["classes"][d["sku_id"]] = \
                manifest["classes"].get(d["sku_id"], 0) + 1
            n += 1
        manifest["split_report"][split] = \
            manifest["split_report"].get(split, 0) + 1
    manifest["n_crops"] = n
    manifest["n_classes"] = len(manifest["classes"])
    manifest["manifest_hash"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True,
                   ensure_ascii=False).encode()).hexdigest()
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps({"crops": n, "classes": len(manifest["classes"]),
                      "hash": manifest["manifest_hash"][:16]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
