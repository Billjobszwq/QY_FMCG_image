"""M6 TDD：PG 迁移脚本（纯函数部分本地验证；真实 PG 由 PLATFORM_TEST_PG_URL 门控）。

无 PG 环境时：规范化哈希/类型映射/建表 SQL 可离线断言；migrate() 真实运行
需设置 PLATFORM_TEST_PG_URL 且已安装 psycopg（生产迁移另需人工授权）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.migrate_sqlite_to_pg import (  # noqa: E402
    canonical_rows_hash,
    pg_create_table_sql,
    pg_type,
    sqlite_columns,
    migrate,
)
from src.platform.data.store import PlatformStore  # noqa: E402

PG_URL = os.environ.get("PLATFORM_TEST_PG_URL", "")


def test_canonical_hash_deterministic_and_order_insensitive() -> None:
    cols = ["a", "b"]
    rows1 = [(1, "x"), (2, "y")]
    rows2 = [(2, "y"), (1, "x")]
    assert canonical_rows_hash(cols, rows1) == canonical_rows_hash(cols, rows2)
    assert canonical_rows_hash(cols, rows1) != canonical_rows_hash(cols, [(1, "z")])


def test_pg_type_mapping() -> None:
    assert pg_type("TEXT") == "TEXT"
    assert pg_type("INTEGER") == "BIGINT"
    assert pg_type("REAL") == "DOUBLE PRECISION"
    assert pg_type("") == "TEXT"


def test_pg_create_table_sql_single_pk() -> None:
    cols = [
        {"name": "job_id", "type": "TEXT", "pk": True},
        {"name": "status", "type": "TEXT", "pk": False},
    ]
    sql = pg_create_table_sql("job", cols)
    assert '"job_id" TEXT PRIMARY KEY' in sql
    assert '"status" TEXT' in sql


def test_sqlite_columns_reads_platform_schema(tmp_path: Path) -> None:
    store = PlatformStore(tmp_path / "p.sqlite")
    cols = sqlite_columns(store._conn, "job")
    names = [c["name"] for c in cols]
    assert "job_id" in names and "lease_until" in names and "max_attempts" in names
    store.close()


@pytest.mark.skipif(not PG_URL, reason="未设置 PLATFORM_TEST_PG_URL（PG 门控测试）")
def test_migrate_sqlite_to_pg_real(tmp_path: Path) -> None:
    store = PlatformStore(tmp_path / "p.sqlite")
    store.create_job(job_id="j1", kind="platform.echo", payload={"n": 1})
    store.append_audit(actor="t", action="x", subject_type="job", subject_id="j1")
    store.close()
    result = migrate(tmp_path / "p.sqlite", PG_URL, drop_existing=True)
    assert result["ok"] is True
    for t in result["tables"]:
        assert t["match"] is True, t
