"""ABOSV2 Phase C：Workflow Studio API。

定义生命周期（draft/lint/simulate/approve/publish/deprecate/新版本）、
节点库（来自已注册 Capability）、运行（start/pause/resume/cancel/retry/
人工批准）、模板、连接器状态、Workflow Agent 草稿。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..auth import AuthService, require_principal
from ..scope import bind_fixture_scope
from ..workflow import WorkflowError, WorkflowService


class DraftBody(BaseModel):
    name: str = ""
    spec: dict | None = None
    template_id: str | None = None
    definition_id: str | None = None
    test_run_id: str = ""


class UpdateBody(BaseModel):
    name: str | None = None
    spec: dict | None = None


class SimulateBody(BaseModel):
    inputs: dict = {}


class StartBody(BaseModel):
    inputs: dict = {}
    source: str = "web"
    version: int | None = None
    customer_id: str = ""   # UFC T7：工作流内命令链继承客户上下文
    project_id: str = ""
    test_run_id: str = ""   # SI2：UAT Test Run 上下文（先建后用）


class ApproveRunBody(BaseModel):
    decision: str = "approved"


class AgentDraftBody(BaseModel):
    text: str


def create_workflow_router(store: Any, service: WorkflowService,
                           auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["workflow"])

    def _err(fn):
        def wrap(*a, **kw):
            try:
                return fn(*a, **kw)
            except WorkflowError as e:
                raise HTTPException(409, str(e))
        return wrap

    # ---- 节点库 / 模板 / 连接器 ----

    @router.get("/api/v1/workflows/node-library")
    def node_library() -> dict:
        return service.node_library()

    @router.get("/api/v1/workflows/templates")
    def templates() -> dict:
        lib = service.node_library()
        return {"count": len(lib["templates"]),
                "templates": lib["templates"]}

    @router.get("/api/v1/workflows/timers")
    def timers(status: str = "") -> dict:
        """ABOSV3 T5：持久化 wait timer（访问时顺带触发到期恢复）。"""
        fired = service.resume_due_timers()
        rows = service.list_timers(status=status)
        return {"count": len(rows), "timers": rows,
                "fired_now": fired}

    # ---- 定义生命周期 ----

    @router.post("/api/v1/workflows")
    def create_draft(body: DraftBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        if not body.template_id and body.spec is None:
            raise HTTPException(422, "spec 或 template_id 必填")
        try:
            out = service.create_draft(
                name=body.name, spec=body.spec or {}, actor=p["actor"],
                definition_id=body.definition_id,
                from_template=body.template_id)
            if body.test_run_id:
                bind_fixture_scope(
                    store, "workflow_definition_v1",
                    out["definition_id"], body.test_run_id)
            return {"definition": out}
        except WorkflowError as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/workflows")
    def list_definitions(include_fixture: bool = False) -> dict:
        defs = store.list_workflow_definitions()
        if not include_fixture:
            # SI2 T4：工作流列表默认 operational（fixture 只在测试中心）
            defs = [d for d in defs
                    if (d.get("data_scope") or "operational")
                    == "operational"]
        return {"count": len(defs), "definitions": defs}

    @router.get("/api/v1/workflows/{definition_id}")
    def get_definition(definition_id: str,
                       version: int | None = None) -> dict:
        d = store.get_workflow_definition(definition_id, version)
        if d is None:
            raise HTTPException(404, f"定义不存在: {definition_id}")
        return {"definition": d}

    @router.put("/api/v1/workflows/{definition_id}")
    def update_draft(definition_id: str, body: UpdateBody,
                     request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            return {"definition": service.update_draft(
                definition_id, spec=body.spec, name=body.name,
                actor=p["actor"])}
        except WorkflowError as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/workflows/{definition_id}/lint")
    def lint(definition_id: str, request: Request) -> dict:
        require_principal(auth, request, csrf=True)
        try:
            return {"definition": service.lint(definition_id)}
        except WorkflowError as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/workflows/{definition_id}/simulate")
    def simulate(definition_id: str, body: SimulateBody,
                 request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            trace = service.simulate(definition_id, inputs=body.inputs,
                                     actor=p["actor"])
            return {"status": trace["status"],
                    "definition": store.get_workflow_definition(
                        definition_id)}
        except WorkflowError as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/workflows/{definition_id}/approve")
    def approve(definition_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            return {"definition": service.approve(
                definition_id, actor=p["actor"])}
        except WorkflowError as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/workflows/{definition_id}/publish")
    def publish(definition_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            return {"definition": service.publish(
                definition_id, actor=p["actor"])}
        except WorkflowError as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/workflows/{definition_id}/deprecate")
    def deprecate(definition_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            return {"definition": service.deprecate(
                definition_id, actor=p["actor"])}
        except WorkflowError as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/workflows/{definition_id}/new-version")
    def new_version(definition_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            return {"definition": service.new_version(
                definition_id, actor=p["actor"])}
        except WorkflowError as e:
            raise HTTPException(409, str(e))

    # ---- 运行 ----

    @router.post("/api/v1/workflows/{definition_id}/runs")
    def start_run(definition_id: str, body: StartBody,
                  request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        from ..rate_limit import enforce
        enforce(request, "workflow.run.start", p["actor"])
        try:
            out = service.start_run(
                definition_id, inputs=body.inputs, actor=p["actor"],
                source=body.source, version=body.version,
                customer_id=body.customer_id, project_id=body.project_id,
                test_run_id=body.test_run_id)
        except WorkflowError as e:
            raise HTTPException(409, str(e))
        return {"run": out["run"],
                "checkpoints": store.list_node_executions(
                    out["run"]["run_id"]),
                "status": out["trace"].get("status"),
                "error": out["trace"].get("error")}

    @router.get("/api/v1/workflows/runs/{run_id}")
    def run_detail(run_id: str) -> dict:
        run = store.get_business_run(run_id)
        if run is None:
            raise HTTPException(404, f"run 不存在: {run_id}")
        # UATCC T3：并行分支 durable 状态（真实执行身份/结果）
        brows = [dict(r) for r in store._conn.execute(
            "SELECT branch_id, node_id, branch_index, status,"
            " started_at, ended_at, error, output_json FROM"
            " workflow_branch_v1 WHERE run_id=? ORDER BY branch_index",
            (run_id,)).fetchall()]
        import json as _json
        for b in brows:
            try:
                b["entry"] = _json.loads(
                    b["output_json"] or "{}").get("entry", "")
            except Exception:
                b["entry"] = ""
        return {"run": run,
                "branches": brows,
                "checkpoints": store.list_node_executions(run_id),
                "dead_letters": store.list_dead_letters(run_id),
                "events": store.list_events(run_id=run_id)}

    @router.post("/api/v1/workflows/runs/{run_id}/approve")
    def approve_run(run_id: str, body: ApproveRunBody,
                    request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            run = service.approve_run(run_id, actor=p["actor"],
                                      decision=body.decision)
        except WorkflowError as e:
            raise HTTPException(409, str(e))
        return {"run": run,
                "checkpoints": store.list_node_executions(run_id)}

    @router.post("/api/v1/workflows/runs/{run_id}/pause")
    def pause_run(run_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            return {"run": service.pause_run(run_id, actor=p["actor"])}
        except Exception as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/workflows/runs/{run_id}/resume")
    def resume_run(run_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            return {"run": service.resume_run(run_id, actor=p["actor"])}
        except WorkflowError as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/workflows/runs/{run_id}/cancel")
    def cancel_run(run_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            return {"run": service.cancel_run(run_id, actor=p["actor"])}
        except Exception as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/workflows/runs/{run_id}/retry")
    def retry_run(run_id: str, request: Request,
                  body: SimulateBody | None = None) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            run = service.retry_run(run_id, actor=p["actor"],
                                    inputs=body.inputs if body else None)
        except WorkflowError as e:
            raise HTTPException(409, str(e))
        return {"run": run,
                "checkpoints": store.list_node_executions(run_id)}

    # ---- Workflow Agent（只能生成 draft；发布必须人工） ----

    @router.post("/api/v1/workflows/agent-draft")
    def agent_draft(body: AgentDraftBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        return service.agent_draft(body.text, actor=p["actor"])

    return router
