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
        row = store._conn.execute(
            "SELECT * FROM training_cycle_v1 WHERE cycle_id="
            "'sku_long_tail_nextgen_cycle_v1'").fetchone()
        if row is None:
            return {"cycle": None}
        nodes = store._conn.execute(
            "SELECT node, status, evidence_json FROM training_cycle_node_v1"
            " WHERE cycle_id=? ORDER BY id", (row["cycle_id"],)).fetchall()
        return {**dict(row), "nodes": [dict(n) for n in nodes]}

    @router.get("/api/v1/platform/gate")
    def gate() -> dict:
        return {"gate": "PIPELINE_SMOKES_READY_PLATFORM_NOT_CONNECTED",
                "corrected_from":
                "FOUR_DEMO_CANDIDATES_READY_AWAITING_INDEPENDENT_EVALUATION"}

    return router
