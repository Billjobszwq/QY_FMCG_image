"""W8 Asset/CAS：内容寻址存储。

红线：
- 数据库只存 ResourceRef/哈希/lineage（asset 表），不存路径本体；
- blob 不可变：已存在不覆盖（去重）；读取必校验 sha256（fail-closed）；
- 只复制字节进 CAS，绝不修改/移动/覆盖原图。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import uuid
from pathlib import Path

from ..contracts import AssetRef
from ..data.store import PlatformStore


class CASIntegrityError(Exception):
    """blob 缺失或哈希校验失败。"""


class ContentAddressedStore:
    def __init__(self, root: Path | str, store: PlatformStore) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._store = store

    def _blob_path(self, sha: str) -> Path:
        return self._root / sha[:2] / sha

    def put(self, data: bytes, *, kind: str, media_type: str | None = None) -> AssetRef:
        sha = hashlib.sha256(data).hexdigest()
        path = self._blob_path(sha)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".tmp-{uuid.uuid4().hex}")
            tmp.write_bytes(data)
            os.replace(tmp, path)  # 原子落盘
        # 数据库只存哈希/lineage
        try:
            self._store._conn.execute(
                "INSERT INTO asset(asset_id, sha256, kind, size_bytes, media_type, created_at)"
                " VALUES (?,?,?,?,?,datetime('now'))",
                (sha, sha, kind, len(data), media_type),
            )
            self._store._conn.commit()
        except Exception:
            # UNIQUE(sha256, kind)：重复登记视为幂等
            pass
        return AssetRef(
            asset_id=sha, sha256=sha, kind=kind, size_bytes=len(data), media_type=media_type
        )

    def get(self, sha256: str) -> bytes:
        path = self._blob_path(sha256)
        if not path.exists():
            raise CASIntegrityError(f"blob 不存在: {sha256}")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != sha256:
            raise CASIntegrityError(f"blob 哈希校验失败（损坏）: {sha256}")
        return data

    def exists(self, sha256: str) -> bool:
        return self._blob_path(sha256).exists()

    # ---------- M6：校验 / 备份 / 恢复 / 磁盘水位 ----------

    def _disk_shas(self) -> set[str]:
        out: set[str] = set()
        if not self._root.exists():
            return out
        for shard in self._root.iterdir():
            if shard.is_dir():
                for f in shard.iterdir():
                    if f.is_file() and not f.name.startswith("."):
                        out.add(f.name)
        return out

    def verify_all(self) -> dict:
        """全量重哈希校验：asset 表 vs 磁盘 blob。fail-closed 报告，不修复。"""
        rows = self._store._conn.execute(
            "SELECT sha256 FROM asset"
        ).fetchall()
        registered = [r["sha256"] for r in rows]
        missing: list[str] = []
        corrupt: list[str] = []
        for sha in registered:
            path = self._blob_path(sha)
            if not path.exists():
                missing.append(sha)
                continue
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                corrupt.append(sha)
        orphans = sorted(self._disk_shas() - set(registered))
        return {
            "checked": len(registered),
            "missing": sorted(missing),
            "corrupt": sorted(corrupt),
            "orphans": orphans,
            "ok": not missing and not corrupt,
        }

    def backup(self, archive_path: Path | str) -> dict:
        """打包 blob + 清单（sha256/size）为 tar.gz；返回归档自身哈希。"""
        archive_path = Path(archive_path)
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        entries = []
        with tarfile.open(archive_path, "w:gz") as tf:
            for sha in sorted(self._disk_shas()):
                path = self._blob_path(sha)
                data = path.read_bytes()
                actual = hashlib.sha256(data).hexdigest()
                if actual != sha:
                    raise CASIntegrityError(f"备份前校验失败（损坏）: {sha}")
                tf.add(path, arcname=f"cas/{sha[:2]}/{sha}")
                entries.append({"sha256": sha, "size_bytes": len(data)})
            manifest = json.dumps(
                {"version": "cas-backup-v1", "entries": entries},
                ensure_ascii=False, indent=1,
            ).encode("utf-8")
            import io

            info = tarfile.TarInfo(name="manifest.json")
            info.size = len(manifest)
            tf.addfile(info, io.BytesIO(manifest))
        return {
            "archive": str(archive_path),
            "blobs": len(entries),
            "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        }

    def restore(self, archive_path: Path | str) -> dict:
        """恢复备份：先落临时区逐文件校验清单哈希，全部通过才并入 CAS（fail-closed）。"""
        archive_path = Path(archive_path)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            with tarfile.open(archive_path) as tf:
                tf.extractall(tmp, filter="data")
            manifest = json.loads((tmp / "manifest.json").read_text(encoding="utf-8"))
            entries = manifest["entries"]
            for e in entries:
                src = tmp / "cas" / e["sha256"][:2] / e["sha256"]
                if not src.exists():
                    raise CASIntegrityError(f"备份缺 blob: {e['sha256']}")
                data = src.read_bytes()
                if hashlib.sha256(data).hexdigest() != e["sha256"]:
                    raise CASIntegrityError(f"备份 blob 哈希不匹配: {e['sha256']}")
                if len(data) != int(e["size_bytes"]):
                    raise CASIntegrityError(f"备份 blob 尺寸不匹配: {e['sha256']}")
            # 校验通过 → 原子并入（已存在不覆盖，保持不可变）
            for e in entries:
                src = tmp / "cas" / e["sha256"][:2] / e["sha256"]
                dst = self._blob_path(e["sha256"])
                if not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(src, dst)
            return {"restored": len(entries)}

    def disk_watermark(self, *, free_fraction_threshold: float = 0.10) -> dict:
        """磁盘水位：剩余空间比例低于阈值 → exceeded=True（fail-closed 告警）。"""
        usage = shutil.disk_usage(str(self._root))
        free_fraction = usage.free / usage.total if usage.total else 0.0
        return {
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "free_fraction": round(free_fraction, 6),
            "threshold": free_fraction_threshold,
            "exceeded": free_fraction < free_fraction_threshold,
        }
