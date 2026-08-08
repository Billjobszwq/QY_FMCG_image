"""M1 Detector 训练（pilot/candidate），run artifact 九要素快照。

九要素：source commit / dirty diff hash / launcher source hash /
resolved command / environment lock / data manifest / base model hash /
config / seed。不继承旧生产模型。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASES = {"yolo11n.pt": ROOT / "yolo11n.pt", "yolov8n.pt": ROOT / "yolov8n.pt"}


def run_snapshot(run_dir: Path, args, data_manifest: dict) -> dict:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "diff", "HEAD"], cwd=ROOT,
                           capture_output=True, text=True).stdout
    snap = {
        "source_commit": head,
        "dirty_diff_hash": hashlib.sha256(dirty.encode()).hexdigest(),
        "launcher_source_hash": hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest(),
        "resolved_command": sys.argv,
        "environment_lock": sys.version.split()[0],
        "data_manifest_sha": data_manifest.get("manifest_hash", ""),
        "base_model_sha": hashlib.sha256(
            BASES[args.base].read_bytes()).hexdigest(),
        "config": {"epochs": args.epochs, "batch": args.batch,
                   "imgsz": args.imgsz, "base": args.base},
        "seed": args.seed,
    }
    (run_dir / "source_snapshot.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    return snap


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--base", default="yolo11n.pt")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    run_dir = ROOT / ".models" / a.run_name
    if run_dir.exists():
        raise SystemExit(f"run 目录已存在，拒绝覆盖: {run_dir}")
    run_dir.mkdir(parents=True)
    data = ROOT / a.data_dir
    manifest = json.loads((data / "manifest.json").read_text())
    snap = run_snapshot(run_dir, a, manifest)

    from ultralytics import YOLO
    model = YOLO(str(BASES[a.base]))  # 公开基础权重，非旧生产模型
    t0 = time.time()
    res = model.train(data=str(data / "data.yaml"), epochs=a.epochs,
                      batch=a.batch, imgsz=a.imgsz, device="mps",
                      project=str(run_dir / "runs"), name="train",
                      seed=a.seed, exist_ok=False, verbose=False)
    dur = time.time() - t0
    best = run_dir / "runs" / "train" / "weights" / "best.pt"
    (run_dir / "weights").mkdir(exist_ok=True)
    import shutil
    shutil.copy(best, run_dir / "weights" / "best.pt")
    metrics = res.results_dict if hasattr(res, "results_dict") else {}
    rep = {"run": a.run_name, "lane": "detector", "epochs": a.epochs,
           "duration_s": round(dur, 1),
           "metrics": {k: float(v) for k, v in metrics.items()
                       if isinstance(v, (int, float))},
           "artifact_sha256": hashlib.sha256(
               (run_dir / "weights/best.pt").read_bytes()).hexdigest(),
           "source_snapshot": snap,
           "candidate": a.epochs >= 5,
           "kind": "pilot" if a.epochs < 30 else "candidate"}
    (run_dir / "train_report.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"done": True,
                      "mAP50": rep["metrics"].get("metrics/mAP50(B)"),
                      "duration_s": rep["duration_s"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
