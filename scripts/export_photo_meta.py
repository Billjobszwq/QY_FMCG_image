"""导出照片门店/session 元数据为 JSON（主环境执行）。

供隔离环境 zero-shot V2 推理脚本消费，避免隔离环境安装 openpyxl。
来源优先级：batch2 manifest（覆盖 sam_refined val split，含 sname/
createtime/typename）；xlsx 仅覆盖早期小样本。两者可叠加。
确定性输出：同输入同输出，可重复执行覆盖（纯派生数据，非证据）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.eval.zeroshot_v2 import parse_photo_rows  # noqa: E402


def meta_from_batch2_manifest(path: Path) -> dict[str, dict]:
    """batch2 manifest photos → {store, store_code, session, photo_type}。"""
    d = json.loads(path.read_text(encoding="utf-8"))
    photos = d.get("photos", d)
    out: dict[str, dict] = {}
    for pid, info in photos.items():
        m = (info or {}).get("meta") or {}
        out[str(pid)] = {
            "store": str(m.get("sname") or ""),
            "store_code": str(m.get("scode") or ""),
            "session": str(m.get("createtime") or "")[:10],
            "photo_type": str(m.get("typename") or ""),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch2-manifest", default=".eval/batch2/manifest.json")
    ap.add_argument("--xlsx", default="实景照片.xlsx")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    meta: dict[str, dict] = {}
    bm = Path(a.batch2_manifest)
    if bm.is_file():
        meta.update(meta_from_batch2_manifest(bm))
    xp = Path(a.xlsx)
    if xp.is_file():
        import openpyxl
        wb = openpyxl.load_workbook(xp, read_only=True)
        ws = wb.worksheets[0]
        rows = ws.iter_rows(min_row=2, values_only=True)
        for k, v in parse_photo_rows(rows).items():
            meta.setdefault(k, v)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"导出 {len(meta)} 张照片元数据 -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
