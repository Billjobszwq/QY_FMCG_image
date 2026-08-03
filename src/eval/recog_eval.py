"""识别质量评测：通用检测+KB识别 vs 金标。

复用 pipeline.autolabel 的评测逻辑，输出检测召回、识别准确（在检出的框上）。
报告写 .labels/recog_eval.json。
用法：python -m src.eval.recog_eval [--max-photos N] [--conf 0.45]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common import paths
from src.common.config import PROJECT_ROOT

LABEL = PROJECT_ROOT / ".labels"


def evaluate(max_photos=9, conf=0.45, topk=5, unknown_thr=0.30):
    from src.pipeline.autolabel import run as _run

    report = _run(max_photos=max_photos, conf=conf, topk=topk, unknown_thr=unknown_thr)
    out = {
        "params": report["params"],
        "photos_evaluated": report["photos_evaluated"],
        "detection_recall": report["detection_recall"],
        "sku_top1_lenient": report["sku_top1_lenient"],
        "sku_top1_strict": report["sku_top1_strict"],
        "unknown_on_known_rate": report["unknown_on_known_rate"],
        "totals": report["totals"],
        "by_store": report.get("by_store", {}),
        "by_type": report.get("by_type", {}),
    }
    LABEL.mkdir(parents=True, exist_ok=True)
    paths.safe_write_text(LABEL / "recog_eval.json", json.dumps(out, ensure_ascii=False, indent=2))
    print("RECOG_EVAL", json.dumps({k: out[k] for k in ["photos_evaluated", "detection_recall", "sku_top1_lenient", "sku_top1_strict", "unknown_on_known_rate"]}, ensure_ascii=False))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-photos", type=int, default=9)
    ap.add_argument("--conf", type=float, default=0.45)
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--unknown-thr", type=float, default=0.30)
    a = ap.parse_args()
    evaluate(a.max_photos, a.conf, a.topk, a.unknown_thr)
