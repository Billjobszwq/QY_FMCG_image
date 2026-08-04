"""PlatformStore — SQLite 开发适配器（M1–M3 专用，M6 一次性迁移 PostgreSQL）。

设计约束：
- 只暴露类型化方法；不存在任意 SQL / shell / 文件系统逃逸口。
- migration 只追加；已应用 migration 的 sha256 校验，防篡改。
- 时间戳 UTC ISO-8601。
- WAL + busy timeout，与旧 warehouse 同款并发策略（ISSUE-007 教训）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

RUN_STATUSES = ("pending", "running", "waiting_human", "completed", "failed", "cancelled")
NODE_STATUSES = ("pending", "running", "completed", "failed", "skipped")
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")


class StoreError(Exception):
    """PlatformStore 域错误（非法状态、缺失记录、重复主键、migration 篡改）。"""


_M001 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_run (
    run_id TEXT PRIMARY KEY,
    graph_name TEXT NOT NULL,
    graph_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','running','waiting_human','completed','failed','cancelled')),
    input_json TEXT NOT NULL DEFAULT '{}',
    output_json TEXT,
    error TEXT,
    request_id TEXT,
    idempotency_key TEXT UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS node_execution (
    execution_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES graph_run(run_id),
    node_name TEXT NOT NULL,
    seq INTEGER NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('pending','running','completed','failed','skipped')),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    output_json TEXT,
    error TEXT,
    UNIQUE (run_id, node_name, seq, attempt)
);

CREATE TABLE IF NOT EXISTS checkpoint (
    run_id TEXT NOT NULL REFERENCES graph_run(run_id),
    node_name TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, node_name)
);

CREATE TABLE IF NOT EXISTS job (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
    payload_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_attempt (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES job(job_id),
    attempt_no INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS audit_event (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_subject ON audit_event(subject_type, subject_id);

CREATE TABLE IF NOT EXISTS usage_event (
    usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    capability TEXT NOT NULL,
    run_id TEXT,
    quantity REAL NOT NULL,
    unit TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_usage_run ON usage_event(run_id);

CREATE TABLE IF NOT EXISTS evidence_bundle (
    evidence_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES graph_run(run_id),
    kind TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asset (
    asset_id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    kind TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    media_type TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (sha256, kind)
);
"""

_M002 = """
CREATE TABLE IF NOT EXISTS labeling_batch (
    batch_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    assisted_project_id INTEGER,
    blind_project_id INTEGER,
    task_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'created'
        CHECK (status IN ('created','imported','annotating','reconciled','closed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    event_id TEXT NOT NULL,
    action TEXT NOT NULL,
    project_id INTEGER,
    task_id INTEGER,
    payload_json TEXT NOT NULL,
    received_at TEXT NOT NULL,
    UNIQUE (source, event_id)
);
"""

_M003 = """
CREATE TABLE IF NOT EXISTS dataset_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    mode TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    guard_json TEXT NOT NULL,
    source_actor TEXT NOT NULL,
    source_conclusion TEXT NOT NULL,
    quality_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'registered'
        CHECK (status IN ('registered','rejected','superseded')),
    created_at TEXT NOT NULL,
    UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS training_run (
    run_id TEXT PRIMARY KEY,
    snapshot_id TEXT REFERENCES dataset_snapshot(snapshot_id),
    kind TEXT NOT NULL DEFAULT 'dry_run'
        CHECK (kind IN ('dry_run','authorized','started','completed_candidate','cancelled')),
    plan_json TEXT NOT NULL,
    command_json TEXT NOT NULL,
    budget_json TEXT NOT NULL,
    stop_lines_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'dry_run',
    publish_status TEXT NOT NULL DEFAULT 'none'
        CHECK (publish_status IN ('none','requested','approved','rejected','published')),
    requested_by TEXT,
    approved_by TEXT,
    publish_requested_by TEXT,
    publish_approved_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS platform_flag (
    flag TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL
);

INSERT OR IGNORE INTO platform_flag (flag, value, updated_at, updated_by)
VALUES ('training_authorized', 'false', '1970-01-01T00:00:00+00:00', 'system');
"""

_M004 = """
ALTER TABLE job ADD COLUMN lease_until TEXT;
ALTER TABLE job ADD COLUMN worker_id TEXT;
ALTER TABLE job ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE job ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 3;
CREATE INDEX IF NOT EXISTS idx_job_status ON job(status);

CREATE TABLE IF NOT EXISTS share_token (
    token TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    subject_id TEXT,
    expires_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);
"""

