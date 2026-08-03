"""数据底座可复用层：本地 SQLite 实现，schema 读自 migrations/sqlite/001_schema.sql。

ISSUE-016：迁移已拆分 migrations/sqlite 与 migrations/postgres（PostgreSQL 方言独立维护，
Compose 首次初始化执行完整迁移）。
追加式表 annotation/auto_label/review_event 在 DB 层由触发器禁 update/delete（红线）；此处提供 app 层 API。
docker 通后可平替为 Postgres + pgvector + MinIO，下列 API 语义不变。"""
from __future__ import annotations

import json
import sqlite3
import time

from ..common import paths

DB = paths.PROJECT_ROOT / ".warehouse" / "db.sqlite"
SCHEMA = paths.PROJECT_ROOT / "migrations" / "sqlite" / "001_schema.sql"
TABLES = ["sku_catalog", "asset", "annotation", "auto_label", "review_event", "dataset_version", "model_version", "recognition_run", "model_bundle", "webhook_event", "audit_outbox"]


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    # ISSUE-007：WAL + busy timeout，避免并发审计写入静默失败
    c = sqlite3.connect(str(DB), timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=15000")
    return c


def migrate(conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    c = conn or connect()
    if SCHEMA.exists():
        c.executescript(SCHEMA.read_text(encoding="utf-8"))
    if own:
        c.commit()
        c.close()


def add_asset(conn, asset_id, sha256, kind, width=None, height=None, source=None, uri=None, bucket=None):
    conn.execute("INSERT OR REPLACE INTO asset VALUES(?,?,?,?,?,?,?,?,?)", (asset_id, sha256, kind, uri, bucket, width, height, source, time.time()))
    conn.commit()


def add_annotation(conn, asset_id, x, y, canonical_id, source, confidence=None, provenance=None, box=None):
    conn.execute(
        "INSERT INTO annotation(asset_id,x,y,box,canonical_id,source,confidence,provenance_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (asset_id, x, y, box, canonical_id, source, confidence, json.dumps(provenance or {}, ensure_ascii=False), time.time()),
    )
    conn.commit()


def add_auto_label(conn, asset_id, box, canonical_id, method, confidence, evidence=None, needs_review=False):
    conn.execute(
        "INSERT INTO auto_label(asset_id,box,canonical_id,method,confidence,evidence_json,needs_review,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (asset_id, json.dumps(box), canonical_id, method, confidence, json.dumps(evidence or {}, ensure_ascii=False), int(bool(needs_review)), time.time()),
    )
    conn.commit()


def add_review_event(conn, asset_id, reviewer, status, before=None, after=None):
    conn.execute(
        "INSERT INTO review_event(asset_id,reviewer,status,before_json,after_json,created_at) VALUES(?,?,?,?,?,?)",
        (asset_id, reviewer, status, json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False), time.time()),
    )
    conn.commit()


def counts(conn) -> dict:
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}
