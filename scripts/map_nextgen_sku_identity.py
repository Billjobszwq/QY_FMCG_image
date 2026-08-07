"""N2 Task 5：三批 canonical 点 SKU 身份映射（证据拒绝覆盖）。"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.modules.nextgen_data.sku_identity import SkuIdentityService


def _pts(p):
    a = p.get("annotations")
    if isinstance(a, str):
        a = eval(a) if a.strip() else []  # noqa: S307
    return a or []


def main() -> int:
    out = ROOT / "reports/nextgen_v2/sku_identity_ledger.json"
    if out.exists():
        print(f"证据已存在，拒绝覆盖: {out}")
        return 0
    svc = SkuIdentityService(registry_path=ROOT / "data/sku_registry.json",
                             aliases_path=ROOT / "data/sku_aliases.json")
    stats = defaultdict(int)
    pending: dict[str, int] = defaultdict(int)
    sku_points: dict[str, int] = defaultdict(int)

    def handle(name, code=None):
        r = svc.resolve(name, code=code)
        stats[r["status"]] += 1
        if r["sku_id"]:
            sku_points[r["sku_id"]] += 1
        if r["status"] == "alias_pending":
            pending[name] += 1

    # 批1/批2 canonical：批2 优先 + 批1 独有
    b1 = json.loads((ROOT / ".training_data/manifest.json")
                    .read_text(encoding="utf-8"))["photos"]
    b2 = json.loads((ROOT / ".eval/batch2/manifest.json")
                    .read_text(encoding="utf-8"))["photos"]
    s2 = {(p.get("image") or {}).get("sha256") for p in b2.values()}
    for p in b2.values():
        for pt in _pts(p):
            handle(str(pt.get("name") or ""), code=pt.get("canonical"))
    for p in b1.values():
        if (p.get("image") or {}).get("sha256") in s2:
            continue
        for pt in _pts(p):
            handle(str(pt.get("name") or ""), code=pt.get("canonical"))
    # 批3：xlsx name + code
    import openpyxl
    wb = openpyxl.load_workbook(ROOT / "第三批训练数据.xlsx", read_only=True)
    ws = wb.active
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[0] is None:
            continue
        handle(str(r[9] or ""), code=str(r[10] or ""))
    wb.close()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "registry_version": svc.version(),
        "status_counts": dict(stats),
        "total_points": sum(stats.values()),
        "known_sku_ids": len(sku_points),
        "known_sku_points": sum(sku_points.values()),
        "alias_pending_names": dict(sorted(pending.items())),
        "unknown_tiers_note": "other/百事other/可乐other 及 *other 不强映射；"
                              "进入 unknown/难负样本/拒答训练",
        "taskbook_expected": {"canonical_points": 745695,
                              "known_sku_points": 705104,
                              "unmapped_other_family": 40591},
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(json.dumps({"total": report["total_points"],
                      "statuses": dict(stats),
                      "known_sku_points": report["known_sku_points"],
                      "pending": dict(pending)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
