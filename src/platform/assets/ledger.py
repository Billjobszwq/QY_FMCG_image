"""U3-2：从 U3-1 扫描结果建账（不可变 source_asset_inventory_v1）。

数量守恒：台账行数 == scan 报告 total_raw（每个来源的每条原始记录都登记
一条 source reference）。追加式幂等：重跑不新增。原图不动：只登记
path#photo_id 形式的引用与 SHA，不复制、移动、覆盖任何文件。

- manifest 来源：source_uri = "{manifest 路径}#{photo_id}"，SHA 取 manifest
  已记录的 sha256（batch1/2/3/field 均已内置，无需重哈希）。
- 目录来源：source_uri = 相对路径，SHA 现场 hashlib.sha256 读文件计算
  （只读，不写回）。
- protocol 来源：source_uri = "{协议文件}#{photo_id}"，SHA 取协议的
  sha256 平行列表（无则留空，U3-3 回填或跳过）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.platform.assets.inventory import DEFAULT_SOURCES, IMAGE_EXTS


def _file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _reg(store, spec, uri, photo_id, sha) -> None:
    """登记一条 source reference（幂等）。新增数由建账前后 count 差得出。"""
    store.register_inventory_asset(
        source_id=spec["source_id"], source_type=spec["type"],
        source_uri=uri, photo_id=str(photo_id), sha256=sha or "")


def _build_manifest_photos_dict(store, root: Path, spec: dict) -> int:
    p = root / spec["path"]
    if not p.is_file():
        return 0
    data = json.loads(p.read_text(encoding="utf-8"))
    photos = data.get("photos", {}) if isinstance(data, dict) else {}
    for pid, v in photos.items():
        img = (v or {}).get("image") or {}
        _reg(store, spec, f"{spec['path']}#{pid}", pid, img.get("sha256"))
    return 0


def _build_manifest_sha_dict(store, root: Path, spec: dict) -> int:
    p = root / spec["path"]
    if not p.is_file():
        return 0
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return 0
    for pid, v in data.items():
        sha = v.get("sha256") if isinstance(v, dict) else None
        _reg(store, spec, f"{spec['path']}#{pid}", pid, sha)
    return 0


def _build_manifest_photos_list(store, root: Path, spec: dict) -> int:
    p = root / spec["path"]
    if not p.is_file():
        return 0
    data = json.loads(p.read_text(encoding="utf-8"))
    photos = data.get("photos", []) if isinstance(data, dict) else []
    for v in photos:
        pid = (v or {}).get("id", "")
        img = (v or {}).get("image") or {}
        _reg(store, spec, f"{spec['path']}#{pid}", pid, img.get("sha256"))
    return 0


def _build_directory(store, root: Path, spec: dict) -> int:
    d = root / spec["path"]
    if not d.is_dir():
        return 0
    for f in sorted(d.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in IMAGE_EXTS:
            continue
        uri = f.relative_to(root).as_posix()
        _reg(store, spec, uri, f.name, _file_sha256(f))
    return 0


def _build_protocol_dir(store, root: Path, spec: dict) -> int:
    d = root / spec["path"]
    if not d.is_dir():
        return 0
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        ids = data.get("photo_ids", [])
        shas = data.get("sha256", [])
        rel = f.relative_to(root).as_posix()
        for i, pid in enumerate(ids):
            sha = shas[i] if i < len(shas) else ""
            _reg(store, spec, f"{rel}#{pid}", pid, sha)
    return 0


_BUILDERS = {
    "manifest_photos_dict": _build_manifest_photos_dict,
    "manifest_sha_dict": _build_manifest_sha_dict,
    "manifest_photos_list": _build_manifest_photos_list,
    "directory": _build_directory,
    "protocol_dir": _build_protocol_dir,
}


def build_ledger_from_scan(store, root: Path,
                           sources: list[dict] | None = None) -> int:
    """从扫描口径建账，返回本次新增行数（重跑幂等返回 0）。"""
    srcs = DEFAULT_SOURCES if sources is None else sources
    before = store.count_inventory_assets()
    for spec in srcs:
        fn = _BUILDERS.get(spec["type"])
        if fn is None:
            continue
        fn(store, root, spec)
    return store.count_inventory_assets() - before
