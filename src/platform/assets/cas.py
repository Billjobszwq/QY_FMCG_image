"""W8 Asset/CAS：内容寻址存储。

红线：
- 数据库只存 ResourceRef/哈希/lineage（asset 表），不存路径本体；
- blob 不可变：已存在不覆盖（去重）；读取必校验 sha256（fail-closed）；
- 只复制字节进 CAS，绝不修改/移动/覆盖原图。
"""

from __future__ import annotations

import hashlib
import os
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
