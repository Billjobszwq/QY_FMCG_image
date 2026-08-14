"""M6：SQLite → PostgreSQL 一次性迁移（不双写）。

流程：
1. 读取 SQLite 平台库全部表（固定依赖顺序）；
2. PG 侧按列定义建表（通用类型映射：TEXT→TEXT、INTEGER→BIGINT、REAL→DOUBLE PRECISION）；
3. 单事务批量插入；
4. 逐表核对：行数 + 规范化行内容 sha256（同算法两侧计算），不一致即非零退出并回滚语义报错。

红线：
- 单次迁移，不做双写；生产切换前必须人工授权（本脚本只负责搬运与核对）；
- 不删除 SQLite 原库（保留为回滚锚点）。

用法：
    python3 scripts/migrate_sqlite_to_pg.py --sqlite .platform/platform.sqlite \\
        --pg-url postgresql://<user>:<password>@host:5432/platform [--drop-existing]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.platform.data.store import MIGRATIONS  # noqa: E402

# 依赖顺序（被引用表在前）
TABLE_ORDER = [
    "graph_run",
    "node_execution",
    "checkpoint",
    "job",
    "job_attempt",
    "audit_event",
    "usage_event",
    "evidence_bundle",
    "asset",
    "labeling_batch",
    "webhook_event",
    "dataset_snapshot",
    "training_run",
    "platform_flag",
    "share_token",
    "schema_migrations",
]

_PG_TYPE_MAP = {
    "TEXT": "TEXT",
    "INTEGER": "BIGINT",
    "REAL": "DOUBLE PRECISION",
    "BLOB": "BYTEA",
    "": "TEXT",
}


def canonical_rows_hash(columns: list[str], rows: list[tuple]) -> str:
    """规范化行集合哈希：每行→排序键 JSON，全表排序后 sha256（两侧同算法）。"""
    dumps = sorted(
        json.dumps(dict(zip(columns, row)), ensure_ascii=False, sort_keys=True, default=str)
        for row in rows
    )
    return hashlib.sha256("\n".join(dumps).encode("utf-8")).hexdigest()


def pg_type(sqlite_type: str) -> str:
    t = (sqlite_type or "").strip().upper()
    return _PG_TYPE_MAP.get(t, "TEXT")


def sqlite_columns(conn: sqlite3.Connection, table: str) -> list[dict]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [
        {"name": r[1], "type": r[2], "pk": bool(r[5])}
        for r in rows
    ]


def pg_create_table_sql(table: str, columns: list[dict]) -> str:
    parts = []
    pk_cols = [c["name"] for c in columns if c["pk"]]
    for c in columns:
        clause = f'"{c["name"]}" {pg_type(c["type"])}'
        if c["pk"] and len(pk_cols) == 1:
            clause += " PRIMARY KEY"
        parts.append(clause)
    if len(pk_cols) > 1:
        quoted = ", ".join(f'"{c}"' for c in pk_cols)
        parts.append(f"PRIMARY KEY ({quoted})")
    return f'CREATE TABLE "{table}" ({", ".join(parts)})'


def fetch_all_sqlite(conn: sqlite3.Connection, table: str) -> tuple[list[str], list[tuple]]:
    cols = [c["name"] for c in sqlite_columns(conn, table)]
    rows = conn.execute(f'SELECT {", ".join(cols)} FROM "{table}"').fetchall()
    return cols, [tuple(r) for r in rows]


def migrate(sqlite_path: Path, pg_url: str, *, drop_existing: bool = False) -> dict:
    try:
        import psycopg
    except ImportError as e:
        raise SystemExit(
            "缺少 psycopg（pip install psycopg[binary]）。"
            "PG 真实迁移需先安装依赖并获得生产迁移授权。"
        ) from e

    conn = sqlite3.connect(str(sqlite_path))
    existing = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    tables = [t for t in TABLE_ORDER if t in existing]

    report: list[dict] = []
    with psycopg.connect(pg_url, autocommit=False) as pg:
        with pg.cursor() as cur:
            for t in tables:
                cols, rows = fetch_all_sqlite(conn, t)
                if drop_existing:
                    cur.execute(f'DROP TABLE IF EXISTS "{t}"')
                cur.execute(pg_create_table_sql(t, sqlite_columns(conn, t)))
                if rows:
                    placeholders = ", ".join(["%s"] * len(cols))
                    col_sql = ", ".join(f'"{c}"' for c in cols)
                    cur.executemany(
                        f'INSERT INTO "{t}" ({col_sql}) VALUES ({placeholders})',
                        rows,
                    )
        pg.commit()
        # 核对：逐表行数 + 规范化哈希
        with pg.cursor() as cur:
            for t in tables:
                cols, rows = fetch_all_sqlite(conn, t)
                col_sql = ", ".join(f'"{c}"' for c in cols)
                cur.execute(f'SELECT {col_sql} FROM "{t}"')
                pg_rows = [tuple(r) for r in cur.fetchall()]
                h_sqlite = canonical_rows_hash(cols, rows)
                h_pg = canonical_rows_hash(cols, pg_rows)
                report.append(
                    {
                        "table": t,
                        "rows_sqlite": len(rows),
                        "rows_pg": len(pg_rows),
                        "sha_sqlite": h_sqlite,
                        "sha_pg": h_pg,
                        "match": len(rows) == len(pg_rows) and h_sqlite == h_pg,
                    }
                )
    conn.close()
    ok = all(r["match"] for r in report)
    return {"ok": ok, "tables": report, "migrations_source": [n for n, _ in MIGRATIONS]}


def main() -> int:
    ap = argparse.ArgumentParser(description="SQLite→PG 一次性迁移（计数+哈希核对）")
    ap.add_argument("--sqlite", default=str(REPO_ROOT / ".platform" / "platform.sqlite"))
    ap.add_argument(
        "--pg-url",
        required=True,
        help="postgresql://<user>:<password>@host:port/db",
    )
    ap.add_argument("--drop-existing", action="store_true", help="先删除同名表（演练库专用）")
    args = ap.parse_args()

    result = migrate(Path(args.sqlite), args.pg_url, drop_existing=args.drop_existing)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
