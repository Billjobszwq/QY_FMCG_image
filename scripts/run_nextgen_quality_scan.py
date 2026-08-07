"""N2 Task 4：批3 全量严格质量扫描（断点续跑、幂等、证据 jsonl）。

对 .batch3_clean/blobs 的 22,659 图执行多维 analyzer；坐标点来自
第三批训练数据.xlsx（越界检查）；结论写 jsonl（append-only 续跑，
已扫描 sha 跳过）。自动结论仍需人工校准门（02 §3.3）才能定稿。
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.modules.nextgen_data.quality import (QualityDecisionError,
                                              QualityPolicy, analyze_image)

OUT = ROOT / "reports/nextgen_v2/quality_decisions.jsonl"
STATS = ROOT / "reports/nextgen_v2/quality_scan_stats.json"


def load_batch3_points():
    import openpyxl
    wb = openpyxl.load_workbook(ROOT / "第三批训练数据.xlsx", read_only=True)
    ws = wb.active
    pts = defaultdict(list)
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[0] is None:
            continue
        pts[str(r[0])].append((float(r[11]), float(r[12])))
    wb.close()
    return pts


def main() -> int:
    import openpyxl  # noqa: F401 确认依赖
    pts_by_pid = load_batch3_points()
    cm = json.loads((ROOT / ".batch3_clean/clean_manifest.json")
                    .read_text(encoding="utf-8"))
    done: set[str] = set()
    if OUT.exists():
        with OUT.open() as f:
            for line in f:
                try:
                    done.add(json.loads(line)["sha256"])
                except Exception:
                    continue
    policy = QualityPolicy(version="qpol_n2_v1")
    fout = OUT.open("a", encoding="utf-8")
    stats = defaultdict(int)
    t0 = time.time()
    n = skipped = errors = 0
    for pid, info in cm.items():
        sha = info.get("sha256")
        if not sha or sha in done:
            skipped += 1
            continue
        blob = ROOT / ".batch3_clean/blobs" / sha[:2] / sha
        if not blob.exists():
            errors += 1
            continue
        w = info.get("width") or 0
        h = info.get("height") or 0
        try:
            d = analyze_image(blob, points=pts_by_pid.get(pid, []),
                              width=int(w), height=int(h), policy=policy,
                              strict_bounds=True)
            d["photo_id"] = pid
            d["source_batch"] = "batch3"
            fout.write(json.dumps(d, ensure_ascii=False) + "\n")
            stats[d["conclusion"]] += 1
        except QualityDecisionError as e:
            errs = str(e)
            if "越界" in errs:
                rec = {"photo_id": pid, "sha256": sha,
                       "conclusion": "manual_review",
                       "reasons": ["point_out_of_bounds"],
                       "policy_version": policy.version,
                       "source_batch": "batch3"}
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                stats["manual_review"] += 1
            else:
                rec = {"photo_id": pid, "sha256": sha,
                       "conclusion": "rejected",
                       "reasons": ["decode_failed"],
                       "policy_version": policy.version,
                       "source_batch": "batch3"}
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                stats["rejected"] += 1
        n += 1
        if n % 500 == 0:
            fout.flush()
            elapsed = time.time() - t0
            print(f"scanned={n} skipped={skipped} "
                  f"rate={n/elapsed:.1f}/s stats={dict(stats)}",
                  flush=True)
    fout.close()
    STATS.write_text(json.dumps({
        "scanned_new": n, "skipped_done": skipped, "errors": errors,
        "conclusions": dict(stats), "elapsed_s": round(time.time() - t0, 1),
        "policy_version": policy.version,
        "note": "自动结论；人工校准门（≥1000 张）完成前不得作为过滤终局"},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"scanned": n, "stats": dict(stats)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
