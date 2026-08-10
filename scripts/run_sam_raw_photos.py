"""SAM2 对独立 raw 照片（1106/1107/百事&可口）生成商品 mask 候选。

grid 点提示 + multimask；面积比 0.005-0.6；输出 jsonl（rle+bbox+score）。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "reports/nextgen_v2/sam_raw_photo_masks.jsonl"


def _rle(mask) -> str:
    flat = mask.flatten(order="F").astype(np.int8)
    idx = np.flatnonzero(np.diff(np.concatenate(([0], flat, [0]))))
    if len(idx) % 2 != 0:
        idx = idx[:-1]
    return ",".join(f"{idx[i]}:{idx[i+1]-idx[i]}"
                    for i in range(0, len(idx), 2))


def main() -> int:
    import torch
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    man = json.loads((ROOT / ".sam_checkpoints/manifest.json")
                     .read_text())
    e = next(x for x in man["entries"]
             if x["model"] == "sam2.1_hiera_small")
    sam = build_sam2("configs/sam2.1/sam2.1_hiera_s.yaml", e["file"],
                     device=torch.device("mps"))
    pred = SAM2ImagePredictor(sam)

    photos = (sorted((ROOT / "照片1106").glob("*.jpg")) +
              sorted((ROOT / "照片1107").glob("*.jpg")) +
              sorted((ROOT / "百事&可口").glob("*.jpg")))
    done = set()
    if OUT.exists():
        with OUT.open() as f:
            for line in f:
                done.add(json.loads(line)["photo"])
    fout = OUT.open("a", encoding="utf-8")
    t0 = time.time()
    n = 0
    for p in photos:
        if str(p) in done:
            continue
        img = cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB)
        if img is None:
            continue
        h, w = img.shape[:2]
        pred.set_image(img)
        ys, xs = np.meshgrid(np.linspace(0.15, 0.85, 4) * h,
                             np.linspace(0.15, 0.85, 4) * w,
                             indexing="ij")
        pts = np.stack([xs.ravel(), ys.ravel()], 1).astype(np.float32)
        labs = np.ones(len(pts), dtype=np.int32)
        masks, scores, _ = pred.predict(point_coords=pts,
                                        point_labels=labs,
                                        multimask_output=True)
        recs = []
        seen = set()
        for m, s in zip(masks, scores.ravel()):
            area = m.sum()
            ratio = area / (h * w)
            if not (0.005 <= ratio <= 0.6):
                continue
            key = (int(m.sum()),)
            if key in seen:
                continue
            seen.add(key)
            yy, xx = np.nonzero(m)
            recs.append({"bbox": [int(xx.min()), int(yy.min()),
                                  int(xx.max()) + 1, int(yy.max()) + 1],
                         "area_ratio": round(float(ratio), 4),
                         "score": round(float(s), 3),
                         "rle": _rle(m)})
        fout.write(json.dumps({"photo": str(p), "h": h, "w": w,
                               "masks": recs[:12]}, ensure_ascii=False)
                   + "\n")
        n += 1
        if n % 100 == 0:
            fout.flush()
            print(f"photos={n} rate={n/(time.time()-t0):.1f}/s",
                  flush=True)
    fout.close()
    print("done photos:", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
