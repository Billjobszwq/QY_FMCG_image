"""ABOSV2 Phase B：控制平面 API（Command Gateway + 对账）。

POST /api/v1/commands：Web/API/Agent 共用的命令入口（登录+CSRF）。
GET  /api/v1/control/reconcile：current projection 与事件/账本对账。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..auth import AuthService, require_principal
from ..control_plane import CommandGateway, CommandGatewayError


class CommandBody(BaseModel):
    command_kind: str
    params: dict = {}
    source: str = "api"
    goal_id: str = ""
    customer_id: str = ""
    project_id: str = ""
    idempotency_key: str | None = None


class RetryBody(BaseModel):
    images: list | None = None  # 进程重启后重放表为空时可补交输入


def create_control_plane_router(store: Any, gateway: CommandGateway,
                                auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["control-plane"])

    @router.post("/api/v1/commands")
    def submit_command(body: CommandBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        idem = body.idempotency_key or request.headers.get(
            "idempotency-key")
        try:
            out = gateway.submit(
                command_kind=body.command_kind, params=body.params,
                actor=p["actor"], source=body.source,
                idempotency_key=idem, goal_id=body.goal_id,
                customer_id=body.customer_id, project_id=body.project_id)
        except CommandGatewayError as e:
            raise HTTPException(400, str(e))
        run = store.get_business_run(out["run_id"])
        work = store.get_work_item_v2(out["work_id"])
        status_code = 200
        resp = {"run": run, "work": work, "result": out.get("result"),
                "status": out["status"],
                "idempotent_replay": out.get("idempotent_replay", False)}
        if out["status"] == "failed":
            resp["error"] = out.get("error")
        return resp

    @router.post("/api/v1/commands/{run_id}/retry")
    def retry_command(run_id: str, request: Request,
                      body: RetryBody | None = None) -> dict:
        p = require_principal(auth, request, csrf=True)
        if body and body.images:
            try:
                gateway._replay_images[run_id] = gateway._decode_images(
                    body.images)
            except CommandGatewayError as e:
                raise HTTPException(400, str(e))
        try:
            out = gateway.retry(run_id, actor=p["actor"])
        except CommandGatewayError as e:
            raise HTTPException(409, str(e))
        return out

    @router.post("/api/v1/commands/{run_id}/cancel")
    def cancel_command(run_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            return gateway.cancel(run_id, actor=p["actor"])
        except Exception as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/control/projection")
    def projection() -> dict:
        """统一 current task 投影（WorkItemV2，可从事件重建）。"""
        proj = store.rebuild_work_projection()
        return {"count": proj["count"], "items": proj["items"],
                "hash": proj["hash"]}

    @router.get("/api/v1/control/reconcile")
    def reconcile() -> dict:
        """事件↔投影↔outbox 对账（只读）。"""
        proj = store.rebuild_work_projection()
        proj2 = store.rebuild_work_projection()
        events = store.list_events()
        outbox_rows = store._conn.execute(
            "SELECT status, count(*) c FROM outbox_v1"
            " GROUP BY status").fetchall()
        outbox = {r["status"]: r["c"] for r in outbox_rows}
        consistent = (proj["hash"] == proj2["hash"]
                      and len(events) >= proj["count"]
                      and outbox.get("pending", 0) == 0)
        return {"consistent": consistent,
                "projection": {"count": proj["count"],
                               "hash": proj["hash"]},
                "event_count": len(events),
                "outbox": outbox}

    return router
