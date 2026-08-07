"""历史 assisted 项目可见 SKU prediction 非破坏性回填 CLI。

用法：
  python -m scripts.backfill_visible_sku_predictions            # dry-run 扫描
  python -m scripts.backfill_visible_sku_predictions --apply    # 追加回填

红线：
- 只处理 title 含 "[assisted]" 的项目；blind 项目永不回填；
- 纯追加 <原model_version>@visible-sku-v2，不覆盖/不删除旧 prediction、
  不修改人工 annotation；同 task+model_version 重复执行跳过；
- 每次执行写审计报告与任务级错误账本到 reports/backfill_visible_sku/。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "reports" / "backfill_visible_sku"


def main() -> None:
    ap = argparse.ArgumentParser(description="可见 SKU prediction 回填")
    ap.add_argument("--apply", action="store_true",
                    help="真正追加 prediction（默认只 dry-run 扫描）")
    ap.add_argument("--projects", type=str, default="",
                    help="限定项目 id（逗号分隔）；默认全部 assisted 项目")
    args = ap.parse_args()

    from src.ls_platform.backfill import (
        backfill_project,
        scan_project,
        select_assisted_projects,
    )
    from src.ls_platform.ls_client import LSClient
    from src.modules.labeling.service import load_default_registry
    from src.platform.adapters.legacy.recognition import RecognitionV2Adapter

    ls = LSClient()
    registry = load_default_registry()
    projects = select_assisted_projects(ls)
    if args.projects:
        wanted = {int(x) for x in args.projects.split(",") if x.strip()}
        projects = [p for p in projects if p["id"] in wanted]
    if not projects:
        raise SystemExit("没有符合条件的 assisted 项目")

    recognition = RecognitionV2Adapter()
    reports = []
    try:
        for p in projects:
            if args.apply:
                rep = backfill_project(ls, recognition, p["id"],
                                       registry=registry, apply=True)
            else:
                rep = scan_project(ls, p["id"], registry)
            reports.append(rep)
            print(json.dumps(
                {"project_id": p["id"], "title": p["title"],
                 "stats": rep["stats"],
                 **({"added": rep.get("added"),
                     "skipped_idempotent": rep.get("skipped_idempotent"),
                     "errors": len(rep.get("errors", []))}
                    if args.apply else {})},
                ensure_ascii=False))
    finally:
        recognition.close()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    mode = "apply" if args.apply else "dry_run"
    out = REPORT_DIR / f"{mode}_{stamp}.json"
    out.write_text(json.dumps(reports, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"audit report -> {out}")


if __name__ == "__main__":
    main()
