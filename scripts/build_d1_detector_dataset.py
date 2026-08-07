"""N2 Task 7/12：D1 detector 数据集物化（YOLO 格式，SAM tight box）。

输入：reports/nextgen_v2/sam_point_masks.jsonl（accepted，
label_source=sam_verified_pseudo）+ .batch3_clean（blobs/w/h）。
输出：data.yaml + images(symlink)/labels + manifest（原子发布，
目录存在拒绝）。split：photo 级确定性 90/10（smoke 口径）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SAM_OUT = ROOT / "reports/nextgen_v2/sam_point_masks.jsonl"
CM = ROOT / ".batch3_clean/clean_manifest.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".datasets_nextgen"
                                         / "d1_detector_smoke_v1"))
    ap.add_argument("--val-ratio", type=float, default=0.1)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        print(f"目录已存在，拒绝覆盖: {out}")
        return 1

    cm = json.loads(CM.read_text(encoding="utf-8"))
    by_photo: dict[str, list] = defaultdict(list)
    for line in SAM_OUT.open(encoding="utf-8"):
        d = json.loads(line)
        if d.get("accepted"):
            by_photo[d["photo_id"]].append(d)
    photos = sorted(by_photo)
    n_val = max(1, int(len(photos) * a.val_ratio))
    val_set = set(photos[len(photos) - n_val:])

    for split in ("train", "val"):
        (out / "images" / split).mkdir(parents=True)
        (out / "labels" / split).mkdir(parents=True)

    manifest = {"schema_version": "detector-snapshot.v2-yolo",
                "label_source": "sam_verified_pseudo",
                "evidence_level": "smoke_pseudo_interim",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "photos": {}, "n_regions": 0}
    n_regions = 0
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
            x1, y1, x2, y2 = d["tight_box"]
            cx = ((x1 + x2) / 2) / w
            cy = ((y1 + y2) / 2) / h
            bw = (x2 - x1) / w
            bh = (y2 - y1) / h
            if not (0 < bw <= 1 and 0 < bh <= 1):
                continue
            lines.append(f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
            n_regions += 1
        if not lines:
            img_dst.unlink(missing_ok=True)
            continue
        (out / "labels" / split / f"{pid}.txt").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")
        manifest["photos"][pid] = {"sha256": sha, "split": split,
                                   "regions": len(lines)}
    n_train = sum(1 for p in manifest["photos"].values()
                  if p["split"] == "train")
    n_valp = sum(1 for p in manifest["photos"].values()
                 if p["split"] == "val")
    (out / "data.yaml").write_text(
        f"path: {out}\ntrain: images/train\nval: images/val\n"
        f"nc: 1\nnames: ['product']\n", encoding="utf-8")
    manifest["n_regions"] = n_regions
    manifest["split_report"] = {"train": n_train, "val": n_valp}
    manifest["manifest_hash"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True,
                   ensure_ascii=False).encode()).hexdigest()
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps({"photos": len(manifest["photos"]),
                      "regions": n_regions,
                      "train": n_train, "val": n_valp,
                      "hash": manifest["manifest_hash"][:16]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
