"""Gate Q0 批量质量分流（手册§八）：四级 verdict + 证据账本。

- 原图只读，永不移动/删除；reject 仅从训练 manifest 排除；
- 断点续跑：同 policy+analyzer 版本下已记账的 SHA 跳过；
- 报告原子写；账本追加式（QualityEvidenceStore）。

用法：
  python -m scripts.run_quality_batch --n-field 9 --n-grid 111
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

from src.data_quality.runner import QualityRunner

QUALITY_DIR = PROJECT_ROOT / ".quality"


def _paths(n_field: int, n_grid: int):
    manifest = json.loads((PROJECT_ROOT / ".field/manifest.json")
                          .read_text(encoding="utf-8"))
    con = sqlite3.connect(PROJECT_ROOT / ".warehouse/db.sqlite")
    assets = {str(r[0]): r[1] for r in
              con.execute("select asset_id, sha256 from asset")}
    out = []
    for p in manifest["photos"]:
        sha = assets.get(str(p["id"]))
        if not sha:
            continue
        blob = PROJECT_ROOT / ".field/blobs" / sha[:2] / sha
        if blob.exists():
            out.append(blob)
        if len(out) >= n_field:
            break
    pool = sorted([p for ext in ("照片1106", "照片1107")
                   for p in (PROJECT_ROOT / ext).glob("*.jpg")])
    step = max(1, len(pool) // n_grid)
    out += pool[::step][:n_grid]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-field", type=int, default=9)
    ap.add_argument("--n-grid", type=int, default=111)
    a = ap.parse_args()

    paths = _paths(a.n_field, a.n_grid)
    QUALITY_DIR.mkdir(parents=True, exist_ok=True)
    runner = QualityRunner(QUALITY_DIR / "quality.jsonl")
    t0 = time.time()
    summary = runner.process(paths)
    dt = time.time() - t0
    runner.write_report(summary, QUALITY_DIR /
                        f"report_{time.strftime('%Y%m%d_%H%M%S')}.json")

    c = summary["counts"]
    print(f"[quality] photos={len(paths)} processed={summary['processed']} "
          f"skipped={c['skipped']} ({dt:.1f}s)")
    print(f"[quality] accept={c['accept']} warn={c['warn']} "
          f"manual_review={c['manual_review']} reject={c['reject']}")
    print(f"[quality] ratios={summary['ratios']}")
    for row in summary["per_image"][:10]:
        print(f"  {row['verdict']:<13} {row['sha256'][:10]} "
              f"{row['reasons'] or row['quality_tags']}")


if __name__ == "__main__":
    main()
