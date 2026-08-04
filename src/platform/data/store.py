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
from datetime import datetime, timezone
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

MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("001_platform_init", _M001),
    ("002_labeling_inbox", _M002),
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
    ) -> dict[str, Any]:
        now = _utcnow()
        try:
            self._conn.execute(
                "INSERT INTO job(job_id, kind, status, payload_json, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?)",
                (job_id, kind, "queued", json.dumps(payload or {}, ensure_ascii=False), now, now),
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
