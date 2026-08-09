"""状态收口 T1：Cycle 逻辑节点唯一状态投影。

- 历史表 training_cycle_node_v1 保留（可重复行）；
- 投影 training_cycle_node_state_v2 UNIQUE(cycle_id, logical_node)；
- 回填按状态优先级 done>running>pending 且保留历史行；
- done 禁回退 pending（除非 reopen 事件）；
- 幂等重跑不新增重复投影；
- Cycle 总状态基于 19 distinct 节点计算。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.platform.data.store import PlatformStore
from src.platform.projection import (
    CycleProjectionService,
    IllegalTransition,
)

CID = "sku_long_tail_nextgen_cycle_v1"


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    s._conn.execute(
        "INSERT INTO training_cycle_v1 (cycle_id, name, status, version,"
        " created_by, created_at, updated_at) VALUES (?,?,?,1,?,?,?)",
        (CID, CID, "DRAFT", "x", "t", "t"))
    s._conn.commit()
    yield s
    s.close()


def _hist(store, node, status):
    store._conn.execute(
        "INSERT INTO training_cycle_node_v1 (cycle_id, node, status,"
        " idempotency_key, created_at, updated_at)"
        " VALUES (?,?,?,?,datetime('now'),datetime('now'))",
        (CID, node, status, f"{CID}:{node}:{status}:t"))
    store._conn.commit()


def test_backfill_duplicate_nodes_to_single_projection(store):
    _hist(store, "M1Pilot", "pending")
    _hist(store, "M1Pilot", "done")
    svc = CycleProjectionService(store)
    audit = svc.backfill(CID)
    rows = store._conn.execute(
        "SELECT * FROM training_cycle_node_state_v2 WHERE cycle_id=?",
        (CID,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["logical_node"] == "M1Pilot"
    assert rows[0]["current_status"] == "done"
    # 历史行保留
    hist = store._conn.execute(
        "SELECT COUNT(*) c FROM training_cycle_node_v1"
        " WHERE cycle_id=? AND node='M1Pilot'", (CID,)).fetchone()
    assert hist["c"] == 2
    assert audit["M1Pilot"] == "done"
    # 幂等重跑
    svc.backfill(CID)
    rows2 = store._conn.execute(
        "SELECT COUNT(*) c FROM training_cycle_node_state_v2"
        " WHERE cycle_id=?", (CID,)).fetchone()
    assert rows2["c"] == 1


def test_done_cannot_regress_to_pending(store):
    svc = CycleProjectionService(store)
    svc.set_state(CID, "M1Pilot", "pending")
    svc.set_state(CID, "M1Pilot", "running")
    svc.set_state(CID, "M1Pilot", "done")
    with pytest.raises(IllegalTransition):
        svc.set_state(CID, "M1Pilot", "pending")
    # reopen 事件允许
    svc.set_state(CID, "M1Pilot", "pending", via_reopen=True)
    row = store._conn.execute(
        "SELECT current_status FROM training_cycle_node_state_v2"
        " WHERE cycle_id=? AND logical_node='M1Pilot'", (CID,)).fetchone()
    assert row["current_status"] == "pending"


def test_cycle_status_from_distinct_projections(store):
    svc = CycleProjectionService(store)
    nodes = ["BaselineReconciled", "SamPseudoMasksGenerated",
             "SamDecoderExperimentRecorded", "SnapshotsV3Frozen",
             "M1SmokeRecorded", "M2SmokeRecorded", "M3LeakageDetected",
             "M3GroupedBaselineRecorded", "M4PilotRecorded",
             "PlatformFactsReconciled", "Canonical38DatasetBuild",
             "M1Pilot", "M2Pilot", "M3LongTailExperiments",
             "KBCoverageBuild", "M4RealCandidatePilot"]
    for n in nodes:
        svc.set_state(CID, n, "done")
    for n in ["DemoEvaluation", "AwaitingIndependentEvaluation",
              "AwaitingProductionDecision"]:
        svc.set_state(CID, n, "pending")
    st = svc.cycle_summary(CID)
    assert st["done"] == 16
    assert st["pending"] == 3
    assert st["distinct_nodes"] == 19
