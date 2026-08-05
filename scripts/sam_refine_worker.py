"""SAM 精修隔离 Worker（.venv_sam 内执行，主环境经子进程调用）。

口径：数据集粗框作为 box prompt + 中心点正提示 → SAM 2.1 输出单 mask
紧框；不落 mask PNG（证据由主环境 JSON 记录 prompt/紧框/得分/决策）。
fail-closed：MPS 不可用或设置 PYTORCH_ENABLE_MPS_FALLBACK 一律拒绝。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path


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
    if not ckpt.exists():
        return {"ok": False, "error": f"checkpoint 不存在: {ckpt}"}
    device = torch.device("mps")
    t0 = time.time()
    sam = build_sam2(request["config"], str(ckpt), device=device)
    predictor = SAM2ImagePredictor(sam)
    load_sec = time.time() - t0

    results = []
    for img_req in request["images"]:
        blob = Path(img_req["image_path"])
        img_bgr = cv2.imread(str(blob), cv2.IMREAD_COLOR)
        if img_bgr is None:
            return {"ok": False, "error": f"图片解码失败: {blob}"}
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

        t_enc = time.time()
        predictor.set_image(img_rgb)          # image embedding：每图一次
        enc_sec = time.time() - t_enc

        inst_out = []
        for inst in img_req["instances"]:
            pts = np.array([inst["positive"]], dtype=np.float32)
            labels = np.array([1], dtype=np.int32)
            box = np.array(inst["coarse_box"], dtype=np.float32)
            masks, scores, _ = predictor.predict(
                point_coords=pts, point_labels=labels,
                box=box, multimask_output=False)
            m = masks[0] > 0
            ys, xs = np.nonzero(m)
            bbox = ([int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)]
                    if len(xs) else None)
            inst_out.append({
                "instance_id": inst["instance_id"],
                "sam_box": bbox,
                "sam_score": float(scores[0]),
                "mask_area_px": int(len(xs)),
            })
        results.append({
            "image_id": img_req["image_id"],
            "encoder_sec": round(enc_sec, 4),
            "instances": inst_out,
        })
    return {"ok": True,
            "env": {"torch": torch.__version__, "device": str(device),
                    "model": request["model"], "load_sec": round(load_sec, 2),
                    "checkpoint_sha256": request.get("checkpoint_sha256", "")},
            "results": results}


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
