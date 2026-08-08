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
                                auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["agent-runtime"])

    @router.post("/api/agent/v1/sessions")
    def create_session(body: SessionBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        sid = "sess-" + uuid4().hex[:10]
        store._conn.execute(
            "INSERT INTO agent_session_v1 (session_id, created_by,"
            " created_at) VALUES (?,?,?)", (sid, p["name"], _now()))
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
        if not store._conn.execute(
                "SELECT 1 FROM agent_session_v1 WHERE session_id=?",
                (body.session_id,)).fetchone():
            raise HTTPException(404, "session not found")
        sup = SupervisorAgent(store)
        resp = sup.chat(body.session_id, body.text, actor=p["name"])
        # 命令预览落库
        for c in resp.get("commands", []):
            store._conn.execute(
                "INSERT INTO agent_command_v1 (command_id, kind, params_json,"
                " status, created_by, created_at) VALUES (?,?,?,?,?,?)",
                (c["command_id"], c["kind"],
                 json.dumps(c.get("params", {}), ensure_ascii=False),
                 "pending_approval", p["name"], _now()))
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
            (p["name"], _now(), command_id))
        store._conn.commit()
        # 批准 training.plan.create → 真实创建 Plan（不启动）
        if row["kind"] == "training.plan.create":
            store._conn.execute(
                "INSERT INTO training_plan_v2 (plan_id, lane, config_json,"
                " status, created_by, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                ("plan-" + uuid4().hex[:8], "classifier",
                 row["params_json"], "approved_not_started", p["name"],
                 _now(), _now()))
            store._conn.commit()
        return {"status": "approved"}

    @router.post("/api/agent/v1/commands/{command_id}/reject")
    def reject(command_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        store._conn.execute(
            "UPDATE agent_command_v1 SET status='rejected', decided_by=?,"
            " decided_at=? WHERE command_id=?",
            (p["name"], _now(), command_id))
        store._conn.commit()
        return {"status": "rejected"}

    @router.get("/api/v1/agents/{agent_id}")
    def agent_detail(agent_id: str) -> dict:
        reg = AgentRegistry(store)
        m = next((a for a in reg.list_agents()
                  if a["agent_id"] == agent_id), None)
        if m is None:
            raise HTTPException(404, "agent not found")
        return m

    @router.post("/api/v1/agents/{agent_id}/invoke")
    def agent_invoke(agent_id: str, request: Request) -> dict:
        require_principal(auth, request, csrf=True)
        reg = AgentRegistry(store)
        m = next((a for a in reg.list_agents()
                  if a["agent_id"] == agent_id), None)
        if m is None:
            raise HTTPException(404, "agent not found")
        # 只读 invoke：返回该 Agent 管辖的事实摘要
        if agent_id == "modelops":
            arts = store._conn.execute(
                "SELECT artifact_id, candidate_status FROM"
                " model_artifact_registry_v1").fetchall()
            return {"agent": agent_id,
                    "result": [dict(a) for a in arts]}
        if agent_id == "data_steward":
            snaps = store._conn.execute(
                "SELECT snapshot_id, manifest_sha FROM"
                " dataset_snapshot_registry_v1").fetchall()
            return {"agent": agent_id,
                    "result": [dict(s) for s in snaps]}
        return {"agent": agent_id, "result": {"ok": True}}

    @router.get("/api/v1/agents/{agent_id}/health")
    def agent_health(agent_id: str) -> dict:
        reg = AgentRegistry(store)
        ok = any(a["agent_id"] == agent_id for a in reg.list_agents())
        return {"agent": agent_id, "healthy": ok}

    @router.get("/api/v1/events/stream")
    def events_stream() -> dict:
        """简化事件流：返回最近黑板+cycle 事件（轮询式，非 SSE）。"""
        rows = store._conn.execute(
            "SELECT id, by, event_type, payload_json, created_at FROM"
            " blackboard_event_v1 ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        return {"events": [dict(r) for r in rows]}

    return router
