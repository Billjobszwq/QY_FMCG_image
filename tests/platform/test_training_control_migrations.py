"""GLTC-001 红测试：training_control 追加式迁移（migration 021）。

要求：只追加新表，不改写旧 training_run/job/dataset_snapshot 历史；
事件与 artifact lineage 表有禁删改触发器；租约有释放语义。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.platform.data.store import PlatformStore


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _tables(store) -> set[str]:
    rows = store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


def test_migration_adds_v2_tables(store):
    t = _tables(store)
    for name in ("training_plan_v2", "training_run_v2", "training_event_v1",
                 "training_artifact_v1", "resource_lease_v1"):
        assert name in t, f"缺表 {name}"


def test_old_tables_untouched(store):
    """历史表保持原样（列数不变，数据语义不改）。"""
    t = _tables(store)
    for name in ("training_run", "job", "dataset_snapshot"):
        assert name in t
    cols = {r["name"] for r in store._conn.execute(
        "PRAGMA table_info(training_run)").fetchall()}
    assert "run_id" in cols and "command_json" in cols


def test_event_rows_immutable(store):
    store._conn.execute(
        "INSERT INTO training_run_v2 (run_id, plan_id, lane, status)"
        " VALUES ('r1','p1','detector','DRAFT')")
    store._conn.execute(
        "INSERT INTO training_event_v1 (run_id, seq, kind, payload_json,"
        " created_at) VALUES ('r1',1,'started','{}','t')")
    store._conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("DELETE FROM training_event_v1")
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute(
            "UPDATE training_event_v1 SET kind='x'")
    store._conn.rollback()


def test_artifact_rows_immutable(store):
    store._conn.execute(
        "INSERT INTO training_artifact_v1 (run_id, lane, artifact_type,"
        " path, sha256, lineage_json, created_at)"
        " VALUES ('r1','detector','checkpoint','/x','ab','{}','t')")
    store._conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("DELETE FROM training_artifact_v1")
    store._conn.rollback()


def test_lease_lifecycle(store):
    store.acquire_resource_lease(run_id="r1", resource="mps",
                                 mode="exclusive")
    # heavy 并发 1：第二个 heavy 租约被拒
    with pytest.raises(Exception):
        store.acquire_resource_lease(run_id="r2", resource="mps",
                                     mode="exclusive")
    # mps/mlx 互斥
    with pytest.raises(Exception):
        store.acquire_resource_lease(run_id="r1", resource="mlx",
                                     mode="exclusive")
    store.release_resource_lease(run_id="r1", resource="mps")
    store.acquire_resource_lease(run_id="r2", resource="mps",
                                 mode="exclusive")
    active = store.list_active_leases()
    assert [l["run_id"] for l in active] == ["r2"]
