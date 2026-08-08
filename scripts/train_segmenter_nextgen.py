"""N2 Task 12：M2 YOLO-seg nextgen smoke（学习审核后 SAM mask 的学生）。

base：ultralytics 公开 seg 权重（yolo11n-seg.pt）；SAM 本体冻结不训。
1 epoch smoke 只验管线，非 candidate。run 目录已存在拒绝。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODELS_DIR = ROOT / ".models"


def _snapshot(run_dir: Path) -> None:
    import hashlib
    import subprocess
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "diff", "HEAD"], cwd=ROOT,
                           capture_output=True, text=True).stdout
    (run_dir / "source_snapshot.json").write_text(json.dumps({
        "source_commit": head,
        "dirty_diff_hash": hashlib.sha256(dirty.encode()).hexdigest(),
        "launcher_source_hash": hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest(),
        "resolved_command": sys.argv,
        "environment_lock": sys.version.split()[0],
        "seed": 42}, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-yaml", required=True)
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--model", default="yolo11n-seg.pt")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=8)
    a = ap.parse_args()

    run_dir = MODELS_DIR / a.run_name
    if run_dir.exists():
        raise SystemExit(f"run 目录已存在，拒绝覆盖: {run_dir}")

    from ultralytics import YOLO
    t0 = time.time()
    model = YOLO(a.model)
    results = model.train(data=a.data_yaml, epochs=a.epochs,
                          imgsz=a.imgsz, batch=a.batch, device="mps",
                          seed=42, deterministic=True,
                          project=str(MODELS_DIR), name=a.run_name,
                          exist_ok=False, patience=5, verbose=False)
    src = Path(results.save_dir)
    # ultralytics 已写入 run 目录；登记 lineage meta（不覆盖权重）
    meta = {"run": a.run_name, "lane": "segmenter",
            "kind": "one_epoch_smoke",
            "base": f"{a.model}(public)",
            "lineage_family": "fmcg_nextgen_v1",
            "teacher": "sam2.1_hiera_small(frozen)",
            "label_source": "sam_verified_pseudo",
            "evidence_level": "smoke_pseudo_interim",
            "duration_s": round(time.time() - t0, 1),
            "epochs": a.epochs, "candidate": False}
    best = src / "weights" / "best.pt"
    if best.exists():
        meta["artifact_sha256"] = hashlib.sha256(
            best.read_bytes()).hexdigest()
    (src / "nextgen_smoke_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"done": True,
                      "sha": meta.get("artifact_sha256", "")[:16],
                      "duration_s": meta["duration_s"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
