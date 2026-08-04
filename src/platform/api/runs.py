"""W9/W10：Graph Runs API（通用路由器；领域 Graph 名由客户端选择，平台不硬编码）。"""

from __future__ import annotations

import json

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from .bundle import PlatformBundle

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class StartRunBody(BaseModel):
    graph_name: str
    graph_version: str = "1"
    input: dict = {}
    idempotency_key: str | None = None


class ApproveBody(BaseModel):
    approved: bool
    actor: str = "human"


def run_view(bundle: PlatformBundle, run_id: str) -> dict:
    run = bundle.store.get_run(run_id)
    run = dict(run)
    for k in ("input_json", "output_json"):
        if run.get(k):
            run[k] = json.loads(run[k])
    return {
        "run": run,
        "nodes": bundle.store.list_nodes(run_id),
        "evidence": bundle.store.list_evidence(run_id),
    }


def create_runs_router(bundle: PlatformBundle) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/assets/upload")
    async def upload(file: UploadFile = File(...)):
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="payload too large")
        if len(data) == 0:
            raise HTTPException(status_code=400, detail="empty file")
        ref = bundle.cas.put(data, kind="photo", media_type=file.content_type)
        return ref.model_dump()

    @router.post("/api/v1/runs")
    def start_run(body: StartRunBody):
        try:
            run = bundle.engine.start_run(
                body.graph_name,
                body.graph_version,
                body.input,
                idempotency_key=body.idempotency_key,
            )
        except KeyError as e:
            raise HTTPException(status_code=404, detail=f"graph 未注册: {e}")
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        bundle.engine.execute(run["run_id"], bundle.handlers_for(body.graph_name))
        return run_view(bundle, run["run_id"])

    @router.post("/api/v1/runs/{run_id}/approve")
    def approve(run_id: str, body: ApproveBody):
        try:
            bundle.engine.approve_human_gate(run_id, approved=body.approved, actor=body.actor)
        except Exception as e:
            raise HTTPException(status_code=409, detail=str(e))
        run = bundle.store.get_run(run_id)
        if body.approved and run["status"] == "running":
            bundle.engine.execute(run_id, bundle.handlers_for(run["graph_name"]))
        return run_view(bundle, run_id)

    @router.get("/api/v1/runs")
    def list_runs(limit: int = 50):
        runs = bundle.store.list_runs(limit=limit)
        return {"count": len(runs), "runs": runs}

    @router.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str):
        try:
            return run_view(bundle, run_id)
        except Exception as e:
            raise HTTPException(status_code=404, detail=str(e))

    return router
