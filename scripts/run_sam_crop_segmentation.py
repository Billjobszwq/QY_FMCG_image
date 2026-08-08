"""用户切分照片全量 SAM 分割（断点续跑）。

单商品切图：中心点正提示 + 90% box 提示 → mask RLE + tight box + score。
输出 jsonl（append-only，按文件路径续跑）。伪标签（SAM 自推理），
证据级 pseudo，非 human gold。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "reports/nextgen_v2/sam_crop_masks.jsonl"


def _rle_encode(mask) -> str:
    import numpy as np
    flat = mask.flatten(order="F").astype(np.int8)
    idx = np.flatnonzero(np.diff(np.concatenate(([0], flat, [0]))))
    if len(idx) % 2 != 0:
        idx = idx[:-1]
    return ",".join(f"{idx[i]}:{idx[i+1]-idx[i]}"
                    for i in range(0, len(idx), 2))


def main() -> int:
    import cv2
    import numpy as np
    import torch
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    man = json.loads((ROOT / ".sam_checkpoints/manifest.json")
                     .read_text(encoding="utf-8"))
    e = next(x for x in man["entries"]
             if x["model"] == "sam2.1_hiera_small")
    sam = build_sam2("configs/sam2.1/sam2.1_hiera_s.yaml", e["file"],
                     device=torch.device("mps"))
    pred = SAM2ImagePredictor(sam)

    done: set = set()
    if OUT.exists():
        with OUT.open() as f:
            for line in f:
                try:
                    done.add(json.loads(line)["path"])
                except Exception:
                    continue
    files = sorted(str(p) for p in (ROOT / "cropped_images").rglob("*.jpg"))
    todo = [f for f in files if f not in done]
    print(f"total={len(files)} done={len(done)} todo={len(todo)}", flush=True)

    fout = OUT.open("a", encoding="utf-8")
    t0 = time.time()
    n = 0
    for f in todo:
        img = cv2.cvtColor(cv2.imread(f), cv2.COLOR_BGR2RGB)
        if img is None:
            continue
        h, w = img.shape[:2]
        pred.set_image(img)
        pts = np.array([[w / 2, h / 2]], dtype=np.float32)
        labs = np.array([1], dtype=np.int32)
        box = np.array([w * 0.05, h * 0.05, w * 0.95, h * 0.95],
                       dtype=np.float32)
        masks, scores, _ = pred.predict(point_coords=pts,
                                        point_labels=labs, box=box,
                                        multimask_output=False)
        m = masks[0] > 0
        ys, xs = np.nonzero(m)
        rec = {"path": f, "width": w, "height": h,
               "score": float(scores[0]), "area_px": int(m.sum())}
        if len(xs):
            rec["tight_box"] = [int(xs.min()), int(ys.min()),
                                int(xs.max()) + 1, int(ys.max()) + 1]
            rec["mask_rle"] = _rle_encode(m)
        fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
        n += 1
        if n % 500 == 0:
            fout.flush()
            el = time.time() - t0
            print(f"seg={n} rate={n/el:.1f}/s", flush=True)
    fout.close()
    print(json.dumps({"segmented": n,
                      "elapsed_min": round((time.time() - t0) / 60, 1)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
