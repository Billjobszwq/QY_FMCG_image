"""U4-1 真实冒烟：点坐标引导 SAM2.1 Hiera Small（隔离 venv worker）。

- 只读 `.field/manifest.json` + `.field/blobs`（内容寻址原图，不改动）；
- lineage 落 `.eval/u4/smoke.sqlite`（本地证据，不进生产库）；
- masks/报告落 `.eval/u4/smoke_out/`；
- 疑难实例自动升级 Base+（--escalate 默认开启）。

用法：
  python -m scripts.run_u4_sam_smoke --n 2 --max-points 4
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_photos(n: int, max_points: int):
    import sqlite3

    manifest = json.loads((PROJECT_ROOT / ".field/manifest.json")
                          .read_text(encoding="utf-8"))
    con = sqlite3.connect(PROJECT_ROOT / ".warehouse/db.sqlite")
    assets = {str(r[0]): {"sha256": r[1], "width": r[2], "height": r[3]}
              for r in con.execute(
                  "select asset_id, sha256, width, height from asset")}
    photos = []
    for p in manifest["photos"]:
        pid = str(p["id"])
        if pid not in assets or not p.get("annotations"):
            continue
        a = assets[pid]
        blob = PROJECT_ROOT / ".field/blobs" / a["sha256"][:2] / a["sha256"]
        if not blob.exists():
            continue
        anns = p["annotations"][:max_points]
        photos.append({
            "photo_id": pid,
            "image_sha": a["sha256"],
            "width": a["width"], "height": a["height"],
            "image_path": str(blob),
            "instances": [
                {"instance_id": f"{pid}_{i:03d}",
                 "x": float(an["x"]), "y": float(an["y"]),
                 "sku_raw_name": an.get("name", "")}
                for i, an in enumerate(anns)],
        })
        if len(photos) >= n:
            break
    return photos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2)
    ap.add_argument("--max-points", type=int, default=4)
    a = ap.parse_args()

    from src.platform.annotate.sam_pipeline import run_sam_assist
    from src.platform.data.store import PlatformStore

    photos = _load_photos(a.n, a.max_points)
    if not photos:
        raise SystemExit("无可用照片（.field/blobs 与 warehouse 不匹配）")

    eval_dir = PROJECT_ROOT / ".eval" / "u4"
    eval_dir.mkdir(parents=True, exist_ok=True)
    import time
    ts = time.strftime("%Y%m%d_%H%M%S")
    store = PlatformStore(eval_dir / f"smoke_{ts}.sqlite")
    try:
        rep = run_sam_assist(store, images=photos,
                             out_root=eval_dir / "smoke_out")
    finally:
        rows = store.list_sam_lineage(limit=2000)
        store.close()

    rep["lineage_rows"] = len(rows)
    rep["sample_rows"] = [
        {"instance_id": r["instance_id"], "model": r["model"],
         "decision": r["decision"], "escalated_to": r["escalated_to"],
         "tight_box": r["tight_box_json"],
         "mask_sha256": r["mask_sha256"],
         "selection_reason": r["selection_reason"]}
        for r in rows]
    out = eval_dir / f"smoke_report_{ts}.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(json.dumps({k: rep[k] for k in
                      ("n_instances", "accepted", "manual_required",
                       "escalated", "lineage_rows", "run_dir")},
                     ensure_ascii=False))
    print(f"[u4-smoke] report: {out}")


if __name__ == "__main__":
    main()
