"""ABOSV3 T8：standard profile 切换/回滚 API（审计 + fail-closed）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..auth import AuthService, require_principal
from ..iam import IAMService
from ..standard_profile import StandardProfileError, StandardProfileService


class SwitchBody(BaseModel):
    bundle_id: str
    reason: str = ""


def create_standard_profile_router(
        store: Any, svc: StandardProfileService, iam: IAMService,
        auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["recognition-standard"])

    def _require_admin(p) -> None:
        roles = set(iam.roles_of(p["actor"]))
        if p["role"] != "admin" and "platform_admin" not in roles \
                and "owner" not in roles:
            raise HTTPException(
                403, "standard 切换/回滚仅限平台管理员（审批矩阵）")

    @router.get("/api/v1/recognition/standard")
    def standard(request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        cur = svc.current()
        bundles = svc.list_bundles()
        shadow = svc.shadow_report()
        return {"current": cur,
                "bundles": bundles,
                "verify_current": (svc.verify_bundle(cur["bundle_id"])
                                   if cur.get("bundle_id") else None),
                "shadow": ({"images": shadow.get("images"),
                            "aggregate": shadow.get("aggregate"),
                            "bundles": shadow.get("bundles"),
                            "at": shadow.get("at")}
                           if shadow else None)}

    @router.get("/api/v1/recognition/standard/shadow-report")
    def shadow_report(request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        rep = svc.shadow_report()
        if rep is None:
            raise HTTPException(
                404, "shadow 报告不存在（先运行 "
                     "scripts/recognition_shadow_compare.py）")
        return rep

    @router.post("/api/v1/recognition/standard/switch")
    def switch(body: SwitchBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _require_admin(p)
        try:
            cur = svc.switch(bundle_id=body.bundle_id, actor=p["actor"],
                             reason=body.reason)
        except StandardProfileError as e:
            raise HTTPException(409, str(e))
        return {"current": cur,
                "note": "8091 识别服务重启后加载新 bundle；回滚经 "
                        "rollback 端点（原子备份已生成）"}

    @router.post("/api/v1/recognition/standard/rollback")
    def rollback(request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _require_admin(p)
        try:
            cur = svc.rollback(actor=p["actor"])
        except StandardProfileError as e:
            raise HTTPException(409, str(e))
        return {"current": cur, "note": "已回滚到上一个 bundle"}

    return router
