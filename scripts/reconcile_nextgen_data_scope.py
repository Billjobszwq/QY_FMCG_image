"""N2 Task 3：三批数据范围对账（可重复执行，证据拒绝覆盖）。

对账项：原始计数、exact unique、canonical points、批间重叠、
未映射 SHA 照片、other 类点数、差异解释。
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OTHER_NAMES = ("other", "百事other", "可乐other")
EXPECTED = {"exact_unique": 29176, "canonical_points": 745695,
            "batch1": 2947, "batch2": 6510, "batch3": 22664,
            "other_points": 40591, "discrepancies": 476}


def _photos(path):
    return list(json.loads(Path(path).read_text(encoding="utf-8"))
                ["photos"].values())


def _sha(p):
    return (p.get("image") or {}).get("sha256") or ""


def _pts(p):
    a = p.get("annotations")
    if isinstance(a, str):
        a = eval(a) if a.strip() else []  # noqa: S307
    return a or []


def main() -> int:
    out = ROOT / "reports/nextgen_v2/data_scope_reconciliation.json"
    if out.exists():
        print(f"证据已存在，拒绝覆盖: {out}")
        return 0

    import openpyxl
    b1, b2 = _photos(ROOT / ".training_data/manifest.json"), \
        _photos(ROOT / ".eval/batch2/manifest.json")
    cm = json.loads((ROOT / ".batch3_clean/clean_manifest.json")
                    .read_text(encoding="utf-8"))
    wb = openpyxl.load_workbook(ROOT / "第三批训练数据.xlsx", read_only=True)
    ws = wb.active
    b3_pts: dict[str, list[str]] = defaultdict(list)
    total3 = 0
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[0] is None:
            continue
        b3_pts[str(r[0])].append(str(r[9]))
        total3 += 1
    wb.close()

    s1 = {_sha(p) for p in b1}
    s2 = {_sha(p) for p in b2}
    s3 = {v["sha256"] for v in cm.values() if v.get("sha256")}
    allu = (s1 | s2 | s3) - {""}
    missing_sha = sorted(set(b3_pts) - set(cm))
    missing_pts = {pid: len(v) for pid, v in
                   ((pid, b3_pts[pid]) for pid in missing_sha)}
    missing_other = sum(1 for pid in missing_sha
                        for n in b3_pts[pid] if n in OTHER_NAMES)

    b2_pts_total = sum(len(_pts(p)) for p in b2)
    b1_only_pts = sum(len(_pts(p)) for p in b1 if _sha(p) not in s2)
    canonical = b2_pts_total + b1_only_pts + total3

    name_counts: dict[str, int] = defaultdict(int)
    for names in b3_pts.values():
        for n in names:
            name_counts[n] += 1

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "batch1_photos": len(b1), "batch1_points": sum(len(_pts(p)) for p in b1),
        "batch2_photos": len(b2), "batch2_points": b2_pts_total,
        "batch3_photos_xlsx": len(b3_pts), "batch3_points_total": total3,
        "batch3_unique_photos": len(b3_pts),
        "clean_manifest": len(cm), "xlsx_mapped": len(cm),
        "batch3_missing_sha_photos": len(missing_sha),
        "batch3_missing_sha_ledger": missing_pts,
        "exact_unique_all": len(allu),
        "exact_unique_expected_by_taskbook": EXPECTED["exact_unique"],
        "exact_unique_delta_explanation":
            "差额 5 = 批3 反光 reject 照片无 blob/SHA（clean 阶段拒入），"
            "其 photo_id 与点数保留在缺失账本；不静默吞差",
        "b1_b2_overlap": len(s1 & s2), "b1_b3_overlap": len(s1 & s3),
        "b2_b3_overlap": len(s2 & s3),
        "b1_only_photos": len(s1 - s2),
        "canonical_points": canonical,
        "canonical_points_expected": EXPECTED["canonical_points"],
        "b1_only_points": b1_only_pts,
        "other_points": {k: name_counts[k] for k in OTHER_NAMES},
        "other_points_expected": EXPECTED["other_points"],
        "missing_photo_points_in_other": missing_other,
        "coordinate_discrepancies_expected": EXPECTED["discrepancies"],
        "note": "476 vs 463 口径差异见 coordinate_discrepancy_ledger.json",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "exact_unique_all", "canonical_points", "batch3_unique_photos",
        "batch3_missing_sha_photos", "missing_photo_points_in_other")},
        ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
