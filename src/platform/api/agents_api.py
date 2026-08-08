"""SLTF §11/§12/§13：Agent/Blackboard/TaskBoard API。

Web/CLI/Agent 共用；UIIntent 白名单校验；blackboard append-only。
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..agents.blackboard import BlackboardService, MemoryService
from ..agents.kernel import (AgentRegistry, UIIntentError,
                             validate_ui_intent)
from ..auth import AuthService, require_principal


class BlackboardAppendBody(BaseModel):
    event_type: str
    payload: dict = {}
    evidence_refs: list[str] = []
    supersedes: str | None = None


class UIIntentBody(BaseModel):
    intent: dict


def create_agents_router(store: Any,
                         auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["agents"])

    @router.get("/api/v1/agents")
    def agents_list() -> dict:
        reg = AgentRegistry(store)
        return {"count": len(reg.list_agents()),
                "agents": reg.list_agents()}

    @router.get("/api/v1/blackboard")
    def blackboard_list() -> dict:
        bb = BlackboardService(store)
        cards = bb.cards()
        return {"count": len(cards), "events": cards}

    @router.post("/api/v1/blackboard")
    def blackboard_append(body: BlackboardAppendBody,
                          request: Request) -> dict:
        principal = require_principal(auth, request, csrf=True)
        bb = BlackboardService(store)
        try:
            eid = bb.append(principal["name"], body.event_type,
                            body.payload, evidence_refs=body.evidence_refs,
                            supersedes=body.supersedes,
                            by_kind="human" if principal.get("role")
                            == "admin" else "agent")
        except (ValueError, PermissionError) as e:
            raise HTTPException(409, str(e))
        return {"id": eid}

    @router.post("/api/v1/ui-intent")
    def ui_intent(body: UIIntentBody, request: Request) -> dict:
        require_principal(auth, request, csrf=True)
        try:
            validate_ui_intent(body.intent)
        except UIIntentError as e:
            raise HTTPException(422, str(e))
        return {"accepted": True, "intent": body.intent}

    @router.get("/api/v1/taskboard")
    def taskboard() -> dict:
        """任务板投影：Todo→Running→Waiting→Review→Done。

        同标题 Task 取最新事件 state（append-only，不修改历史）。"""
        bb = BlackboardService(store)
        tasks = [e for e in bb.cards() if e["event_type"] == "Task"]
        latest: dict[str, dict] = {}
        for t in tasks:
            payload = json.loads(t["payload_json"] or "{}")
            title = payload.get("title") or payload.get("text") or t["id"]
            latest[title] = {**t, "payload": payload, "title": title}
        by_state: dict[str, list] = {s: [] for s in (
            "todo", "running", "waiting", "review", "done")}
        for t in latest.values():
            st = t["payload"].get("state") or "todo"
            by_state.setdefault(st, []).append(t)
        return {"states": by_state}

    return router
