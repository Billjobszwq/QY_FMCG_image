"""U3-1：照片来源扫描器（手册 §5.1 全来源，只读、追加式）。

只统计、不移动、不覆盖、不删除任何原文件。输出每个来源的
raw_count / sha_present / download_failed / missing；total_raw 是
各来源原始数之和（含重复），禁止把它当作唯一照片总数——唯一数
由 U3-3 的 SHA 精确去重产出。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic"}

# 手册 §5.1 全部来源族（路径相对仓库根；缺失来源显式报 missing）
DEFAULT_SOURCES: list[dict[str, str]] = [
    {"source_id": "batch1_manifest", "type": "manifest_photos_dict",
     "path": ".training_data/manifest.json"},
    {"source_id": "batch2_manifest", "type": "manifest_photos_dict",
     "path": ".eval/batch2/manifest.json"},
    {"source_id": "batch3_clean", "type": "manifest_sha_dict",
     "path": ".batch3_clean/clean_manifest.json"},
    {"source_id": "batch3_gray", "type": "manifest_sha_dict",
     "path": "batch3_gray/gray_manifest.json"},
    {"source_id": "photo1106", "type": "directory", "path": "照片1106"},
    {"source_id": "photo1107", "type": "directory", "path": "照片1107"},
    {"source_id": "pepsi_cola", "type": "directory", "path": "百事&可口"},
    {"source_id": "p1_reference", "type": "directory",
     "path": "搭建初期P1"},
    {"source_id": "field_blobs", "type": "manifest_photos_list",
     "path": ".field/manifest.json"},
    {"source_id": "bad_samples", "type": "directory", "path": "bad_samples"},
    {"source_id": "protocols", "type": "protocol_dir",
     "path": ".data_protocol"},
]


def _entry(spec: dict[str, str], **kw: Any) -> dict[str, Any]:
    base = {
        "source_id": spec["source_id"],
        "source_type": spec["type"],
        "path": spec["path"],
        "raw_count": 0,
        "sha_present": 0,
        "download_failed": 0,
        "missing": False,
    }
    base.update(kw)
    return base


def _scan_manifest_photos_dict(root: Path, spec: dict[str, str]) -> dict:
    """photos 为 {photo_id: {image: {ok, sha256}}} 的 manifest。"""
    p = root / spec["path"]
    if not p.is_file():
        return _entry(spec, missing=True)
    data = json.loads(p.read_text(encoding="utf-8"))
    photos = data.get("photos", {}) if isinstance(data, dict) else {}
    sha = failed = 0
    for v in photos.values():
        img = v.get("image") or {}
        if img.get("ok") and img.get("sha256"):
            sha += 1
        if img.get("ok") is False:
            failed += 1
    return _entry(spec, raw_count=len(photos), sha_present=sha,
                  download_failed=failed)


def _scan_manifest_sha_dict(root: Path, spec: dict[str, str]) -> dict:
    """{photo_id: {sha256: ...}} 顶层字典 manifest（batch3 gate）。"""
    p = root / spec["path"]
    if not p.is_file():
        return _entry(spec, missing=True)
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return _entry(spec, missing=True)
    sha = sum(1 for v in data.values()
              if isinstance(v, dict) and v.get("sha256"))
    return _entry(spec, raw_count=len(data), sha_present=sha)


def _scan_manifest_photos_list(root: Path, spec: dict[str, str]) -> dict:
    """photos 为列表的 manifest（.field）。"""
    p = root / spec["path"]
    if not p.is_file():
        return _entry(spec, missing=True)
    data = json.loads(p.read_text(encoding="utf-8"))
    photos = data.get("photos", []) if isinstance(data, dict) else []
    return _entry(spec, raw_count=len(photos))


def _scan_directory(root: Path, spec: dict[str, str]) -> dict:
    """本地目录：只计图片扩展名文件（递归，含 SKU 子目录）。"""
    d = root / spec["path"]
    if not d.is_dir():
        return _entry(spec, missing=True)
    n = sum(1 for f in d.rglob("*")
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS)
    return _entry(spec, raw_count=n)


def _scan_protocol_dir(root: Path, spec: dict[str, str]) -> dict:
    """frozen protocols：每个协议文件的 photo_ids 数。"""
    d = root / spec["path"]
    if not d.is_dir():
        return _entry(spec, missing=True)
    n = sha = 0
    detail: dict[str, int] = {}
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        ids = data.get("photo_ids", [])
        detail[f.name] = len(ids)
        n += len(ids)
        sha += len(data.get("sha256", []))
    return _entry(spec, raw_count=n, sha_present=sha, detail=detail)


_SCANNERS = {
    "manifest_photos_dict": _scan_manifest_photos_dict,
    "manifest_sha_dict": _scan_manifest_sha_dict,
    "manifest_photos_list": _scan_manifest_photos_list,
    "directory": _scan_directory,
    "protocol_dir": _scan_protocol_dir,
}


def scan_sources(root: Path, sources: list[dict[str, str]] | None = None,
                 ) -> dict[str, Any]:
    """只读扫描全部来源。total_raw 为原始数之和（含跨来源重复）。"""
    srcs = DEFAULT_SOURCES if sources is None else sources
    out: list[dict[str, Any]] = []
    for spec in srcs:
        fn = _SCANNERS.get(spec["type"])
        if fn is None:
            out.append(_entry(spec, missing=True))
            continue
        out.append(fn(root, spec))
    total = sum(s["raw_count"] for s in out)
    return {
        "sources": out,
        "total_raw": total,
        "note": ("total_raw 为各来源原始数之和（含重复），"
                 "不是唯一照片总数；唯一数由 SHA 去重（U3-3）产出"),
    }
