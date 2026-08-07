"""N2 Task 6 隔离 Worker（.venv_sam 内）：点提示 SAM multimask 推理。

prompt = 正点 + ROI 内其他 SKU 负点 + 局部 box；输出全部候选 mask
（RLE）与分数；几何门由主环境执行。fail-closed：MPS 不可用拒绝。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def _rle_encode(mask) -> str:
    import numpy as np
    flat = mask.flatten(order="F")
    idx = np.flatnonzero(np.diff(np.concatenate(([0], flat.view(int), [0]))))
    return ",".join(f"{idx[i]}:{idx[i+1]-idx[i]}" for i in range(0, len(idx), 2))


def _run(request: dict) -> dict:
    import numpy as np
    import torch

    if __import__("os").environ.get("PYTORCH_ENABLE_MPS_FALLBACK"):
        return {"ok": False, "error": "PYTORCH_ENABLE_MPS_FALLBACK 被禁止"}
    if not (torch.backends.mps.is_built() and torch.backends.mps.is_available()):
        return {"ok": False, "error": "MPS 不可用，禁止 CPU fallback"}

    import cv2
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    ckpt = Path(request["checkpoint"])
    device = torch.device("mps")
    t0 = time.time()
    sam = build_sam2(request["config"], str(ckpt), device=device)
    predictor = SAM2ImagePredictor(sam)
    load_sec = time.time() - t0

    out_images = []
    for img_req in request["images"]:
        blob = Path(img_req["image_path"])
        img_bgr = cv2.imread(str(blob), cv2.IMREAD_COLOR)
        if img_bgr is None:
            out_images.append({"image_id": img_req["image_id"],
                               "error": "decode_failed"})
            continue
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        predictor.set_image(img_rgb)
        inst_out = []
        for inst in img_req["instances"]:
            pts = [inst["positive"]] + [list(p) for p in inst.get("negatives", [])]
            labels = [1] + [0] * len(inst.get("negatives", []))
            kw = {"point_coords": np.array(pts, dtype=np.float32),
                  "point_labels": np.array(labels, dtype=np.int32),
                  "multimask_output": True}
            if inst.get("roi_box"):
                kw["box"] = np.array(inst["roi_box"], dtype=np.float32)
            masks, scores, _ = predictor.predict(**kw)
            cands = []
            for m, s in zip(masks, scores):
                mb = m > 0
                if not mb.any():
                    continue
                cands.append({"rle": _rle_encode(mb),
                              "score": float(s),
                              "area_px": int(mb.sum())})
            inst_out.append({"instance_id": inst["instance_id"],
                             "candidates": cands})
        out_images.append({"image_id": img_req["image_id"],
                           "instances": inst_out})
    return {"ok": True,
            "env": {"torch": torch.__version__, "device": str(device),
                    "model": request["model"],
                    "load_sec": round(load_sec, 2),
                    "checkpoint_sha256": request.get("checkpoint_sha256", "")},
            "results": out_images}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", required=True)
    a = ap.parse_args()
    request = json.loads(Path(a.request).read_text(encoding="utf-8"))
    resp = _run(request)
    print(json.dumps(resp, ensure_ascii=False))
    sys.exit(0 if resp.get("ok") else 1)


if __name__ == "__main__":
    main()
