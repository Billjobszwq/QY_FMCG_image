"""UATCC T6：限流管理 API（仅管理员；修改留审计）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..auth import AuthService, require_principal
from ..iam import IAMService
from ..rate_limit import RateLimiter


class RuleBody(BaseModel):
    max_per_window: int
    window_seconds: int = 60
    burst: int = 0
    enabled: bool = True


def _is_admin(iam: IAMService, actor: str, role: str) -> bool:
    if role == "admin":
        return True
    roles = set(iam.roles_of(actor))
    return "platform_admin" in roles or "owner" in roles


def create_rate_limit_router(store: Any, limiter: RateLimiter,
                             iam: IAMService,
                             auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["rate-limit"])

    @router.get("/api/v1/rate-limit/rules")
    def rules(request: Request) -> dict:
        p = require_principal(auth, request, csrf=False)
        if not _is_admin(iam, p["actor"], p["role"]):
            raise HTTPException(403, "仅管理员可查看限流规则")
        return {"rules": limiter.list_rules()}

    @router.put("/api/v1/rate-limit/rules/{capability}")
    def update_rule(capability: str, body: RuleBody,
                    request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        if not _is_admin(iam, p["actor"], p["role"]):
            raise HTTPException(403, "仅管理员可修改限流规则")
        try:
            rule = limiter.set_rule(
                capability, max_per_window=body.max_per_window,
                window_seconds=body.window_seconds, burst=body.burst,
                enabled=body.enabled, actor=p["actor"])
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"rule": rule}

    @router.get("/api/v1/rate-limit/stats")
    def stats(request: Request) -> dict:
        p = require_principal(auth, request, csrf=False)
        if not _is_admin(iam, p["actor"], p["role"]):
            raise HTTPException(403, "仅管理员可查看限流统计")
        denied = store._conn.execute(
            "SELECT count(*) c FROM event_envelope_v1 WHERE"
            " event_type='rate_limit.denied'").fetchone()["c"]
        return {"denied_total": denied,
                "rules": limiter.list_rules()}

    return router
