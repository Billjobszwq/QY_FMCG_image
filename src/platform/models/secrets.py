"""SecretStore port + AES-256-GCM envelope encryption（M2/G1，02 §5）。

纪律（DEC-M005 凭据只写不读）：
- 算法 AES-256-GCM；每个 secret version 独立随机 DEK（32B）与 nonce（12B）；
  DEK 用 KEK 以 AES-GCM envelope 包裹。
- AAD = canonical JSON(tenant_id, secret_ref, version, adapter_kind)；
  scope 不符（租户/适配器/版本）解密失败，fail-closed。
- KEK 只能运行时注入（32 字节）；缺失时整个 SecretStore 为 unavailable，
  绝不用默认 key，也不自动落盘 key。
- 明文只存在于 ``SecretLease.value``（短租约）与调用方内存；repr/dump/
  日志/异常/数据库字段均不得出现。
- 轮换生成新版本并 revoke 旧版本；运行时不得自动回落旧值。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Protocol

try:  # cryptography 属可选依赖组 model-providers；缺失时 fail-closed
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:  # pragma: no cover - 取决于宿主安装
    AESGCM = None  # type: ignore[assignment]

from src.platform.models.contracts import (
    MODEL_SECRET_UNAVAILABLE,
    ModelManagementError,
)

ALGORITHM = "AES-256-GCM"
_KEK_LEN = 32
_DEK_LEN = 32
_NONCE_LEN = 12
DEFAULT_LEASE_TTL_SECONDS = 60.0


class SecretStoreError(ModelManagementError):
    code = MODEL_SECRET_UNAVAILABLE
    http_status = 503


class SecretStoreUnavailable(SecretStoreError):
    """KEK 未注入或 SecretStore 不可用（503）。"""


class SecretNotFoundError(SecretStoreError):
    """secret 不存在/已撤销/跨租户不可见（统一零泄漏）。"""


class SecretLeaseExpired(SecretStoreError):
    """短租约过期：调用方必须重新 lease。"""


@dataclass(frozen=True)
class SecretScope:
    """AAD 绑定范围：tenant + secret_ref + adapter_kind。"""

    tenant_id: str
    secret_ref: str
    adapter_kind: str

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.secret_ref or not self.adapter_kind:
            raise ValueError(
                "SecretScope 需要非空 tenant_id/secret_ref/adapter_kind")


@dataclass(frozen=True)
class SecretMeta:
    """可安全暴露的 secret 元数据（不含任何密文字段）。"""

    secret_ref: str
    version: int
    tenant_id: str
    status: str
    algorithm: str
    key_id: str
    aad_hash: str
    created_by: str
    created_at: str
    rotated_at: str | None = None


@dataclass(frozen=True)
class SecretLease:
    """短生命周期明文租约。value 永不进入 repr/str。"""

    secret_ref: str
    version: int
    value: bytes = field(repr=False)
    expires_at: float = field(repr=False, default=0.0)

    def __repr__(self) -> str:  # pragma: no cover - 纯保护性
        return (f"SecretLease(secret_ref={self.secret_ref!r}, "
                f"version={self.version}, expires_at={self.expires_at})")

    def __str__(self) -> str:
        return self.__repr__()


class SecretStore(Protocol):
    def put(self, scope: SecretScope, value: bytes, actor: str) -> SecretMeta:
        ...

    def lease(self, ref: str, scope: SecretScope, *,
              ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS) -> SecretLease:
        ...

    def lease_version(self, ref: str, version: int, scope: SecretScope, *,
                      ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS
                      ) -> SecretLease:
        ...

    def rotate(self, scope: SecretScope, value: bytes,
               actor: str) -> SecretMeta:
        ...

    def revoke(self, ref: str, actor: str) -> None:
        ...

    def metadata(self, ref: str) -> dict:
        ...

    def validate_lease(self, lease: SecretLease) -> None:
        ...


def _canonical_aad(*, tenant_id: str, secret_ref: str, version: int,
                   adapter_kind: str) -> bytes:
    return json.dumps(
        {"adapter_kind": adapter_kind, "secret_ref": secret_ref,
         "tenant_id": tenant_id, "version": version},
        sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _utcnow_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class EncryptedSQLiteSecretStore:
    """以 ``model_secret_envelope_v1`` 为持久层的 envelope 加密实现。

    ``kek`` 必须由组合根运行时注入（例如读取
    ``TAAS_MODEL_SECRET_KEK``）；传 None 表示不可用而非默认 key。
    """

    def __init__(self, store, *, kek: bytes | None) -> None:
        self._store = store
        if kek is not None and len(kek) != _KEK_LEN:
            raise ValueError(f"KEK 必须是 {_KEK_LEN} 字节")
        self._kek = kek

    # ------------------------------------------------------------- internals

    def _require_kek(self) -> bytes:
        if AESGCM is None:
            raise SecretStoreUnavailable(
                "SecretStore 不可用：未安装 cryptography"
                "（可选依赖组 model-providers）")
        if self._kek is None:
            raise SecretStoreUnavailable(
                "SecretStore 未配置 KEK：拒绝使用默认 key")
        return self._kek

    @property
    def _key_id(self) -> str:
        assert self._kek is not None
        return hashlib.sha256(b"kek-fp:" + self._kek).hexdigest()[:16]

    def _conn(self) -> sqlite3.Connection:
        return self._store._conn

    def _fetch(self, ref: str, version: int | None = None,
               status: str | None = None) -> sqlite3.Row | None:
        sql = ("SELECT * FROM model_secret_envelope_v1 WHERE secret_ref=?")
        args: list = [ref]
        if version is not None:
            sql += " AND version=?"
            args.append(version)
        if status is not None:
            sql += " AND status=?"
            args.append(status)
        sql += " ORDER BY version DESC LIMIT 1"
        return self._conn().execute(sql, args).fetchone()

    def _decrypt_row(self, row: sqlite3.Row, scope: SecretScope) -> bytes:
        if row["tenant_id"] != scope.tenant_id:
            # 跨租户：与不存在同语义，零泄漏
            raise SecretNotFoundError("secret 不存在或不可见")
        aad = _canonical_aad(
            tenant_id=row["tenant_id"], secret_ref=row["secret_ref"],
            version=row["version"], adapter_kind=scope.adapter_kind)
        wrapped_blob = bytes(row["wrapped_dek"])
        wrap_nonce, wrapped_dek = (wrapped_blob[:_NONCE_LEN],
                                   wrapped_blob[_NONCE_LEN:])
        try:
            dek = AESGCM(self._require_kek()).decrypt(
                wrap_nonce, wrapped_dek, aad)
            return AESGCM(dek).decrypt(
                bytes(row["nonce"]), bytes(row["ciphertext"]), aad)
        except SecretNotFoundError:
            raise
        except Exception as e:
            raise SecretStoreError("secret 解密失败：AAD/scope 不符") from e

    def _insert(self, *, scope: SecretScope, value: bytes, actor: str,
                version: int) -> SecretMeta:
        kek = self._require_kek()
        dek = os.urandom(_DEK_LEN)
        nonce = os.urandom(_NONCE_LEN)
        wrap_nonce = os.urandom(_NONCE_LEN)
        aad = _canonical_aad(
            tenant_id=scope.tenant_id, secret_ref=scope.secret_ref,
            version=version, adapter_kind=scope.adapter_kind)
        wrapped_dek = AESGCM(kek).encrypt(wrap_nonce, dek, aad)
        ciphertext = AESGCM(dek).encrypt(nonce, value, aad)
        # wrapped_dek 列存 wrap_nonce(12B)||wrapped_dek；nonce 列存 data nonce
        aad_hash = hashlib.sha256(aad).hexdigest()
        now = _utcnow_iso()
        try:
            self._conn().execute(
                "INSERT INTO model_secret_envelope_v1"
                " (secret_ref, version, tenant_id, algorithm, key_id,"
                "  wrapped_dek, nonce, ciphertext, aad_hash, status,"
                "  created_by, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (scope.secret_ref, version, scope.tenant_id, ALGORITHM,
                 self._key_id, wrap_nonce + wrapped_dek, nonce, ciphertext,
                 aad_hash, "active", actor, now))
        except sqlite3.IntegrityError as e:
            raise SecretStoreError("secret 版本冲突") from e
        return SecretMeta(
            secret_ref=scope.secret_ref, version=version,
            tenant_id=scope.tenant_id, status="active",
            algorithm=ALGORITHM, key_id=self._key_id, aad_hash=aad_hash,
            created_by=actor, created_at=now)

    # ------------------------------------------------------------------ API

    def put(self, scope: SecretScope, value: bytes,
            actor: str) -> SecretMeta:
        self._require_kek()
        if not isinstance(value, (bytes, bytearray)):
            raise SecretStoreError("secret value 必须是 bytes")
        if self._fetch(scope.secret_ref, status="active") is not None:
            raise SecretStoreError(
                "secret 已存在：新增凭据必须使用 rotate")
        version_row = self._conn().execute(
            "SELECT max(version) v FROM model_secret_envelope_v1"
            " WHERE secret_ref=?", (scope.secret_ref,)).fetchone()
        version = (version_row["v"] or 0) + 1
        return self._insert(scope=scope, value=bytes(value), actor=actor,
                            version=version)

    def rotate(self, scope: SecretScope, value: bytes,
               actor: str) -> SecretMeta:
        """轮换：新版本 active，旧 active 版本全部 rotated。

        签名取 ``SecretScope`` 而非裸 ref（对 02 §5 协议的最小强化）：
        新版本的 AAD 必须绑定 tenant/secret_ref/version/adapter_kind，
        裸 ref 无法安全重建 adapter_kind。运行时绝不回落旧版本。
        """
        self._require_kek()
        if not isinstance(value, (bytes, bytearray)):
            raise SecretStoreError("secret value 必须是 bytes")
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            active = conn.execute(
                "SELECT version FROM model_secret_envelope_v1"
                " WHERE secret_ref=? AND status='active' AND tenant_id=?",
                (scope.secret_ref, scope.tenant_id)).fetchall()
            if not active:
                raise SecretNotFoundError(
                    "secret 不存在或无 active 版本，无法轮换")
            now = _utcnow_iso()
            for row in active:
                conn.execute(
                    "UPDATE model_secret_envelope_v1 SET status='rotated',"
                    " rotated_at=? WHERE secret_ref=? AND version=?",
                    (now, scope.secret_ref, row["version"]))
            conn.execute("COMMIT")
        except SecretNotFoundError:
            conn.execute("ROLLBACK")
            raise
        except Exception:
            conn.execute("ROLLBACK")
            raise
        version_row = conn.execute(
            "SELECT max(version) v FROM model_secret_envelope_v1"
            " WHERE secret_ref=?", (scope.secret_ref,)).fetchone()
        version = (version_row["v"] or 0) + 1
        return self._insert(scope=scope, value=bytes(value), actor=actor,
                            version=version)

    def lease(self, ref: str, scope: SecretScope, *,
              ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS) -> SecretLease:
        self._require_kek()
        row = self._fetch(ref, status="active")
        if row is None:
            raise SecretNotFoundError("secret 不存在或不可见")
        value = self._decrypt_row(row, scope)
        return SecretLease(secret_ref=ref, version=row["version"],
                           value=value,
                           expires_at=time.time() + ttl_seconds)

    def lease_version(self, ref: str, version: int, scope: SecretScope, *,
                      ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS
                      ) -> SecretLease:
        self._require_kek()
        row = self._fetch(ref, version=version)
        if row is None:
            raise SecretNotFoundError("secret 版本不存在或不可见")
        if row["status"] != "active":
            raise SecretStoreError(
                f"secret 版本 {version} 非 active（{row['status']}）："
                "禁止回落到旧版本")
        value = self._decrypt_row(row, scope)
        return SecretLease(secret_ref=ref, version=row["version"],
                           value=value,
                           expires_at=time.time() + ttl_seconds)

    def revoke(self, ref: str, actor: str) -> None:
        self._require_kek()
        conn = self._conn()
        now = _utcnow_iso()
        cur = conn.execute(
            "UPDATE model_secret_envelope_v1 SET status='revoked',"
            " rotated_at=? WHERE secret_ref=? AND status != 'revoked'",
            (now, ref))
        if cur.rowcount == 0:
            raise SecretNotFoundError("secret 不存在或不可见")

    def metadata(self, ref: str) -> dict:
        """只返回安全元数据：绝不包含 wrapped_dek/nonce/ciphertext。"""
        row = self._fetch(ref)
        if row is None:
            raise SecretNotFoundError("secret 不存在或不可见")
        return {
            "secret_ref": row["secret_ref"],
            "version": row["version"],
            "tenant_id": row["tenant_id"],
            "algorithm": row["algorithm"],
            "key_id": row["key_id"],
            "aad_hash": row["aad_hash"],
            "status": row["status"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "rotated_at": row["rotated_at"],
        }

    def validate_lease(self, lease: SecretLease) -> None:
        if time.time() > lease.expires_at:
            raise SecretLeaseExpired("secret 租约已过期：必须重新 lease")
        row = self._fetch(lease.secret_ref, version=lease.version)
        if row is None or row["status"] != "active":
            raise SecretStoreError(
                "secret 租约对应的版本已非 active（可能已轮换/撤销）")
