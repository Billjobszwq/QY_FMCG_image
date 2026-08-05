"""U5-2/U5-3：Graph+Loop v2 运行 API。

口径：
- runs/trail 只读端点公开；start/gate 强制服务端 session+CSRF，
  且仅限 admin（训练相关链路不得由 operator 触发）；
- start 与 gate 批准后同步执行到下一个终态/人工门，
  返回真实 status/stop_reason/决策轨迹/等待项，禁止伪造；
- 识别默认走真实 8091；质量走真实 qpol_v2。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..auth import AuthService, require_principal
from ..kernel.loop import LoopEngine
from ..loops.pipeline_v2 import GRAPH_NAME, build_graph, build_handlers, \
    build_routers

REPO_ROOT = Path(__file__).resolve().parents[3]


class StartBody(BaseModel):
    source_id: str = "photo1106"
    batch_size: int = 8
    max_rounds: int = 5
    idempotency_key: str | None = None


class GateBody(BaseModel):
    approved: bool


def _run_view(store, eng: LoopEngine, run: dict[str, Any]) -> dict[str, Any]:
    view = dict(run)
    out = None
    if run.get("output_json"):
        try:
            out = json.loads(run["output_json"])
        except (TypeError, ValueError):
            out = None
    if isinstance(out, dict) and out.get("stop_reason"):
        view["stop_reason"] = out["stop_reason"]
    trail = eng.decision_trail(run["run_id"])
    view["trail"] = trail
    view["rounds_used"] = max((d["round"] for d in trail), default=0)
    waiting = None
    if run["status"] == "waiting_human":
        gates = [d for d in trail if d["decision"] == "human_gate"]
        waiting = gates[-1]["reason"] if gates else "等待人工"
    view["waiting_for"] = waiting
    view["next_node"] = (
        (store.load_checkpoint(run["run_id"], "__loop_state__") or {})
        .get("node"))
    nodes = store.list_nodes(run["run_id"])
    view["cost_nodes"] = len(nodes)
    view["cost_detail"] = {
        "node_executions": len(nodes),
        "quality_evals": sum(
            1 for n in nodes if n["node_name"] == "quality"
            and n["status"] == "completed"),
    }
    return view


def create_loops_router(store, auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["loops"])

    @router.get("/api/v1/loops/runs")
    def runs(request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        eng = LoopEngine(store)
        items = []
        for r in store.list_runs(limit=200):
            if r["graph_name"] != GRAPH_NAME:
                continue
            v = _run_view(store, eng, r)
            items.append({k: v.get(k) for k in (
                "run_id", "status", "error", "stop_reason", "rounds_used",
                "waiting_for", "next_node", "cost_nodes", "created_at",
                "updated_at")})
        return {"n_runs": len(items), "runs": items}

    @router.get("/api/v1/loops/runs/{run_id}")
    def run_detail(run_id: str, request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        eng = LoopEngine(store)
        try:
            run = store.get_run(run_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=404, detail=str(e))
        if run["graph_name"] != GRAPH_NAME:
            raise HTTPException(status_code=404, detail="非 Loop v2 run")
        return _run_view(store, eng, run)

    @router.post("/api/v1/loops/start")
    def start(body: StartBody, request: Request) -> dict:
        p = require_principal(auth, request)
        if p.get("role") != "admin":
            raise HTTPException(status_code=403,
                                detail="启动 Loop 仅限 admin")
        eng = LoopEngine(store)
        graph = build_graph(max_rounds=body.max_rounds)
        run = eng.start_run(
            graph,
            {"origin": "api", "actor": p["actor"],
             "source_id": body.source_id},
            idempotency_key=body.idempotency_key)
        handlers = build_handlers(store, root=REPO_ROOT,
                                  source_id=body.source_id,
                                  batch_size=body.batch_size)
        out = eng.execute(run["run_id"], handlers, build_routers())
        store.append_audit(actor=p["actor"], action="loop.started",
                           subject_type="run", subject_id=out["run_id"],
                           detail={"source_id": body.source_id,
                                   "status": out["status"]})
        return _run_view(store, eng, out)

    @router.post("/api/v1/loops/runs/{run_id}/gate")
    def gate(run_id: str, body: GateBody, request: Request) -> dict:
        p = require_principal(auth, request)
        if p.get("role") != "admin":
            raise HTTPException(status_code=403,
                                detail="人工门审批仅限 admin")
        eng = LoopEngine(store)
        try:
            run = store.get_run(run_id)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=404, detail=str(e))
        if run["graph_name"] != GRAPH_NAME:
            raise HTTPException(status_code=404, detail="非 Loop v2 run")
        try:
            eng.approve_human_gate(run_id, approved=body.approved,
                                   actor=p["actor"])
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        if body.approved:
            source_id = (json.loads(run["input_json"] or "{}")
                         .get("source_id", "photo1106"))
            handlers = build_handlers(store, root=REPO_ROOT,
                                      source_id=source_id)
            out = eng.execute(run_id, handlers, build_routers())
            return _run_view(store, eng, out)
        return _run_view(store, eng, store.get_run(run_id))

    return router
