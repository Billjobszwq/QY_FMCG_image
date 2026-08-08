"""用户提供切分照片（cropped_images）→ classifier 训练集。

映射见 reports/nextgen_v2/cropped_sku_mapping.json：
mapped→registry canonical id；new→CROP-NEW-xx 独立类（待人工裁决）。
图像级 90/10 split（seed 固定）；symlink 零复制；目录存在拒绝。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MAPPING = ROOT / "reports/nextgen_v2/cropped_sku_mapping.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".datasets_nextgen"
                                         / "d3_cropped_classifier_v1"))
    ap.add_argument("--val-ratio", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        print(f"目录已存在，拒绝覆盖: {out}")
        return 1

    mp = json.loads(MAPPING.read_text(encoding="utf-8"))
    rng = random.Random(a.seed)
    manifest = {"schema_version": "classifier-snapshot.v2-cropped",
                "label_source": "user_provided_cropped",
                "evidence_level": "user_labeled（文件名即标签，映射规则可复核）",
                "classes": {}, "n_images": 0, "split_report": {}}
    for d, e in mp["entries"].items():
        src = ROOT / "cropped_images" / d
        files = sorted(p for p in src.iterdir() if p.suffix.lower()
                       in (".jpg", ".jpeg", ".png"))
        rng.shuffle(files)
        n_val = max(1, int(len(files) * a.val_ratio)) if len(files) > 3 else 0
        val_set = set(files[len(files) - n_val:])
        cls_dir_tr = out / "train" / e["class_id"]
        cls_dir_va = out / "val" / e["class_id"]
        cls_dir_tr.mkdir(parents=True, exist_ok=True)
        cls_dir_va.mkdir(parents=True, exist_ok=True)
        ntr = nva = 0
        for f in files:
            dst = (cls_dir_va if f in val_set else cls_dir_tr) / f.name
            if not dst.exists():
                dst.symlink_to(f)
            if f in val_set:
                nva += 1
            else:
                ntr += 1
        manifest["classes"][e["class_id"]] = {
            "display": e["display"], "kind": e["kind"],
            "registry_name": e["registry_name"],
            "train": ntr, "val": nva}
        manifest["n_images"] += len(files)
        manifest["split_report"]["train"] = \
            manifest["split_report"].get("train", 0) + ntr
        manifest["split_report"]["val"] = \
            manifest["split_report"].get("val", 0) + nva
    manifest["n_classes"] = len(manifest["classes"])
    manifest["manifest_hash"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True,
                   ensure_ascii=False).encode()).hexdigest()
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps({"classes": manifest["n_classes"],
                      "images": manifest["n_images"],
                      "split": manifest["split_report"],
                      "hash": manifest["manifest_hash"][:16]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
