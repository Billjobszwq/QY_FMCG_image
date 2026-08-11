"""ABOSV2-P0-002：快速目标 goal draft API。

目标先落服务端（migration 032 goal_draft_v1），再打开主管；
确认后由 Supervisor 形成计划/命令并留痕（message/command_previews/
trace_id）。刷新可恢复：open goal 可 GET 拉回。
业务状态禁止只存 URL/前端/localStorage。
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..agents.supervisor import SupervisorAgent
from ..auth import AuthService, require_principal


class GoalCreateBody(BaseModel):
    text: str


def create_goals_router(store: Any,
                        auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["goals"])

    @router.post("/api/v1/goals")
    def create_goal(body: GoalCreateBody, request: Request) -> dict:
        principal = require_principal(auth, request, csrf=True)
        text = body.text.strip()
        if not text:
            raise HTTPException(422, "目标文本不得为空")
        goal = store.create_goal_draft(
            goal_id="goal-" + uuid.uuid4().hex[:12],
            text=text, created_by=principal["actor"])
        return {"goal": goal}

    @router.get("/api/v1/goals")
    def list_goals(request: Request,
                   status: str | None = None) -> dict:
        require_principal(auth, request, csrf=False)
        if status not in (None, "open", "confirmed", "cancelled"):
            raise HTTPException(
                422, f"status 只支持 open/confirmed/cancelled，收到 {status!r}")
        goals = store.list_goal_drafts(status=status)
        return {"count": len(goals), "goals": goals}

    @router.get("/api/v1/goals/{goal_id}")
    def get_goal(goal_id: str, request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        goal = store.get_goal_draft(goal_id)
        if goal is None:
            raise HTTPException(404, f"goal 不存在: {goal_id}")
        return {"goal": goal}

    @router.post("/api/v1/goals/{goal_id}/confirm")
    def confirm_goal(goal_id: str, request: Request) -> dict:
        """确认目标 → Supervisor 形成计划/命令；结果随 goal 留痕。"""
        principal = require_principal(auth, request, csrf=True)
        goal = store.get_goal_draft(goal_id)
        if goal is None:
            raise HTTPException(404, f"goal 不存在: {goal_id}")
        sup = SupervisorAgent(store)
        resp = sup.chat(session_id=f"goal:{goal_id}", text=goal["text"],
                        actor=principal["actor"])
        result = {
            "message": resp.get("message"),
            "command_previews": resp.get("command_previews") or [],
            "ui_intents": resp.get("ui_intents") or [],
            "evidence_refs": resp.get("evidence_refs") or [],
            "delegations": resp.get("delegations") or [],
            "requires_approval": resp.get("requires_approval", False),
            "provider": resp.get("provider"),
            "trace_id": resp.get("trace_id"),
            "confirmed_by": principal["actor"],
        }
        try:
            updated = store.resolve_goal_draft(
                goal_id, status="confirmed", result=result,
                expected_version=goal["version"])
        except Exception as e:  # StoreError：终态重复/版本冲突
            raise HTTPException(409, str(e))
        return {"goal": updated}

    return router
