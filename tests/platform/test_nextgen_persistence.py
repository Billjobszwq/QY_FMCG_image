"""N2 Task 1：持久化 Cycle/Plan/Run/Artifact（03 计划 Task 1）。

- append-only cycle/node checkpoint/events；乐观版本推进；
- 服务重启后从 DB 恢复；重复幂等键不重复执行；
- training_run_v2 兼容投影，但 cycle 表是唯一写事实源。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.modules.training_control.cycle import (
    CYCLE_STATES,
    CycleError,
    TrainingCycleService,
)
from src.platform.data.store import PlatformStore


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def test_cycle_states_frozen():
    assert CYCLE_STATES[0] == "DRAFT"
    assert "FOUR_EXPERIMENTAL_CANDIDATES_READY" in CYCLE_STATES
    assert "AWAITING_PROMOTION_DECISION" in CYCLE_STATES


def test_create_and_recover_cycle(store):
    svc = TrainingCycleService(store)
    cid = svc.create_cycle(name="nextgen_v2_cycle_1", actor="admin")
    st = svc.get_cycle(cid)
    assert st["status"] == "DRAFT" and st["version"] == 1
    # 服务重启 = 新 service 实例，从 DB 恢复
    svc2 = TrainingCycleService(store)
    assert svc2.get_cycle(cid)["status"] == "DRAFT"


def test_advance_with_optimistic_version(store):
    svc = TrainingCycleService(store)
    cid = svc.create_cycle(name="c", actor="admin")
    svc.advance(cid, "BASELINE_VERIFIED", actor="admin",
                expected_version=1)
    assert svc.get_cycle(cid)["version"] == 2
    # 版本冲突（并发/重复按钮）→ 拒绝
    with pytest.raises(CycleError):
        svc.advance(cid, "ASSET_SCOPE_FROZEN", actor="admin",
                    expected_version=1)
    # 非法跃迁拒绝并留审计
    with pytest.raises(CycleError):
        svc.advance(cid, "TRAINING_RUNNING", actor="admin",
                    expected_version=2)


def test_node_checkpoint_idempotent(store):
    svc = TrainingCycleService(store)
    cid = svc.create_cycle(name="c", actor="admin")
    svc.record_node(cid, node="ExactDedup", status="completed",
                    idempotency_key="dedup-v1",
                    evidence={"unique": 29176})
    # 重复幂等键 → 不重复执行
    out = svc.record_node(cid, node="ExactDedup", status="completed",
                          idempotency_key="dedup-v1",
                          evidence={"unique": 999})
    assert out["duplicate"] is True
    cp = svc.node_checkpoint(cid, "ExactDedup")
    assert cp["evidence"]["unique"] == 29176


def test_events_append_only(store):
    import sqlite3
    svc = TrainingCycleService(store)
    cid = svc.create_cycle(name="c", actor="admin")
    svc.advance(cid, "BASELINE_VERIFIED", actor="admin",
                expected_version=1)
    evs = svc.events(cid)
    assert any(e["kind"] == "cycle_advanced" for e in evs)
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("DELETE FROM training_cycle_event_v1")


def test_plan_approval_and_run_attempt(store):
    svc = TrainingCycleService(store)
    cid = svc.create_cycle(name="c", actor="admin")
    pid = svc.register_plan(
        cid, lane="detector", hypothesis="h", base_revision="public:yolo26m@r1",
        dataset_hash="d" * 8, budget={"minutes": 60},
        stop_lines=["fp>1"], eval_set_hash="e" * 8, actor="admin")
    plan = svc.get_plan(pid)
    assert plan["status"] == "DRAFT"
    svc.approve_plan(pid, actor="boss", approval_key="appr-1")
    assert svc.get_plan(pid)["status"] == "APPROVED"
    # 重复审批幂等键不重复记录
    svc.approve_plan(pid, actor="boss", approval_key="appr-1")
    assert svc.get_plan(pid)["approved_count"] == 1
    # run attempt 登记（新 attempt 新目录语义在 adapter；这里登记账）
    rid = svc.register_run_attempt(pid, attempt=1, command_hash="c" * 8,
                                   env_hash="n" * 8)
    att = svc.get_run_attempt(rid)
    assert att["attempt"] == 1 and att["status"] == "REGISTERED"


def test_artifact_registration_immutable(store):
    import sqlite3
    svc = TrainingCycleService(store)
    cid = svc.create_cycle(name="c", actor="admin")
    pid = svc.register_plan(cid, lane="detector", hypothesis="h",
                            base_revision="public:yolo26m@r1",
                            dataset_hash="d" * 8, budget={},
                            stop_lines=[], eval_set_hash="e" * 8,
                            actor="admin")
    rid = svc.register_run_attempt(pid, attempt=1, command_hash="c" * 8,
                                   env_hash="n" * 8)
    svc.register_artifact(rid, artifact_type="checkpoint",
                          path="/runs/a/best.pt", sha256="ab" * 32,
                          lineage={"base": "public:yolo26m@r1"})
    arts = svc.list_artifacts(rid)
    assert arts[0]["sha256"] == "ab" * 32
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("DELETE FROM training_artifact_v2")
