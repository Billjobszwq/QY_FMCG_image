"""统一模型管理：typed repositories（M4/G3）。

纪律：
- Repository 只返回 typed rows；状态迁移与审批在 service 层；
- 所有状态更新走条件 UPDATE（CAS：status + etag），rowcount=0 → 冲突；
- 查询永远 WHERE tenant_id=?（scope-first，跨租户零泄漏的基础）。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

_BINDING_SCOPE_KEY = ("tenant_id", "customer_id", "project_id",
                      "subject_kind", "subject_id", "capability")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_etag(*parts) -> str:
    payload = json.dumps(list(parts), sort_keys=True, ensure_ascii=False,
                         default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class ConnectionVersionRow:
    connection_id: str
    version: int
    tenant_id: str
    name: str
    location: str
    adapter_kind: str
    api_flavor: str
    base_url: str
    secret_ref: str
    timeout_ms: int
    max_retries: int
    config_json: str
    status: str
    etag: str
    approval_id: str | None
    created_by: str
    created_at: str
    activated_at: str | None


@dataclass(frozen=True)
class CatalogEntryRow:
    catalog_id: str
    tenant_id: str
    connection_id: str
    connection_version: int
    model_id: str
    model_revision: str
    capabilities_json: str
    embedding_dimension: int | None
    normalization_version: str | None
    source: str
    probe_status: str
    probe_json: str
    last_verified_at: str | None


@dataclass(frozen=True)
class BindingVersionRow:
    binding_id: str
    version: int
    tenant_id: str
    customer_id: str
    project_id: str
    subject_kind: str
    subject_id: str
    capability: str
    connection_id: str
    connection_version: int
    model_id: str
    fallback_json: str
    status: str
    etag: str
    approval_id: str | None
    created_by: str
    created_at: str
    activated_at: str | None


class ModelRepository:
    """Connection/Catalog/Binding 持久化（typed；禁止服务层直连 _conn）。"""

    def __init__(self, store) -> None:
        self._store = store

    @property
    def _conn(self) -> sqlite3.Connection:
        return self._store._conn

    # ---------------------------------------------------------- connections

    def insert_connection(self, row: ConnectionVersionRow) -> None:
        try:
            self._conn.execute(
                "INSERT INTO model_connection_version_v1"
                " (connection_id, version, tenant_id, name, location,"
                "  adapter_kind, api_flavor, base_url, secret_ref,"
                "  timeout_ms, max_retries, config_json, status, etag,"
                "  approval_id, created_by, created_at, activated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row.connection_id, row.version, row.tenant_id, row.name,
                 row.location, row.adapter_kind, row.api_flavor,
                 row.base_url, row.secret_ref, row.timeout_ms,
                 row.max_retries, row.config_json, row.status, row.etag,
                 row.approval_id, row.created_by, row.created_at,
                 row.activated_at))
        except sqlite3.IntegrityError as e:
            raise ValueError(f"connection 版本冲突: {row.connection_id}"
                             f"@v{row.version}") from e

    def get_connection(self, *, tenant_id: str, connection_id: str,
                       version: int) -> ConnectionVersionRow | None:
        r = self._conn.execute(
            "SELECT * FROM model_connection_version_v1"
            " WHERE tenant_id=? AND connection_id=? AND version=?",
            (tenant_id, connection_id, version)).fetchone()
        return _to_connection(r)

    def latest_connection_version(self, *, tenant_id: str,
                                  connection_id: str) -> int:
        r = self._conn.execute(
            "SELECT max(version) v FROM model_connection_version_v1"
            " WHERE tenant_id=? AND connection_id=?",
            (tenant_id, connection_id)).fetchone()
        return int(r["v"] or 0)

    def list_connections(self, *, tenant_id: str
                         ) -> list[ConnectionVersionRow]:
        rows = self._conn.execute(
            "SELECT * FROM model_connection_version_v1 WHERE tenant_id=?"
            " ORDER BY connection_id, version", (tenant_id,)).fetchall()
        return [_to_connection(r) for r in rows]

    def connection_ids(self, *, tenant_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT connection_id FROM"
            " model_connection_version_v1 WHERE tenant_id=?"
            " ORDER BY connection_id", (tenant_id,)).fetchall()
        return [r[0] for r in rows]

    def set_connection_secret_ref(self, *, tenant_id: str,
                                  connection_id: str, version: int,
                                  secret_ref: str, expected_etag: str
                                  ) -> str:
        new_etag = compute_etag("secret", connection_id, version,
                                secret_ref, _utcnow_iso())
        rc = self._conn.execute(
            "UPDATE model_connection_version_v1 SET secret_ref=?,"
            " etag=? WHERE tenant_id=? AND connection_id=? AND"
            " version=? AND etag=? AND status IN"
            " ('draft','testing','ready')",
            (secret_ref, new_etag, tenant_id, connection_id, version,
             expected_etag)).rowcount
        if rc == 0:
            raise LookupError("connection 不存在/状态不允许/etag 冲突")
        return new_etag

    def cas_connection_status(self, *, tenant_id: str, connection_id: str,
                              version: int, from_status: str | tuple,
                              to_status: str, expected_etag: str,
                              approval_id: str | None = None,
                              activated_at: str | None = None) -> str:
        """条件状态迁移（CAS：status+etag）；返回新 etag。"""
        new_etag = compute_etag("conn-status", connection_id, version,
                                to_status, _utcnow_iso())
        statuses = (from_status,) if isinstance(from_status, str) \
            else tuple(from_status)
        marks = ",".join("?" for _ in statuses)
        sql = ("UPDATE model_connection_version_v1 SET status=?, etag=?"
               + (", approval_id=?" if approval_id is not None else "")
               + (", activated_at=?" if activated_at is not None else "")
               + " WHERE tenant_id=? AND connection_id=? AND version=?"
               f" AND etag=? AND status IN ({marks})")
        args: list = [to_status, new_etag]
        if approval_id is not None:
            args.append(approval_id)
        if activated_at is not None:
            args.append(activated_at)
        args += [tenant_id, connection_id, version, expected_etag, *statuses]
        rc = self._conn.execute(sql, args).rowcount
        if rc == 0:
            raise LookupError("CAS 冲突：状态/版本已变化")
        return new_etag

    def supersede_other_active_connections(self, *, tenant_id: str,
                                           connection_id: str,
                                           keep_version: int) -> int:
        cur = self._conn.execute(
            "UPDATE model_connection_version_v1 SET status='superseded'"
            " WHERE tenant_id=? AND connection_id=? AND status='active'"
            " AND version != ?", (tenant_id, connection_id, keep_version))
        return cur.rowcount

    # -------------------------------------------------------------- catalog

    def upsert_catalog(self, row: CatalogEntryRow) -> None:
        self._conn.execute(
            "INSERT INTO model_catalog_entry_v1"
            " (catalog_id, tenant_id, connection_id, connection_version,"
            "  model_id, model_revision, capabilities_json,"
            "  embedding_dimension, normalization_version, source,"
            "  probe_status, probe_json, last_verified_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(tenant_id, connection_id, connection_version,"
            " model_id) DO UPDATE SET"
            "  capabilities_json=excluded.capabilities_json,"
            "  embedding_dimension=excluded.embedding_dimension,"
            "  normalization_version=excluded.normalization_version,"
            "  source=excluded.source,"
            "  last_verified_at=excluded.last_verified_at",
            (row.catalog_id, row.tenant_id, row.connection_id,
             row.connection_version, row.model_id, row.model_revision,
             row.capabilities_json, row.embedding_dimension,
             row.normalization_version, row.source, row.probe_status,
             row.probe_json, row.last_verified_at))

    def get_catalog(self, *, tenant_id: str, catalog_id: str
                    ) -> CatalogEntryRow | None:
        r = self._conn.execute(
            "SELECT * FROM model_catalog_entry_v1"
            " WHERE tenant_id=? AND catalog_id=?",
            (tenant_id, catalog_id)).fetchone()
        return _to_catalog(r)

    def find_catalog_model(self, *, tenant_id: str, connection_id: str,
                           connection_version: int, model_id: str
                           ) -> CatalogEntryRow | None:
        r = self._conn.execute(
            "SELECT * FROM model_catalog_entry_v1 WHERE tenant_id=?"
            " AND connection_id=? AND connection_version=? AND model_id=?",
            (tenant_id, connection_id, connection_version,
             model_id)).fetchone()
        return _to_catalog(r)

    def list_catalog(self, *, tenant_id: str,
                     connection_id: str | None = None
                     ) -> list[CatalogEntryRow]:
        sql = ("SELECT * FROM model_catalog_entry_v1 WHERE tenant_id=?")
        args: list = [tenant_id]
        if connection_id is not None:
            sql += " AND connection_id=?"
            args.append(connection_id)
        sql += " ORDER BY connection_id, model_id"
        return [_to_catalog(r) for r in self._conn.execute(sql, args)]

    def update_catalog_probe(self, *, tenant_id: str, catalog_id: str,
                             probe_status: str, probe_json: str,
                             embedding_dimension: int | None = None,
                             ) -> bool:
        rc = self._conn.execute(
            "UPDATE model_catalog_entry_v1 SET probe_status=?,"
            " probe_json=?, last_verified_at=?,"
            " embedding_dimension=COALESCE(?, embedding_dimension)"
            " WHERE tenant_id=? AND catalog_id=?",
            (probe_status, probe_json, _utcnow_iso(), embedding_dimension,
             tenant_id, catalog_id)).rowcount
        return rc > 0

    # ------------------------------------------------------------- bindings

    def insert_binding(self, row: BindingVersionRow) -> None:
        try:
            self._conn.execute(
                "INSERT INTO model_binding_version_v1"
                " (binding_id, version, tenant_id, customer_id, project_id,"
                "  subject_kind, subject_id, capability, connection_id,"
                "  connection_version, model_id, fallback_json, status,"
                "  etag, approval_id, created_by, created_at, activated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (row.binding_id, row.version, row.tenant_id,
                 row.customer_id, row.project_id, row.subject_kind,
                 row.subject_id, row.capability, row.connection_id,
                 row.connection_version, row.model_id, row.fallback_json,
                 row.status, row.etag, row.approval_id, row.created_by,
                 row.created_at, row.activated_at))
        except sqlite3.IntegrityError as e:
            raise ValueError(
                f"binding 版本冲突: {row.binding_id}@v{row.version}") from e

    def get_binding(self, *, tenant_id: str, binding_id: str,
                    version: int) -> BindingVersionRow | None:
        r = self._conn.execute(
            "SELECT * FROM model_binding_version_v1"
            " WHERE tenant_id=? AND binding_id=? AND version=?",
            (tenant_id, binding_id, version)).fetchone()
        return _to_binding(r)

    def latest_binding_version(self, *, tenant_id: str,
                               binding_id: str) -> int:
        r = self._conn.execute(
            "SELECT max(version) v FROM model_binding_version_v1"
            " WHERE tenant_id=? AND binding_id=?",
            (tenant_id, binding_id)).fetchone()
        return int(r["v"] or 0)

    def list_bindings(self, *, tenant_id: str, customer_id: str | None = None,
                      subject_kind: str | None = None,
                      capability: str | None = None,
                      status: str | None = None) -> list[BindingVersionRow]:
        sql = "SELECT * FROM model_binding_version_v1 WHERE tenant_id=?"
        args: list = [tenant_id]
        if customer_id is not None:
            sql += " AND customer_id=?"
            args.append(customer_id)
        if subject_kind is not None:
            sql += " AND subject_kind=?"
            args.append(subject_kind)
        if capability is not None:
            sql += " AND capability=?"
            args.append(capability)
        if status is not None:
            sql += " AND status=?"
            args.append(status)
        sql += " ORDER BY binding_id, version"
        return [_to_binding(r) for r in self._conn.execute(sql, args)]

    def candidate_bindings(self, *, tenant_id: str) -> list[BindingVersionRow]:
        """Resolver 候选：只看 active/canary（scope-first：tenant 先行）。"""
        rows = self._conn.execute(
            "SELECT * FROM model_binding_version_v1 WHERE tenant_id=?"
            " AND status IN ('active','canary')"
            " ORDER BY binding_id, version", (tenant_id,)).fetchall()
        return [_to_binding(r) for r in rows]

    def set_binding_approval(self, *, tenant_id: str, binding_id: str,
                             version: int, approval_id: str,
                             expected_etag: str) -> str:
        """checker 批准后记录 approval（状态保持 pending_approval，
        等待 canary/active CAS）。"""
        new_etag = compute_etag("binding-approval", binding_id, version,
                                approval_id, _utcnow_iso())
        rc = self._conn.execute(
            "UPDATE model_binding_version_v1 SET approval_id=?, etag=?"
            " WHERE tenant_id=? AND binding_id=? AND version=? AND"
            " etag=? AND status='pending_approval'",
            (approval_id, new_etag, tenant_id, binding_id, version,
             expected_etag)).rowcount
        if rc == 0:
            raise LookupError("CAS 冲突：状态/版本已变化")
        return new_etag

    def cas_binding_status(self, *, tenant_id: str, binding_id: str,
                           version: int, from_status: str | tuple,
                           to_status: str, expected_etag: str,
                           approval_id: str | None = None,
                           activated_at: str | None = None) -> str:
        new_etag = compute_etag("binding-status", binding_id, version,
                                to_status, _utcnow_iso())
        statuses = (from_status,) if isinstance(from_status, str) \
            else tuple(from_status)
        marks = ",".join("?" for _ in statuses)
        sql = ("UPDATE model_binding_version_v1 SET status=?, etag=?"
               + (", approval_id=?" if approval_id is not None else "")
               + (", activated_at=?" if activated_at is not None else "")
               + " WHERE tenant_id=? AND binding_id=? AND version=?"
               f" AND etag=? AND status IN ({marks})")
        args = [to_status, new_etag]
        if approval_id is not None:
            args.append(approval_id)
        if activated_at is not None:
            args.append(activated_at)
        args += [tenant_id, binding_id, version, expected_etag, *statuses]
        rc = self._conn.execute(sql, args).rowcount
        if rc == 0:
            raise LookupError("CAS 冲突：状态/版本已变化")
        return new_etag

    def supersede_other_active_bindings(self, *, tenant_id: str,
                                        scope_key: dict,
                                        keep_binding_id: str,
                                        keep_version: int) -> int:
        """同 scope key 的其它 active 版本降级为 superseded（单事务内）。"""
        cur = self._conn.execute(
            "UPDATE model_binding_version_v1 SET status='superseded'"
            " WHERE tenant_id=? AND customer_id=? AND project_id=?"
            " AND subject_kind=? AND subject_id=? AND capability=?"
            " AND status='active'"
            " AND NOT (binding_id=? AND version=?)",
            (tenant_id, scope_key["customer_id"], scope_key["project_id"],
             scope_key["subject_kind"], scope_key["subject_id"],
             scope_key["capability"], keep_binding_id, keep_version))
        return cur.rowcount


def _to_connection(r: sqlite3.Row | None) -> ConnectionVersionRow | None:
    if r is None:
        return None
    return ConnectionVersionRow(
        connection_id=r["connection_id"], version=r["version"],
        tenant_id=r["tenant_id"], name=r["name"], location=r["location"],
        adapter_kind=r["adapter_kind"], api_flavor=r["api_flavor"],
        base_url=r["base_url"], secret_ref=r["secret_ref"],
        timeout_ms=r["timeout_ms"], max_retries=r["max_retries"],
        config_json=r["config_json"], status=r["status"], etag=r["etag"],
        approval_id=r["approval_id"], created_by=r["created_by"],
        created_at=r["created_at"], activated_at=r["activated_at"])


def _to_catalog(r: sqlite3.Row | None) -> CatalogEntryRow | None:
    if r is None:
        return None
    return CatalogEntryRow(
        catalog_id=r["catalog_id"], tenant_id=r["tenant_id"],
        connection_id=r["connection_id"],
        connection_version=r["connection_version"], model_id=r["model_id"],
        model_revision=r["model_revision"],
        capabilities_json=r["capabilities_json"],
        embedding_dimension=r["embedding_dimension"],
        normalization_version=r["normalization_version"],
        source=r["source"], probe_status=r["probe_status"],
        probe_json=r["probe_json"], last_verified_at=r["last_verified_at"])


def _to_binding(r: sqlite3.Row | None) -> BindingVersionRow | None:
    if r is None:
        return None
    return BindingVersionRow(
        binding_id=r["binding_id"], version=r["version"],
        tenant_id=r["tenant_id"], customer_id=r["customer_id"],
        project_id=r["project_id"], subject_kind=r["subject_kind"],
        subject_id=r["subject_id"], capability=r["capability"],
        connection_id=r["connection_id"],
        connection_version=r["connection_version"], model_id=r["model_id"],
        fallback_json=r["fallback_json"], status=r["status"],
        etag=r["etag"], approval_id=r["approval_id"],
        created_by=r["created_by"], created_at=r["created_at"],
        activated_at=r["activated_at"])