_M005 = """
ALTER TABLE dataset_snapshot ADD COLUMN trainable INTEGER NOT NULL DEFAULT 1;
ALTER TABLE dataset_snapshot ADD COLUMN status_note TEXT NOT NULL DEFAULT '';
"""

MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("001_platform_init", _M001),
    ("002_labeling_inbox", _M002),
    ("003_training_gov", _M003),
    ("004_recoverable_worker", _M004),
    ("005_snapshot_trainable", _M005),
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class PlatformStore:
    """SQLite 开发适配器。生产（M6）将一次性迁移到 PostgreSQL，不做双写。"""

    def __init__(self, db_path: Path | str) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        # 首连接设置 WAL（持久化于库文件）
        self._conn.execute("PRAGMA journal_mode=WAL")
        self.apply_migrations()

    def _make_conn(self) -> sqlite3.Connection:
        # autocommit 模式：避免隐式长读事务在 WAL 下阻塞其他连接的写者；
        # 写路径每条语句自提交（本库写操作均为单语句）。
        c = sqlite3.connect(str(self._path), timeout=15, autocommit=True)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=15000")
        c.execute("PRAGMA journal_mode=WAL")
        return c

    @property
    def _conn(self) -> sqlite3.Connection:
        """每线程独立连接（WAL 并发），避免跨线程共享 sqlite 对象。"""
        c = getattr(self._local, "conn", None)
        if c is None:
            c = self._make_conn()
            self._local.conn = c
        return c

    # ---------- migrations ----------

    def apply_migrations(self) -> None:
        conn = self._conn
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,"
            "sha256 TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        applied = {
            r["name"]: r["sha256"]
            for r in conn.execute("SELECT name, sha256 FROM schema_migrations").fetchall()
        }
        for name, sql in MIGRATIONS:
            digest = _sha(sql)
            if name in applied:
                if applied[name] != digest:
                    raise StoreError(
                        f"migration '{name}' 已被篡改（记录 sha256 与当前内容不一致），拒绝启动"
                    )
                continue
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations(name, sha256, applied_at) VALUES (?,?,?)",
                (name, digest, _utcnow()),
            )
        conn.commit()

    # ---------- graph_run ----------

    def create_run(
        self,
        *,
        run_id: str,
        graph_name: str,
        graph_version: str,
        input_payload: dict[str, Any] | None = None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        now = _utcnow()
        try:
            self._conn.execute(
                "INSERT INTO graph_run(run_id, graph_name, graph_version, status,"
                " input_json, request_id, idempotency_key, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    graph_name,
                    graph_version,
                    "pending",
                    json.dumps(input_payload or {}, ensure_ascii=False),
                    request_id,
                    idempotency_key,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise StoreError(f"run 已存在或 idempotency_key 冲突: {run_id}") from e
        self._conn.commit()
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM graph_run WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise StoreError(f"run 不存在: {run_id}")
        return dict(row)

    def list_runs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM graph_run ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def find_run_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM graph_run WHERE idempotency_key=?", (key,)
        ).fetchone()
        return _row_to_dict(row)

    def set_run_status(
        self,
        run_id: str,
        status: str,
        *,
        output_payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if status not in RUN_STATUSES:
            raise StoreError(f"非法 run 状态: {status}")
        cur = self._conn.execute(
            "UPDATE graph_run SET status=?, updated_at=?, error=?"
            + (", output_json=?" if output_payload is not None else "")
            + " WHERE run_id=?",
            (
                status,
                _utcnow(),
                error,
                *(
                    [json.dumps(output_payload, ensure_ascii=False)]
                    if output_payload is not None
                    else []
                ),
                run_id,
            ),
        )
        if cur.rowcount == 0:
            raise StoreError(f"run 不存在: {run_id}")
        self._conn.commit()

    # ---------- node_execution ----------

    def start_node(self, run_id: str, *, node_name: str, seq: int, attempt: int = 1) -> None:
        try:
            self._conn.execute(
                "INSERT INTO node_execution(run_id, node_name, seq, attempt, status, started_at)"
                " VALUES (?,?,?,?,?,?)",
                (run_id, node_name, seq, attempt, "running", _utcnow()),
            )
        except sqlite3.IntegrityError as e:
            raise StoreError(f"node 执行记录已存在: {run_id}/{node_name}/seq{seq}/a{attempt}") from e
        self._conn.commit()

    def finish_node(
        self,
        run_id: str,
        *,
        node_name: str,
        seq: int,
        status: str,
        attempt: int = 1,
        output_payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if status not in NODE_STATUSES:
            raise StoreError(f"非法 node 状态: {status}")
        cur = self._conn.execute(
            "UPDATE node_execution SET status=?, ended_at=?, output_json=?, error=?"
            " WHERE run_id=? AND node_name=? AND seq=? AND attempt=?",
            (
                status,
                _utcnow(),
                json.dumps(output_payload, ensure_ascii=False) if output_payload is not None else None,
                error,
                run_id,
                node_name,
                seq,
                attempt,
            ),
        )
        if cur.rowcount == 0:
            raise StoreError(f"node 执行记录不存在: {run_id}/{node_name}/seq{seq}/a{attempt}")
        self._conn.commit()

    def list_nodes(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM node_execution WHERE run_id=? ORDER BY seq, attempt",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- checkpoint ----------

    def save_checkpoint(self, run_id: str, *, node_name: str, payload: dict[str, Any]) -> None:
        try:
            self._conn.execute(
                "INSERT INTO checkpoint(run_id, node_name, payload_json, created_at)"
                " VALUES (?,?,?,?)"
                " ON CONFLICT(run_id, node_name) DO UPDATE SET"
                " payload_json=excluded.payload_json, created_at=excluded.created_at",
                (run_id, node_name, json.dumps(payload, ensure_ascii=False), _utcnow()),
            )
        except sqlite3.IntegrityError as e:
            raise StoreError(f"checkpoint 写入失败: {run_id}/{node_name}") from e
        self._conn.commit()

    def load_checkpoint(self, run_id: str, node_name: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT payload_json FROM checkpoint WHERE run_id=? AND node_name=?",
            (run_id, node_name),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload_json"])

    # ---------- job / attempt ----------

    def create_job(
        self,
        *,
        job_id: str,
        kind: str,
        payload: dict[str, Any] | None = None,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        now = _utcnow()
        try:
            self._conn.execute(
                "INSERT INTO job(job_id, kind, status, payload_json, max_attempts,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (
                    job_id, kind, "queued",
                    json.dumps(payload or {}, ensure_ascii=False),
                    max_attempts, now, now,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise StoreError(f"job 已存在: {job_id}") from e
        self._conn.commit()
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM job WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise StoreError(f"job 不存在: {job_id}")
        return dict(row)

    def set_job_status(
        self,
        job_id: str,
        status: str,
        *,
        result_payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if status not in JOB_STATUSES:
            raise StoreError(f"非法 job 状态: {status}")
        cur = self._conn.execute(
            "UPDATE job SET status=?, updated_at=?, error=?"
            + (", result_json=?" if result_payload is not None else "")
            + " WHERE job_id=?",
            (
                status,
                _utcnow(),
                error,
                *(
                    [json.dumps(result_payload, ensure_ascii=False)]
                    if result_payload is not None
                    else []
                ),
                job_id,
            ),
        )
        if cur.rowcount == 0:
            raise StoreError(f"job 不存在: {job_id}")
        self._conn.commit()

    def record_attempt(
        self,
        job_id: str,
        *,
        attempt_no: int,
        status: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO job_attempt(job_id, attempt_no, status, started_at, ended_at, detail_json)"
            " VALUES (?,?,?,?,?,?)",
            (job_id, attempt_no, status, _utcnow(), _utcnow(), json.dumps(detail or {}, ensure_ascii=False)),
        )
        self._conn.commit()

    def list_attempts(self, job_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM job_attempt WHERE job_id=? ORDER BY attempt_no", (job_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def claim_next_job(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        exclude_job_ids: set[str] | None = None,
    ) -> dict[str, Any] | None:
        """原子认领最老 queued job 为 running（单语句 UPDATE，崩溃可恢复）。

        lease_until 到期而 worker 未续期/完成 → 视为崩溃，可被重新排队。
        exclude_job_ids：本轮刚 requeue 的 job 不重复认领（退让语义）。
        """
        now = datetime.now(timezone.utc)
        lease = (now + timedelta(seconds=lease_seconds)).isoformat()
        excluded = sorted(exclude_job_ids or ())
        params: list[Any] = [worker_id, lease, now.isoformat()]
        excl_sql = ""
        if excluded:
            excl_sql = f" AND job_id NOT IN ({', '.join('?' * len(excluded))})"
            params.extend(excluded)
        params.extend(excluded)  # 子查询同名排除
        row = self._conn.execute(
            "UPDATE job SET status='running', worker_id=?, lease_until=?, updated_at=?"
            " WHERE job_id=(SELECT job_id FROM job WHERE status='queued'"
            f"{excl_sql} ORDER BY created_at, job_id LIMIT 1){excl_sql} RETURNING *",
            params,
        ).fetchone()
        self._conn.commit()
        return dict(row) if row is not None else None

    def increment_attempt(self, job_id: str) -> int:
        self._conn.execute(
            "UPDATE job SET attempt_count=attempt_count+1, updated_at=? WHERE job_id=?",
            (_utcnow(), job_id),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT attempt_count FROM job WHERE job_id=?", (job_id,)
        ).fetchone()
        if row is None:
            raise StoreError(f"job 不存在: {job_id}")
        return int(row["attempt_count"])

    def clear_lease(self, job_id: str) -> None:
        self._conn.execute(
            "UPDATE job SET lease_until=NULL, worker_id=NULL, updated_at=? WHERE job_id=?",
            (_utcnow(), job_id),
        )
        self._conn.commit()

    def list_jobs(
        self, *, status: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        if status is not None:
            rows = self._conn.execute(
                "SELECT * FROM job WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM job ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def count_jobs_by_status(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM job GROUP BY status"
        ).fetchall()
        out = {s: 0 for s in JOB_STATUSES}
        for r in rows:
            out[r["status"]] = int(r["n"])
        return out

    def expired_running_leases(self, *, before_ts: str) -> list[dict[str, Any]]:
        """lease 过期仍 running 的 job（worker 崩溃候选）。"""
        rows = self._conn.execute(
            "SELECT * FROM job WHERE status='running' AND lease_until IS NOT NULL"
            " AND lease_until < ?",
            (before_ts,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- share token（scope + 有效期，fail-closed） ----------

    def create_share_token(
        self,
        *,
        scope: str,
        subject_id: str | None = None,
        ttl_seconds: int,
        created_by: str,
        token: str | None = None,
    ) -> dict[str, Any]:
        import secrets

        tok = token or secrets.token_urlsafe(24)
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=ttl_seconds)).isoformat()
        self._conn.execute(
            "INSERT INTO share_token(token, scope, subject_id, expires_at,"
            " created_by, created_at, revoked) VALUES (?,?,?,?,?,?,0)",
            (tok, scope, subject_id, expires, created_by, now.isoformat()),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT * FROM share_token WHERE token=?", (tok,)
        ).fetchone()
        return dict(row)

    def validate_share_token(
        self, token: str, *, scope: str
    ) -> dict[str, Any] | None:
        """校验 token：存在 + 未吊销 + 未过期 + scope 匹配；任一不满足返回 None。"""
        row = self._conn.execute(
            "SELECT * FROM share_token WHERE token=?", (token,)
        ).fetchone()
        if row is None:
            return None
        r = dict(row)
        if r["revoked"]:
            return None
        if r["scope"] != scope:
            return None
        if r["expires_at"] <= _utcnow():
            return None
        return r

    def revoke_share_token(self, token: str) -> bool:
        cur = self._conn.execute(
            "UPDATE share_token SET revoked=1 WHERE token=?", (token,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def flag_orphaned_jobs(self, *, before_ts: str) -> list[str]:
        """将超时仍处于 running 的 job 标记为 failed（可恢复语义，M2 要求）。"""
        rows = self._conn.execute(
            "SELECT job_id FROM job WHERE status='running' AND updated_at < ?",
            (before_ts,),
        ).fetchall()
        ids = [r["job_id"] for r in rows]
        for jid in ids:
            self._conn.execute(
                "UPDATE job SET status='failed', error='orphaned', updated_at=? WHERE job_id=?",
                (_utcnow(), jid),
            )
        if ids:
            self._conn.commit()
        return ids

    # ---------- audit / usage ----------

    def append_audit(
        self,
        *,
        actor: str,
        action: str,
        subject_type: str,
        subject_id: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO audit_event(ts, actor, action, subject_type, subject_id, detail_json)"
            " VALUES (?,?,?,?,?,?)",
            (_utcnow(), actor, action, subject_type, subject_id, json.dumps(detail or {}, ensure_ascii=False)),
        )
        self._conn.commit()

    def list_audit(self, *, subject_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if subject_id is not None:
            rows = self._conn.execute(
                "SELECT * FROM audit_event WHERE subject_id=? ORDER BY audit_id LIMIT ?",
                (subject_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM audit_event ORDER BY audit_id LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def append_usage(
        self,
        *,
        capability: str,
        run_id: str | None,
        quantity: float,
        unit: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO usage_event(ts, capability, run_id, quantity, unit, detail_json)"
            " VALUES (?,?,?,?,?,?)",
            (_utcnow(), capability, run_id, quantity, unit, json.dumps(detail or {}, ensure_ascii=False)),
        )
        self._conn.commit()

    def list_usage(self, *, run_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if run_id is not None:
            rows = self._conn.execute(
                "SELECT * FROM usage_event WHERE run_id=? ORDER BY usage_id LIMIT ?",
                (run_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM usage_event ORDER BY usage_id LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------- evidence / asset ----------

    def create_evidence_bundle(
        self,
        *,
        evidence_id: str,
        run_id: str,
        kind: str,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            self._conn.execute(
                "INSERT INTO evidence_bundle(evidence_id, run_id, kind, manifest_json, created_at)"
                " VALUES (?,?,?,?,?)",
                (evidence_id, run_id, kind, json.dumps(manifest, ensure_ascii=False), _utcnow()),
            )
        except sqlite3.IntegrityError as e:
            raise StoreError(f"evidence 已存在或 run 缺失: {evidence_id}") from e
        self._conn.commit()
        return self.get_evidence(evidence_id)

    def get_evidence(self, evidence_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM evidence_bundle WHERE evidence_id=?", (evidence_id,)
        ).fetchone()
        if row is None:
            raise StoreError(f"evidence 不存在: {evidence_id}")
        return dict(row)

    def list_evidence(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM evidence_bundle WHERE run_id=? ORDER BY created_at", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- labeling batch / webhook inbox (M4) ----------

    def create_labeling_batch(
        self,
        *,
        batch_id: str,
        name: str,
        assisted_project_id: int | None,
        blind_project_id: int | None,
        task_count: int = 0,
    ) -> dict[str, Any]:
        now = _utcnow()
        try:
            self._conn.execute(
                "INSERT INTO labeling_batch(batch_id, name, assisted_project_id,"
                " blind_project_id, task_count, status, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (batch_id, name, assisted_project_id, blind_project_id,
                 task_count, "created", now, now),
            )
        except sqlite3.IntegrityError as e:
            raise StoreError(f"labeling batch 已存在: {batch_id}") from e
        self._conn.commit()
        return self.get_labeling_batch(batch_id)

    def get_labeling_batch(self, batch_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM labeling_batch WHERE batch_id=?", (batch_id,)
        ).fetchone()
        if row is None:
            raise StoreError(f"labeling batch 不存在: {batch_id}")
        return dict(row)

    def list_labeling_batches(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM labeling_batch ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    _BATCH_FIELDS = {"name", "assisted_project_id", "blind_project_id", "task_count", "status"}

    def update_labeling_batch(self, batch_id: str, **fields: Any) -> dict[str, Any]:
        unknown = set(fields) - self._BATCH_FIELDS
        if unknown:
            raise StoreError(f"未知 labeling batch 字段: {sorted(unknown)}")
        if not fields:
            return self.get_labeling_batch(batch_id)
        sets = ", ".join(f"{k}=?" for k in fields)
        cur = self._conn.execute(
            f"UPDATE labeling_batch SET {sets}, updated_at=? WHERE batch_id=?",
            (*fields.values(), _utcnow(), batch_id),
        )
        if cur.rowcount == 0:
            raise StoreError(f"labeling batch 不存在: {batch_id}")
        self._conn.commit()
        return self.get_labeling_batch(batch_id)

    def record_webhook_event(
        self,
        *,
        source: str,
        event_id: str,
        action: str,
        project_id: int | None = None,
        task_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """幂等收件箱：(source, event_id) 重复时返回 False，不重复写入。"""
        try:
            self._conn.execute(
                "INSERT INTO webhook_event(source, event_id, action, project_id,"
                " task_id, payload_json, received_at) VALUES (?,?,?,?,?,?,?)",
                (source, event_id, action, project_id, task_id,
                 json.dumps(payload or {}, ensure_ascii=False), _utcnow()),
            )
        except sqlite3.IntegrityError:
            return False
        self._conn.commit()
        return True

    def list_webhook_events(
        self, *, source: str | None = None, project_id: int | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM webhook_event"
        cond: list[str] = []
        args: list[Any] = []
        if source is not None:
            cond.append("source=?")
            args.append(source)
        if project_id is not None:
            cond.append("project_id=?")
            args.append(project_id)
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY id"
        return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    # ---------- dataset snapshot / training gov (M5) ----------

    def create_dataset_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        self._conn.execute(
            """INSERT INTO dataset_snapshot (snapshot_id, name, version, mode,
               manifest_hash, manifest_json, guard_json, source_actor,
               source_conclusion, quality_json, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (snapshot["snapshot_id"], snapshot["name"], snapshot["version"],
             snapshot["mode"], snapshot["manifest_hash"], snapshot["manifest_json"],
             snapshot["guard_json"], snapshot["source_actor"],
             snapshot["source_conclusion"], snapshot.get("quality_json", "{}"),
             snapshot.get("status", "registered"), snapshot["created_at"]),
        )
        return snapshot

    def get_dataset_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        return _row_to_dict(self._conn.execute(
            "SELECT * FROM dataset_snapshot WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone())

    def list_dataset_snapshots(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM dataset_snapshot ORDER BY created_at DESC").fetchall()]

    def mark_dataset_snapshot_trainable(
        self, snapshot_id: str, *, trainable: int, note: str
    ) -> dict[str, Any] | None:
        """审计式标记（U0-2/UMT-004）：不删除行，仅改可训练标志与备注。"""
        self._conn.execute(
            "UPDATE dataset_snapshot SET trainable=?, status_note=?"
            " WHERE snapshot_id=?",
            (1 if trainable else 0, note, snapshot_id),
        )
        self._conn.commit()
        return self.get_dataset_snapshot(snapshot_id)

    def create_training_run(self, run: dict[str, Any]) -> dict[str, Any]:
        self._conn.execute(
            """INSERT INTO training_run (run_id, snapshot_id, kind, plan_json,
               command_json, budget_json, stop_lines_json, status, publish_status,
               requested_by, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run["run_id"], run.get("snapshot_id"), run.get("kind", "dry_run"),
             run["plan_json"], run["command_json"], run["budget_json"],
             run["stop_lines_json"], run.get("status", "dry_run"),
             run.get("publish_status", "none"), run.get("requested_by"),
             run["created_at"], run["updated_at"]),
        )
        return run

    def get_training_run(self, run_id: str) -> dict[str, Any] | None:
        return _row_to_dict(self._conn.execute(
            "SELECT * FROM training_run WHERE run_id=?", (run_id,)).fetchone())

    def list_training_runs(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM training_run ORDER BY created_at DESC").fetchall()]

    _TRAINING_RUN_FIELDS = (
        "kind", "status", "publish_status", "approved_by", "requested_by",
        "publish_requested_by", "publish_approved_by", "plan_json",
    )

    def update_training_run(self, run_id: str, **fields: Any) -> dict[str, Any]:
        bad = set(fields) - set(self._TRAINING_RUN_FIELDS)
        if bad:
            raise ValueError(f"不允许的字段: {sorted(bad)}")
        if not fields:
            raise ValueError("无更新字段")
        fields["updated_at"] = _utcnow()
        sets = ", ".join(f"{k}=?" for k in fields)
        self._conn.execute(
            f"UPDATE training_run SET {sets} WHERE run_id=?",
            (*fields.values(), run_id),
        )
        got = self.get_training_run(run_id)
        if got is None:
            raise KeyError(run_id)
        return got

    def get_flag(self, flag: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM platform_flag WHERE flag=?", (flag,)).fetchone()
        return row["value"] if row else None

    def set_flag(self, flag: str, value: str, actor: str) -> None:
        self._conn.execute(
            """INSERT INTO platform_flag (flag, value, updated_at, updated_by)
               VALUES (?,?,?,?) ON CONFLICT(flag) DO UPDATE SET
               value=excluded.value, updated_at=excluded.updated_at,
               updated_by=excluded.updated_by""",
            (flag, value, _utcnow(), actor),
        )

    # ---------- backup ----------

    def backup(self, dest: Path | str) -> dict[str, Any]:
        """使用 sqlite3 backup API 生成一致性备份，并对备份做 integrity_check。"""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(dest))
        try:
            self._conn.backup(target)
            ok = target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            target.close()
        return {"ok": bool(ok), "path": str(dest), "created_at": _utcnow()}

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None
