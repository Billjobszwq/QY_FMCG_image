"""实景照片入库：解析 xlsx → 按照片(ID)聚合标注 → 按唯一文件名从 OSS 下载(去重) → 落 manifest。

xlsx 每行 = 某照片(ID) 里 (x,y) 处的一个产品，name 为它模给的 SKU 名；
URL 为 .aspx 查看页，真实图由 oss_url() 直连。下载按内容哈希去重。"""
from __future__ import annotations

import collections
import json
from pathlib import Path

import httpx
import openpyxl
from PIL import Image

from ..common import hashing
from ..common.config import PROJECT_ROOT, get_settings
from ..common.oss_urls import oss_url
from ..catalog.alias_registry import build_registry

ALIAS = PROJECT_ROOT / "data" / "sku_aliases.json"
FIELD_DIR = PROJECT_ROOT / ".field"


def _read_rows(xlsx: Path):
    wb = openpyxl.load_workbook(str(xlsx), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(c).strip() if c else "" for c in rows[0]]
    idx = {name: header.index(name) for name in header if name in header}
    out = []
    for r in rows[1:]:
        g = lambda k: r[idx[k]] if k in idx and idx[k] < len(r) else None
        out.append(
            {
                "id": g("ID"),
                "scode": g("SCode"),
                "sname": g("SName"),
                "item": g("ItemName"),
                "typename": g("TypeName"),
                "typevalue": g("TypeValue"),
                "createtime": str(g("CreateTime")) if g("CreateTime") else None,
                "url": g("URL"),
                "filename": g("TypeValue"),
                "name": g("name"),
                "x": g("x"),
                "y": g("y"),
            }
        )
    return out


def group_photos(rows) -> dict:
    photos = collections.OrderedDict()
    for r in rows:
        pid = r["id"]
        if pid not in photos:
            photos[pid] = {
                "id": pid,
                "filename": r["filename"],
                "url": r["url"],
                "meta": {
                    "scode": r["scode"],
                    "sname": r["sname"],
                    "item": r["item"],
                    "typename": r["typename"],
                    "createtime": r["createtime"],
                },
                "annotations": [],
            }
        photos[pid]["annotations"].append({"x": r["x"], "y": r["y"], "name": r["name"], "canonical": None})
    return photos


def download_photos(photos: dict, blobs: Path) -> dict:
    """按唯一文件名下载；返回 filename -> {sha256,width,height,bytes,ok,err}。"""
    blobs.mkdir(parents=True, exist_ok=True)
    order = list({p["filename"] for p in photos.values() if p["filename"]})
    info: dict = {}
    with httpx.Client(follow_redirects=True, timeout=60.0, headers={"User-Agent": "Mozilla/5.0"}) as c:
        for fn in order:
            url = oss_url(fn)
            try:
                r = c.get(url)
                if r.status_code != 200 or not r.content:
                    info[fn] = {"ok": False, "err": f"http_{r.status_code}", "url": url}
                    continue
                b = r.content
                h = hashing.sha256_bytes(b)
                bp = blobs / h[:2] / h
                if not bp.exists():
                    bp.parent.mkdir(parents=True, exist_ok=True)
                    bp.write_bytes(b)
                with Image.open(bp) as im:
                    w, ht = im.size
                info[fn] = {"ok": True, "sha256": h, "width": w, "height": ht, "bytes": len(b), "url": url}
            except Exception as e:
                info[fn] = {"ok": False, "err": f"{type(e).__name__}:{str(e)[:120]}", "url": url}
    return info


def main() -> dict:
    s = get_settings()
    rows = _read_rows(Path(s.field_xlsx))
    photos = group_photos(rows)
    kb_names = sorted(p.name for p in Path(s.reference_dir).iterdir() if p.is_dir())
    field_names = sorted({a["name"] for p in photos.values() for a in p["annotations"] if a["name"]})
    reg = build_registry(kb_names, ALIAS, extra_names=field_names)

    n_resolved = n_unresolved = 0
    for p in photos.values():
        for a in p["annotations"]:
            r = reg.resolve(a["name"])
            a["canonical"] = r[0] if r else None
            (n_resolved if r else n_unresolved) and None
            if r:
                n_resolved += 1
            else:
                n_unresolved += 1

    blobs = FIELD_DIR / "blobs"
    info = download_photos(photos, blobs)
    for p in photos.values():
        fi = info.get(p["filename"], {})
        p["image"] = {k: fi.get(k) for k in ("sha256", "width", "height", "ok", "err")}

    manifest = {"photos": list(photos.values()), "images": info}
    FIELD_DIR.mkdir(parents=True, exist_ok=True)
    (FIELD_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    by_type = collections.Counter(p["meta"]["typename"] for p in photos.values())
    by_store = collections.Counter(p["meta"]["sname"] for p in photos.values())
    summary = {
        "photos": len(photos),
        "unique_images": len(info),
        "downloaded_ok": sum(1 for v in info.values() if v.get("ok")),
        "download_failed": [fn for fn, v in info.items() if not v.get("ok")],
        "annotations": n_resolved + n_unresolved,
        "annotations_canonical_resolved": n_resolved,
        "annotations_unresolved": n_unresolved,
        "by_type": dict(by_type),
        "by_store": dict(by_store),
        "manifest": str(FIELD_DIR / "manifest.json"),
    }
    print("FIELD_INGEST_SUMMARY", json.dumps(summary, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    main()
