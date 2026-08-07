"""diagnostic_v1_truebox_v2 正式导出驱动（任务书§十三）。

从生产库（只读使用）导出 gold_region_v1 终态区域为不可变真值文件：
  .data_protocol/diagnostic_v1_truebox_v2.json

fail-closed 约定：
- 默认严格模式：存在 submitted/conflict 区域或失效队列区域 → 拒绝导出；
  --non-strict 时仅输出终态区域（被禁类别仍绝不进入）；
- 0 gold → 只打印"无 gold，未写文件"，绝不写空真值文件；
- 目标文件已存在 → FileExistsError（不可变制品禁止覆盖）。

用法：
  python -m scripts.export_truebox_v2 [--db PATH] [--non-strict]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from src.platform.data.store import PlatformStore
from src.review.truebox_export import export_truebox_gold

DEFAULT_DB = ROOT / ".platform" / "platform.sqlite"
MANIFEST = ROOT / ".batch3_clean" / "clean_manifest.json"
PROTOCOL = ROOT / ".data_protocol" / "diagnostic_v1.json"
OUT = ROOT / ".data_protocol" / "diagnostic_v1_truebox_v2.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--non-strict", action="store_true",
                    help="仅输出终态区域（默认严格模式 fail-closed）")
    a = ap.parse_args()

    db = Path(a.db)
    if not db.is_file():
        print(f"[export_truebox_v2] 生产库不存在: {db}", file=sys.stderr)
        return 2
    for req in (MANIFEST, PROTOCOL):
        if not req.is_file():
            print(f"[export_truebox_v2] 依赖制品缺失: {req}", file=sys.stderr)
            return 2

    store = PlatformStore(db)
    try:
        res = export_truebox_gold(
            store, out_path=OUT, manifest_path=MANIFEST,
            protocol_path=PROTOCOL, strict=not a.non_strict)
    finally:
        store.close()

    if not res["written"]:
        print("[export_truebox_v2] 无 gold 终态区域，未写文件"
              f"（counts={res['counts']}）")
        return 0
    c = res["counts"]
    print(f"[export_truebox_v2] 已导出 {res['path']}")
    print(f"[export_truebox_v2] export_hash={res['export_hash']}")
    print(f"[export_truebox_v2] counts={c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
