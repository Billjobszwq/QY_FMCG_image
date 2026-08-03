"""难例 SKU 检测召回穿透测试（Gate 3）。

对包含困难 SKU（美橙600ml/拉罐330ml/芬达500ml 等）的真实货架照片，
用指定 YOLO 权重跑检测，计算每个困难 SKU 的**单独检测召回率**：
  recall = (GT 点被「同类」预测框覆盖数) / (该 SKU GT 点数)

用法：python -m src.eval.hardcase_recall --weight <yolo.pt> [--limit 250] [--conf 0.15]"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT

B2_MANIFEST = PROJECT_ROOT / ".eval" / "batch2" / "manifest.json"
BLOBS = PROJECT_ROOT / ".training_data" / "blobs"
REGISTRY = PROJECT_ROOT / "data" / "sku_registry.json"

# 困难 SKU（与 watchlist 对齐）
HARD_SKUS = ["美橙600ml", "拉罐330ml百事", "芬达橙500ml", "百事600ml", "1L美年达(橙味)"]


def select_photos(limit: int):
    """选出包含困难 SKU 的照片（含其 GT 标注）。"""
    manifest = json.loads(B2_MANIFEST.read_text(encoding="utf-8"))
    photos = manifest["photos"]
    sel = []
    for pid, p in photos.items():
        anns = p.get("annotations", [])
        hard = [a for a in anns if a.get("name") in HARD_SKUS]
        if hard and (p.get("image") or {}).get("sha256"):
            sel.append((pid, p))
        if len(sel) >= limit:
            break
    return sel


def run(weight: str, limit: int = 250, conf: float = 0.15):
    from ultralytics import YOLO
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    name_to_cls = {k: v["class_id"] for k, v in registry.items()}
    yolo = YOLO(weight)

    sel = select_photos(limit)
    print(f"[{Path(weight).name}] 测试照片: {len(sel)}")

    gt_total = collections.Counter()
    hit = collections.Counter()
    anybox = collections.Counter()
    t0 = time.time()
    for pid, p in sel:
        sha = p["image"]["sha256"]
        bp = BLOBS / sha[:2] / sha
        if not bp.exists():
            continue
        img = Image.open(bp).convert("RGB")
        arr = np.array(img)
        rs = yolo.predict(arr, conf=conf, imgsz=1024, verbose=False, device="mps")
        preds = []
        for r in rs:
            if r.boxes is None:
                continue
            for box, cls in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist()):
                preds.append((box, int(cls)))
        for a in p["annotations"]:
            name = a.get("name")
            if name not in HARD_SKUS:
                continue
            gx, gy = a["x"], a["y"]
            gt_total[name] += 1
            target_cls = name_to_cls.get(name)
            for box, cls in preds:
                if box[0] <= gx <= box[2] and box[1] <= gy <= box[3]:
                    anybox[name] += 1
                    if cls == target_cls:
                        hit[name] += 1
                    break
    print(f"  耗时 {time.time()-t0:.0f}s")
    print(f"  {'SKU':<16}{'GT':>6}{'同类命中':>8}{'检测召回':>9}{'任意框覆盖':>11}")
    out = {}
    for name in HARD_SKUS:
        g, h, ab = gt_total[name], hit[name], anybox[name]
        rec = h / g if g else 0
        abr = ab / g if g else 0
        out[name] = {"gt": g, "hit": h, "recall": round(rec, 4), "anybox": round(abr, 4)}
        print(f"  {name:<16}{g:>6}{h:>8}{rec*100:>8.1f}%{abr*100:>10.1f}%")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--weight", required=True)
    ap.add_argument("--limit", type=int, default=250)
    ap.add_argument("--conf", type=float, default=0.15)
    a = ap.parse_args()
    run(a.weight, a.limit, a.conf)
