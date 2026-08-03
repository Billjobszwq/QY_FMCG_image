"""smoke 训练（证明训练体系）：ultralytics 微调 + 在数据底座登记 model_version。
真实训练=更多 approved 照片+更多 epoch；此处 1 图 1 epoch 仅打通链路。"""
from __future__ import annotations

import glob
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.data import warehouse as wh


def code_hash():
    h = hashlib.sha256()
    for f in sorted(glob.glob("src/**/*.py", recursive=True)):
        h.update(open(f, "rb").read())
    return h.hexdigest()[:12]


def train(epochs=1, imgsz=320):
    from ultralytics import YOLO

    ds = Path(".datasets/v1/data.yaml")
    m = YOLO("yolo11n.pt")
    m.train(data=str(ds), epochs=epochs, imgsz=imgsz, batch=1, workers=0, device="cpu", project=".models", name="smoke", exist_ok=True, verbose=False)
    best = Path(".models/smoke/weights/best.pt")
    wp = best if best.exists() else Path(".models/smoke/weights/last.pt")
    metrics = {}
    rc = Path(".models/smoke/results.csv")
    if rc.exists():
        lines = rc.read_text().strip().splitlines()
        if len(lines) > 1:
            metrics = dict(zip([c.strip() for c in lines[0].split(",")], [v.strip() for v in lines[-1].split(",")]))
    conn = wh.connect()
    wh.migrate(conn)
    mv = "smoke-" + time.strftime("%Y%m%d%H%M%S")
    wsha = hashlib.sha256(wp.read_bytes()).hexdigest() if wp.exists() else ""
    conn.execute("INSERT OR REPLACE INTO model_version VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                 (mv, "detect", code_hash(), "datasets/v1", json.dumps({"epochs": epochs, "imgsz": imgsz}), 0,
                  json.dumps(metrics, ensure_ascii=False), str(wp), wsha, "draft", time.time()))
    conn.commit()
    conn.close()
    print("SMOKE_TRAIN", json.dumps({"model_version": mv, "weight": str(wp), "weight_exists": wp.exists(), "metrics_tail": metrics}, ensure_ascii=False))
    return mv


if __name__ == "__main__":
    train()
