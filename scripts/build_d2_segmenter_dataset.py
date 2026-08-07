"""N2 Task 7/12：D2 segmenter 数据集物化（YOLO-seg polygon）。

输入：sam_point_masks.jsonl 的 mask RLE（sam_verified_pseudo，几何门后）。
输出：data.yaml + images(symlink)/labels（0 cx... polygon 归一化）。
红线：SAM 伪 mask 只作学生模型训练数据（非 gold/eval 真值）；
目录存在拒绝覆盖。
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


def _rle_to_mask(rle: str, h: int, w: int):
    import numpy as np
    mask = np.zeros(h * w, dtype=bool)
    for seg in rle.split(","):
        if not seg:
            continue
        start, ln = seg.split(":")
        mask[int(start):int(start) + int(ln)] = True
    return mask.reshape((h, w), order="F")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".datasets_nextgen"
                                         / "d2_segmenter_smoke_v1"))
    ap.add_argument("--val-ratio", type=float, default=0.1)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        print(f"目录已存在，拒绝覆盖: {out}")
        return 1

    import cv2

    cm = json.loads(CM.read_text(encoding="utf-8"))
    by_photo: dict[str, list] = defaultdict(list)
    for line in SAM_OUT.open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("accepted") and d.get("mask_rle"):
            by_photo[d["photo_id"]].append(d)
    photos = sorted(by_photo)
    n_val = max(1, int(len(photos) * a.val_ratio))
    val_set = set(photos[len(photos) - n_val:])
    for split in ("train", "val"):
        (out / "images" / split).mkdir(parents=True)
        (out / "labels" / split).mkdir(parents=True)

    manifest = {"schema_version": "segmenter-snapshot.v2-yolo-seg",
                "label_source": "sam_verified_pseudo",
                "evidence_level": "smoke_pseudo_interim",
                "teacher": "sam2.1_hiera_small(frozen)",
                "photos": {}, "n_polygons": 0}
    n_polys = 0
    for pid in photos:
        info = cm[pid]
        sha = info["sha256"]
        w, h = int(info["width"]), int(info["height"])
        split = "val" if pid in val_set else "train"
        blob = ROOT / ".batch3_clean/blobs" / sha[:2] / sha
        img_dst = out / "images" / split / f"{pid}.jpg"
        if not img_dst.exists():
            img_dst.symlink_to(blob)
        lines = []
        for d in by_photo[pid]:
            mask = _rle_to_mask(d["mask_rle"], h, w).astype("uint8")
            conts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
            if not conts:
                continue
            c = max(conts, key=cv2.contourArea)
            if len(c) < 3:
                continue
            pts = " ".join(f"{x / w:.6f} {y / h:.6f}"
                           for x, y in c.reshape(-1, 2))
            lines.append(f"0 {pts}")
            n_polys += 1
        if not lines:
            img_dst.unlink(missing_ok=True)
            continue
        (out / "labels" / split / f"{pid}.txt").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")
        manifest["photos"][pid] = {"sha256": sha, "split": split,
                                   "polygons": len(lines)}
    n_train = sum(1 for p in manifest["photos"].values()
                  if p["split"] == "train")
    n_valp = sum(1 for p in manifest["photos"].values()
                 if p["split"] == "val")
    (out / "data.yaml").write_text(
        f"path: {out}\ntrain: images/train\nval: images/val\n"
        f"nc: 1\nnames: ['product']\n", encoding="utf-8")
    manifest["n_polygons"] = n_polys
    manifest["split_report"] = {"train": n_train, "val": n_valp}
    manifest["manifest_hash"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True,
                   ensure_ascii=False).encode()).hexdigest()
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps({"photos": len(manifest["photos"]),
                      "polygons": n_polys, "train": n_train,
                      "val": n_valp,
                      "hash": manifest["manifest_hash"][:16]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
