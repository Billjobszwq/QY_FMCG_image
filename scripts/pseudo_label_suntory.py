"""SAM 自动 mask + classifier 伪标注 → 三得利场景 detector 训练数据。

SAM2 自动 mask（class-agnostic）→ crop → grouped-83 classifier 推理 →
conf≥0.6 记 (box, sku) YOLO label。证据级 sam_classifier_pseudo。
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

OUT = ROOT / ".datasets_nextgen/d1_pseudo_suntory"


def main() -> int:
    import torch
    import torchvision
    from torchvision import transforms
    from PIL import Image
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    man = json.loads((ROOT / ".sam_checkpoints/manifest.json").read_text())
    e = next(x for x in man["entries"]
             if x["model"] == "sam2.1_hiera_small")
    sam = build_sam2("configs/sam2.1/sam2.1_hiera_s.yaml", e["file"],
                     device=torch.device("mps"))
    pred = SAM2ImagePredictor(sam)

    ck = torch.load(ROOT / ".models/nextgen_classifier_grouped_v1/weights"
                    / "best.pt", map_location="cpu", weights_only=False)
    m83 = torchvision.models.resnet18(weights=None)
    m83.fc = torch.nn.Linear(m83.fc.in_features, 83)
    m83.load_state_dict(ck["model"])
    m83.eval()
    tf = transforms.Compose([
        transforms.Resize(256), transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize([.485, .456, .406], [.229, .224, .225])])

    photos = sorted((ROOT / "照片1106").glob("*.jpg")) + \
        sorted((ROOT / "照片1107").glob("*.jpg"))
    (OUT / "images" / "train").mkdir(parents=True, exist_ok=True)
    (OUT / "labels" / "train").mkdir(parents=True, exist_ok=True)
    total = 0
    t0 = time.time()
    for i, p in enumerate(photos):
        img = cv2.imread(str(p))
        if img is None:
            continue
        H, W = img.shape[:2]
        pred.set_image(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        ys, xs = np.meshgrid(np.linspace(0.12, 0.88, 4) * H,
                             np.linspace(0.12, 0.88, 4) * W,
                             indexing="ij")
        pts = np.stack([xs.ravel(), ys.ravel()], 1).astype(np.float32)
        labs = np.ones(len(pts), dtype=np.int32)
        masks, scores, _ = pred.predict(point_coords=pts,
                                        point_labels=labs,
                                        multimask_output=True)
        lines = []
        seen = set()
        for m, sc in zip(masks, scores.ravel()):
            area = m.sum()
            if not (0.004 <= area / (H * W) <= 0.5):
                continue
            yy, xx = np.nonzero(m)
            x, y = float(xx.min()), float(yy.min())
            w, h = float(xx.max() - xx.min() + 1), float(yy.max() - yy.min() + 1)
            key = (int(x), int(y), int(w), int(h))
            if key in seen:
                continue
            seen.add(key)
            crop = img[int(y):int(y + h), int(x):int(x + w)]
            if crop.size == 0:
                continue
            with torch.no_grad():
                o = torch.softmax(m83(tf(Image.fromarray(
                    cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))[None]), 1)[0]
            c, conf = int(o.argmax()), float(o.max())
            if conf < 0.6:
                continue
            cx, cy = (x + w / 2) / W, (y + h / 2) / H
            lines.append(f"{c} {cx:.6f} {cy:.6f} {w/W:.6f} {h/H:.6f}")
            total += 1
        if lines:
            stem = f"suntory_{i:05d}"
            cv2.imwrite(str(OUT / "images" / "train" / f"{stem}.jpg"), img)
            (OUT / "labels" / "train" / f"{stem}.txt").write_text(
                "\n".join(lines))
        if (i + 1) % 100 == 0:
            print(f"photos={i+1} boxes={total} "
                  f"rate={(i+1)/(time.time()-t0):.1f}/s", flush=True)
    print("done boxes:", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
