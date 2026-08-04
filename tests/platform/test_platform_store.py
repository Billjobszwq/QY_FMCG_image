"""W5 PlatformStore（SQLite 开发适配器）TDD 测试。

覆盖：migration 幂等与防篡改、Run/Node/Checkpoint/Job/Attempt/Audit/Usage/Evidence
持久化、状态校验、备份与完整性校验、重启后可恢复。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.platform.data.store import PlatformStore, StoreError


@pytest.fixture()
def store(tmp_path: Path) -> PlatformStore:
    s = PlatformStore(tmp_path / "platform.sqlite")
    yield s
    s.close()


# ---------- migrations ----------

def test_migrations_applied_once(store: PlatformStore) -> None:
    rows = store._conn.execute("SELECT name FROM schema_migrations").fetchall()
    assert len(rows) >= 1
    before = len(rows)
    store.apply_migrations()  # 重复执行幂等
    after = store._conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    assert after == before


def test_migration_tamper_detection(tmp_path: Path) -> None:
    s = PlatformStore(tmp_path / "platform.sqlite")
    # 篡改已应用 migration 的内容 → 重新打开时必须拒绝
    s._conn.execute("UPDATE schema_migrations SET sha256='deadbeef'")
    s._conn.commit()
    with pytest.raises(StoreError):
        s.apply_migrations()
    s.close()


def test_tables_exist(store: PlatformStore) -> None:
    names = {
        r[0]
        for r in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for t in (
        "graph_run",
        "node_execution",
        "checkpoint",
        "job",
        "job_attempt",
        "audit_event",
        "usage_event",
        "evidence_bundle",
        "asset",
    ):
        assert t in names, t


# ---------- graph_run ----------

def test_run_lifecycle(store: PlatformStore) -> None:
    run = store.create_run(
        run_id="run-1",
        graph_name="system_health_v1",
        graph_version="1",
        input_payload={"probe": True},
        request_id="req-1",
        idempotency_key="idem-1",
    )
    assert run["status"] == "pending"
    store.set_run_status("run-1", "running")
    store.set_run_status("run-1", "completed", output_payload={"ok": True})
    got = store.get_run("run-1")
    assert got["status"] == "completed"
    assert json.loads(got["output_json"]) == {"ok": True}
    assert got["idempotency_key"] == "idem-1"


def test_run_invalid_status_rejected(store: PlatformStore) -> None:
    store.create_run(run_id="run-x", graph_name="g", graph_version="1")
    with pytest.raises(StoreError):
        store.set_run_status("run-x", "exploded")


def test_run_missing_raises(store: PlatformStore) -> None:
    with pytest.raises(StoreError):
        store.get_run("nope")
    with pytest.raises(StoreError):
        store.set_run_status("nope", "running")


def test_run_duplicate_rejected(store: PlatformStore) -> None:
    store.create_run(run_id="dup", graph_name="g", graph_version="1")
    with pytest.raises(StoreError):
        store.create_run(run_id="dup", graph_name="g", graph_version="1")


def test_list_runs_newest_first(store: PlatformStore) -> None:
    store.create_run(run_id="a", graph_name="g", graph_version="1")
    store.create_run(run_id="b", graph_name="g", graph_version="1")
    runs = store.list_runs()
    assert [r["run_id"] for r in runs] == ["b", "a"]
    assert store.list_runs(limit=1)[0]["run_id"] == "b"


def test_find_run_by_idempotency_key(store: PlatformStore) -> None:
    store.create_run(run_id="r9", graph_name="g", graph_version="1", idempotency_key="k9")
    assert store.find_run_by_idempotency_key("k9")["run_id"] == "r9"
    assert store.find_run_by_idempotency_key("missing") is None


# ---------- node_execution ----------

def test_node_execution_roundtrip(store: PlatformStore) -> None:
    store.create_run(run_id="rn", graph_name="g", graph_version="1")
    store.start_node("rn", node_name="ingest", seq=1, attempt=1)
    store.finish_node("rn", node_name="ingest", seq=1, status="completed", output_payload={"n": 2})
    nodes = store.list_nodes("rn")
    assert len(nodes) == 1
    assert nodes[0]["status"] == "completed"
    assert json.loads(nodes[0]["output_json"]) == {"n": 2}
    assert nodes[0]["started_at"] and nodes[0]["ended_at"]


def test_node_invalid_status(store: PlatformStore) -> None:
    store.create_run(run_id="rn2", graph_name="g", graph_version="1")
    store.start_node("rn2", node_name="x", seq=1, attempt=1)
    with pytest.raises(StoreError):
        store.finish_node("rn2", node_name="x", seq=1, status="sideways")


# ---------- checkpoint ----------

def test_checkpoint_roundtrip(store: PlatformStore) -> None:
    store.create_run(run_id="rc", graph_name="g", graph_version="1")
    store.save_checkpoint("rc", node_name="step2", payload={"cursor": 42})
    cp = store.load_checkpoint("rc", "step2")
    assert cp == {"cursor": 42}
    # 覆盖写：最新值生效
    store.save_checkpoint("rc", node_name="step2", payload={"cursor": 43})
    assert store.load_checkpoint("rc", "step2") == {"cursor": 43}
    assert store.load_checkpoint("rc", "missing") is None


# ---------- job / attempt ----------

def test_job_attempts(store: PlatformStore) -> None:
    store.create_job(job_id="job-1", kind="recognition", payload={"img": "x"})
    store.set_job_status("job-1", "running")
    store.record_attempt("job-1", attempt_no=1, status="failed", detail={"err": "timeout"})
    store.record_attempt("job-1", attempt_no=2, status="succeeded", detail={})
    store.set_job_status("job-1", "succeeded", result_payload={"ok": True})
    job = store.get_job("job-1")
    assert job["status"] == "succeeded"
    attempts = store.list_attempts("job-1")
    assert [a["attempt_no"] for a in attempts] == [1, 2]
    assert attempts[0]["status"] == "failed"


def test_job_invalid_status(store: PlatformStore) -> None:
    store.create_job(job_id="job-2", kind="k")
    with pytest.raises(StoreError):
        store.set_job_status("job-2", "napping")


def test_orphaned_jobs_markable(store: PlatformStore) -> None:
    store.create_job(job_id="job-3", kind="k")
    store.set_job_status("job-3", "running")
    flagged = store.flag_orphaned_jobs(before_ts="9999-01-01T00:00:00+00:00")
    assert "job-3" in flagged
    assert store.get_job("job-3")["status"] == "failed"


# ---------- audit / usage / evidence ----------

def test_audit_append_list(store: PlatformStore) -> None:
    store.append_audit(actor="system", action="run.created", subject_type="run", subject_id="r1")
    store.append_audit(actor="admin", action="gate.approved", subject_type="run", subject_id="r1", detail={"note": "ok"})
    events = store.list_audit(subject_id="r1")
    assert len(events) == 2
    assert events[0]["action"] == "run.created"
    assert json.loads(events[1]["detail_json"]) == {"note": "ok"}


def test_usage_append_list(store: PlatformStore) -> None:
    store.append_usage(capability="legacy.recognition.v2", run_id="r1", quantity=1.0, unit="call")
    rows = store.list_usage(run_id="r1")
    assert len(rows) == 1
    assert rows[0]["capability"] == "legacy.recognition.v2"
    assert rows[0]["quantity"] == 1.0


def test_evidence_bundle(store: PlatformStore) -> None:
    store.create_run(run_id="re", graph_name="g", graph_version="1")
    store.create_evidence_bundle(
        evidence_id="ev-1", run_id="re", kind="recognition",
        manifest={"items": [{"ref": "sha256:abc", "role": "input_photo"}]},
    )
    ev = store.get_evidence("ev-1")
    assert ev["run_id"] == "re"
    assert json.loads(ev["manifest_json"])["items"][0]["role"] == "input_photo"
    with pytest.raises(StoreError):
        store.create_evidence_bundle(evidence_id="ev-1", run_id="re", kind="x", manifest={})


# ---------- 持久化与备份 ----------

def test_persistence_across_reopen(tmp_path: Path) -> None:
    db = tmp_path / "platform.sqlite"
    s = PlatformStore(db)
    s.create_run(run_id="persist", graph_name="g", graph_version="1")
    s.close()
    s2 = PlatformStore(db)
    assert s2.get_run("persist")["graph_name"] == "g"
    s2.close()


def test_backup_integrity(store: PlatformStore, tmp_path: Path) -> None:
    store.create_run(run_id="bk", graph_name="g", graph_version="1")
    dest = tmp_path / "backup.sqlite"
    info = store.backup(dest)
    assert info["ok"] is True
    assert dest.exists()
    # 备份文件独立可读且数据一致
    c = sqlite3.connect(str(dest))
    n = c.execute("SELECT COUNT(*) FROM graph_run WHERE run_id='bk'").fetchone()[0]
    assert n == 1
    c.close()
