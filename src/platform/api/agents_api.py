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
    def blackboard_list(current: int = 0) -> dict:
        bb = BlackboardService(store)
        cards = bb.cards(current_only=bool(current))
        return {"count": len(cards), "events": cards,
                "current_only": bool(current)}

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
        """任务板：读 task_state_projection_v1 唯一投影（无过期状态）。"""
        from src.platform.projection import (
            TaskProjectionService)
        tps = TaskProjectionService(store)
        return {"states": tps.board(
            "sku_long_tail_nextgen_cycle_v1")}

    return router
