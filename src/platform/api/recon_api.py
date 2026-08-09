"""纠偏 Task 2：reconciliation registry 只读 API（四方对账的 API 侧）。"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from fastapi import APIRouter


def create_recon_router(store: Any) -> APIRouter:
    router = APIRouter(tags=["reconciliation"])

    @router.get("/api/v1/training/artifacts")
    def artifacts() -> dict:
        rows = store._conn.execute(
            "SELECT * FROM model_artifact_registry_v1").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            p = Path(d["path"])
            d["disk_consistent"] = (
                p.exists() and hashlib.sha256(
                    p.read_bytes()).hexdigest() == d["sha256"])
            out.append(d)
        return {"count": len(out), "artifacts": out}

    @router.get("/api/v1/training/snapshots")
    def snapshots() -> dict:
        rows = store._conn.execute(
            "SELECT * FROM dataset_snapshot_registry_v1").fetchall()
        return {"count": len(rows), "snapshots": [dict(r) for r in rows]}

    @router.get("/api/v1/training/evaluations")
    def evaluations() -> dict:
        rows = store._conn.execute(
            "SELECT * FROM evaluation_registry_v1").fetchall()
        return {"count": len(rows), "evaluations": [dict(r) for r in rows]}

    @router.get("/api/v1/training/cycle")
    def cycle() -> dict:
        # 状态收口：读唯一投影 v2（历史表仅证据）
        from src.modules.training_control.cycle_projection import (
            CycleProjectionService)
        row = store._conn.execute(
            "SELECT * FROM training_cycle_v1 WHERE cycle_id="
            "'sku_long_tail_nextgen_cycle_v1'").fetchone()
        if row is None:
            return {"cycle": None}
        cps = CycleProjectionService(store)
        proj = store._conn.execute(
            "SELECT logical_node AS node, current_status AS status,"
            " evidence_json FROM training_cycle_node_state_v2"
            " WHERE cycle_id=? ORDER BY logical_node",
            (row["cycle_id"],)).fetchall()
        return {**dict(row), "nodes": [dict(n) for n in proj],
                "summary": cps.cycle_summary(row["cycle_id"]),
                "history_rows": store._conn.execute(
                    "SELECT COUNT(*) c FROM training_cycle_node_v1"
                    " WHERE cycle_id=?",
                    (row["cycle_id"],)).fetchone()["c"]}

    @router.get("/api/v1/platform/gate")
    def gate() -> dict:
        row = store._conn.execute(
            "SELECT status FROM training_cycle_v1 WHERE cycle_id="
            "'sku_long_tail_nextgen_cycle_v1'").fetchone()
        return {"gate": row["status"] if row else
                "MODEL_PILOTS_READY_AWAITING_CANDIDATE_EVALUATION",
                "history": ["FOUR_DEMO_CANDIDATES_READY_AWAITING_INDEPENDENT_"
                            "EVALUATION", "FOUR_CANDIDATES_READY_AWAITING_"
                            "MICRO_GOLD（撤销）",
                            "PIPELINE_SMOKES_READY_PLATFORM_NOT_CONNECTED"]}

    return router
