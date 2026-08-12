"""纠偏 Task 4：Agent runtime API（sessions/chat/commands/invoke/health/stream）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..agents.kernel import AgentRegistry
from ..agents.supervisor import SupervisorAgent
from ..auth import AuthService, require_principal


class SessionBody(BaseModel):
    title: str = ""


class ChatBody(BaseModel):
    session_id: str
    text: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_agent_runtime_router(store: Any,
                                auth: AuthService | None,
                                on_approved: Any = None,
                                runtime: Any = None) -> APIRouter:
    """on_approved(row_dict) -> result：命令批准后的领域执行钩子
    （由组合根注入；Agent 不直接写库/执行 SQL）。
    runtime：ABOSV3 真实 Agent Runtime（工具循环/版本化定义/health 探针）。"""
    router = APIRouter(tags=["agent-runtime"])

    @router.post("/api/agent/v1/sessions")
    def create_session(body: SessionBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        sid = "sess-" + uuid4().hex[:10]
        store._conn.execute(
            "INSERT INTO agent_session_v1 (session_id, created_by,"
            " created_at) VALUES (?,?,?)", (sid, p["actor"], _now()))
        store._conn.commit()
        return {"session_id": sid}

    @router.get("/api/agent/v1/sessions/{session_id}")
    def get_session(session_id: str) -> dict:
        row = store._conn.execute(
            "SELECT * FROM agent_session_v1 WHERE session_id=?",
            (session_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "session not found")
        msgs = store._conn.execute(
            "SELECT role, content, meta_json, created_at FROM"
            " agent_session_msg_v1 WHERE session_id=? ORDER BY id",
            (session_id,)).fetchall()
        return {**dict(row),
                "messages": [dict(m) for m in msgs]}

    @router.get("/api/agent/v1/sessions/{session_id}/messages")
    def get_messages(session_id: str) -> dict:
        msgs = store._conn.execute(
            "SELECT role, content, meta_json, created_at FROM"
            " agent_session_msg_v1 WHERE session_id=? ORDER BY id",
            (session_id,)).fetchall()
        return {"count": len(msgs), "messages": [dict(m) for m in msgs]}

    @router.post("/api/agent/v1/chat")
    def chat(body: ChatBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        # UATCC T6：Agent invoke/chat 限流
        from ..rate_limit import enforce
        enforce(request, "agent.invoke", p["actor"])
        if not store._conn.execute(
                "SELECT 1 FROM agent_session_v1 WHERE session_id=?",
                (body.session_id,)).fetchone():
            raise HTTPException(404, "session not found")
        # ABOSV3-P0-006：Supervisor 优先走真实工具循环（Provider SPI +
        # tool calling）；未命中工具意图时才回退规则/导航回答。
        if runtime is not None:
            try:
                rt = runtime.invoke("supervisor", body.text,
                                    actor=p["actor"],
                                    session_id=body.session_id)
                if rt.get("tool_trace"):
                    resp = {
                        "session_id": body.session_id,
                        "provider": rt["provider"],
                        "message": rt["message"],
                        "evidence_refs": rt["evidence_refs"],
                        "ui_intents": rt["ui_intents"],
                        "command_previews": rt["command_previews"],
                        "tasks": [], "delegations": [],
                        "memory_updates": [],
                        "requires_approval": rt["requires_approval"],
                        "trace_id": rt["trace_id"],
                        "tool_trace": rt["tool_trace"],
                        "run_id": rt["run_id"]}
                    store._conn.execute(
                        "INSERT INTO agent_session_msg_v1 (session_id,"
                        " role, content, meta_json, created_at)"
                        " VALUES (?,?,?,?,?)",
                        (body.session_id, "user", body.text,
                         json.dumps({"actor": p["actor"]},
                                    ensure_ascii=False), _now()))
                    meta = {k: v for k, v in resp.items()
                            if k not in ("message",)}
                    store._conn.execute(
                        "INSERT INTO agent_session_msg_v1 (session_id,"
                        " role, content, meta_json, created_at)"
                        " VALUES (?,?,?,?,?)",
                        (body.session_id, "supervisor", resp["message"],
                         json.dumps(meta, ensure_ascii=False,
                                    default=str), _now()))
                    store._conn.commit()
                    # 命令已由 runtime 落库 pending_approval，不重复插入
                    resp["answer"] = resp["message"]
                    resp["commands"] = resp["command_previews"]
                    resp["evidence"] = [e.get("ref", str(e)) for e in
                                        resp["evidence_refs"]]
                    return resp
            except Exception:
                pass  # 工具循环异常 → 诚实回退规则回答
        sup = SupervisorAgent(store)
        resp = sup.chat(body.session_id, body.text, actor=p["actor"])
        # 命令预览落库（新契约 command_previews，兼容旧 commands）
        for c in resp.get("command_previews") or resp.get("commands", []):
            store._conn.execute(
                "INSERT INTO agent_command_v1 (command_id, kind, params_json,"
                " status, created_by, created_at) VALUES (?,?,?,?,?,?)",
                (c["command_id"], c["kind"],
                 json.dumps(c.get("params", {}), ensure_ascii=False),
                 "pending_approval", p["actor"], _now()))
            store._conn.commit()
        return resp

    @router.post("/api/agent/v1/commands/{command_id}/approve")
    def approve(command_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        row = store._conn.execute(
            "SELECT * FROM agent_command_v1 WHERE command_id=?",
            (command_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "command not found")
        if row["status"] != "pending_approval":
            raise HTTPException(409, f"status={row['status']}")
        store._conn.execute(
            "UPDATE agent_command_v1 SET status='approved', decided_by=?,"
            " decided_at=? WHERE command_id=?",
            (p["actor"], _now(), command_id))
        store._conn.commit()
        # 批准 training.plan.create → 真实创建 Plan（不启动）
        if row["kind"] == "training.plan.create":
            store._conn.execute(
                "INSERT INTO training_plan_v2 (plan_id, lane, plan_json,"
                " status, created_by, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?)",
                ("plan-" + uuid4().hex[:8], "classifier",
                 row["params_json"], "approved_not_started", p["actor"],
                 _now(), _now()))
            store._conn.commit()
        result = None
        if on_approved is not None:
            # 领域执行经组合根注入的钩子（如 vision.recognition.create
            # → 统一 RecognitionTaskService）；失败不冒充成功
            try:
                result = on_approved(dict(row))
            except Exception as e:
                store._conn.execute(
                    "UPDATE agent_command_v1 SET status='approved_failed',"
                    " decided_at=? WHERE command_id=?",
                    (_now(), command_id))
                store._conn.commit()
                raise HTTPException(502, f"批准后执行失败: {e}")
        return {"status": "approved",
                **({"execution": result} if result is not None else {})}

    @router.post("/api/agent/v1/commands/{command_id}/reject")
    def reject(command_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        store._conn.execute(
            "UPDATE agent_command_v1 SET status='rejected', decided_by=?,"
            " decided_at=? WHERE command_id=?",
            (p["actor"], _now(), command_id))
        store._conn.commit()
        return {"status": "rejected"}

    @router.post("/api/v1/agents/{agent_id}/invoke")
    def agent_invoke(agent_id: str, request: Request,
                     body: dict | None = None) -> dict:
        """ABOSV3：真实工具循环 invoke（不再统一 ok=true）。"""
        p = require_principal(auth, request, csrf=True)
        # UATCC T6：Agent invoke 限流
        from ..rate_limit import enforce
        enforce(request, "agent.invoke", p["actor"])
        if runtime is None:
            raise HTTPException(503, "Agent Runtime 未装配")
        body = body or {}
        try:
            return runtime.invoke(
                agent_id, str(body.get("text", "")), actor=p["actor"],
                session_id=str(body.get("session_id", "")),
                customer_id=str(body.get("customer_id", "")),
                project_id=str(body.get("project_id", "")))
        except Exception as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/agents/runs")
    def agent_runs(request: Request, status: str = "",
                   limit: int = 50) -> dict:
        """UFC T9：Agent 运行列表（含失败详情：failed run/evidence/
        error），供失败详情抽屉与人工补救入口。"""
        require_principal(auth, request, csrf=False)
        where, params = "", []
        if status:
            where = " WHERE ar.status=?"
            params.append(status)
        rows = store._conn.execute(
            "SELECT ar.run_id, ar.agent_id, ar.status, ar.actor,"
            " ar.customer_id, ar.created_at, ar.business_run_id,"
            " ar.evidence_bundle_id, br.status AS business_status,"
            " br.error, br.work_id FROM agent_run_v1 ar LEFT JOIN"
            " business_run_v1 br ON br.run_id=ar.business_run_id"
            + where + " ORDER BY ar.created_at DESC LIMIT ?",
            (*params, min(limit, 200))).fetchall()
        return {"count": len(rows), "runs": [dict(r) for r in rows]}

    @router.get("/api/v1/agents/{agent_id}/health")
    def agent_health(agent_id: str) -> dict:
        """ABOSV3：有界探针（定义已发布 + 事实查询可执行 +
        allowlist 有效），不再是 Manifest 存在即健康。"""
        if runtime is None:
            reg = AgentRegistry(store)
            ok = any(a["agent_id"] == agent_id
                     for a in reg.list_agents())
            return {"agent": agent_id, "healthy": ok}
        return runtime.health(agent_id)

    # ---- ABOSV3 T4：版本化定义 / 资产 / 记忆 ----

    @router.get("/api/v1/agents/definitions")
    def list_definitions(request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        if runtime is None:
            raise HTTPException(503, "Agent Runtime 未装配")
        rows = runtime.list_definitions()
        return {"count": len(rows), "definitions": rows}

    @router.get("/api/v1/agents/definitions/{agent_id}")
    def get_definition(agent_id: str, request: Request,
                       version: int | None = None) -> dict:
        require_principal(auth, request, csrf=False)
        if runtime is None:
            raise HTTPException(503, "Agent Runtime 未装配")
        d = runtime.get_definition(agent_id, version)
        if d is None:
            raise HTTPException(404, "定义不存在")
        return {"definition": d}

    @router.post("/api/v1/agents/definitions/{agent_id}/draft")
    def save_definition_draft(agent_id: str, body: dict,
                              request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        if runtime is None:
            raise HTTPException(503, "Agent Runtime 未装配")
        try:
            d = runtime.save_draft(
                agent_id, actor=p["actor"], soul=body.get("soul"),
                system_prompt=body.get("system_prompt"),
                tool_allowlist=body.get("tool_allowlist"),
                budget=body.get("budget"), approval=body.get("approval"),
                provider=body.get("provider"), model=body.get("model"))
        except Exception as e:
            raise HTTPException(409, str(e))
        return {"definition": d}

    @router.post("/api/v1/agents/definitions/{agent_id}/publish")
    def publish_definition(agent_id: str, request: Request,
                           body: dict | None = None) -> dict:
        p = require_principal(auth, request, csrf=True)
        if runtime is None:
            raise HTTPException(503, "Agent Runtime 未装配")
        version = int((body or {}).get("version", 0)) or None
        d = runtime.get_definition(agent_id)
        if version is None:
            version = d["version"] if d else 1
        try:
            return {"definition": runtime.publish(
                agent_id, version, actor=p["actor"])}
        except Exception as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/agents/definitions/{agent_id}/rollback")
    def rollback_definition(agent_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        if runtime is None:
            raise HTTPException(503, "Agent Runtime 未装配")
        try:
            return {"definition": runtime.rollback(
                agent_id, actor=p["actor"])}
        except Exception as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/agents/assets")
    def list_assets(request: Request, kind: str = "") -> dict:
        require_principal(auth, request, csrf=False)
        if runtime is None:
            raise HTTPException(503, "Agent Runtime 未装配")
        rows = runtime.list_assets(kind=kind)
        return {"count": len(rows), "assets": rows}

    @router.post("/api/v1/agents/assets")
    def save_asset(body: dict, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        if runtime is None:
            raise HTTPException(503, "Agent Runtime 未装配")
        try:
            return {"asset": runtime.save_asset(
                kind=str(body.get("kind", "")),
                name=str(body.get("name", "")),
                content=str(body.get("content", "")),
                asset_id=body.get("asset_id"),
                customer_id=str(body.get("customer_id", "")),
                meta=body.get("meta"), actor=p["actor"])}
        except Exception as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/agents/assets/{asset_id}/publish")
    def publish_asset(asset_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        if runtime is None:
            raise HTTPException(503, "Agent Runtime 未装配")
        try:
            return {"asset": runtime.publish_asset(
                asset_id, actor=p["actor"])}
        except Exception as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/agents/{agent_id}/memories")
    def list_memories(agent_id: str, request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        if runtime is None:
            raise HTTPException(503, "Agent Runtime 未装配")
        rows = runtime.list_memories(agent_id)
        return {"count": len(rows), "memories": rows}

    @router.post("/api/v1/agents/{agent_id}/memories")
    def remember(agent_id: str, body: dict, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        if runtime is None:
            raise HTTPException(503, "Agent Runtime 未装配")
        try:
            return runtime.remember(
                agent_id=agent_id, content=str(body.get("content", "")),
                level=str(body.get("level", "L1")), actor=p["actor"])
        except Exception as e:
            raise HTTPException(409, str(e))

    @router.delete("/api/v1/agents/memories/{memory_id}")
    def clear_memory(memory_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        if runtime is None:
            raise HTTPException(503, "Agent Runtime 未装配")
        try:
            runtime.clear_memory(memory_id, actor=p["actor"])
        except Exception as e:
            raise HTTPException(409, str(e))
        return {"cleared": memory_id}

    # 注意：通配路由 /api/v1/agents/{agent_id} 必须在全部具体
    # 路径（definitions/assets/memories）之后注册，避免遮蔽。
    @router.get("/api/v1/agents/{agent_id}")
    def agent_detail(agent_id: str) -> dict:
        reg = AgentRegistry(store)
        m = next((a for a in reg.list_agents()
                  if a["agent_id"] == agent_id), None)
        if m is None:
            raise HTTPException(404, "agent not found")
        return m

    @router.get("/api/v1/events/stream")
    def events_stream() -> dict:
        """简化事件流：返回最近黑板+cycle 事件（轮询式，非 SSE）。"""
        rows = store._conn.execute(
            "SELECT id, by, event_type, payload_json, created_at FROM"
            " blackboard_event_v1 ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        return {"events": [dict(r) for r in rows]}

    return router
