"""补 M2 pilot 报告（results.csv + 九要素快照）。"""
import csv
import hashlib
import json
import shutil
from pathlib import Path

run = Path(".models/nextgen_segmenter_pilot_v1")
rows = list(csv.DictReader(open(run / "results.csv")))
best = max(rows, key=lambda r: float(r.get("metrics/mAP50(B)", 0)))
(run / "weights").mkdir(exist_ok=True)
if not (run / "weights/best.pt").exists():
    shutil.copy(run / "runs/train/weights/best.pt", run / "weights/best.pt")
rep = {"run": "nextgen_segmenter_pilot_v1", "lane": "segmenter",
       "epochs": len(rows),
       "metrics": {"mAP50": float(best["metrics/mAP50(B)"]),
                   "mAP50-95": float(best["metrics/mAP50-95(B)"])},
       "artifact_sha256": hashlib.sha256(
           (run / "weights/best.pt").read_bytes()).hexdigest(),
       "source_snapshot": json.loads(
           (run / "source_snapshot.json").read_text()),
       "candidate": True, "kind": "pilot",
       "note": "pseudo_mask_interim；无人工 mask 不升级"}
(run / "train_report.json").write_text(
    json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
print("M2 report:", rep["metrics"])
