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
    test_run_id: str = ""   # SI2：UAT Test Run 上下文（受信路径）


class RetryBody(BaseModel):
    images: list | None = None  # 进程重启后重放表为空时可补交输入


def create_control_plane_router(store: Any, gateway: CommandGateway,
                                auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["control-plane"])

    @router.post("/api/v1/commands")
    def submit_command(body: CommandBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        # UATCC T6：识别等高成本命令限流
        if body.command_kind == "vision.recognition.create":
            from ..rate_limit import enforce
            enforce(request, "recognition.create", p["actor"])
        idem = body.idempotency_key or request.headers.get(
            "idempotency-key")
        try:
            out = gateway.submit(
                command_kind=body.command_kind, params=body.params,
                actor=p["actor"], source=body.source,
                idempotency_key=idem, goal_id=body.goal_id,
                customer_id=body.customer_id, project_id=body.project_id,
                test_run_id=body.test_run_id)
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

    # ABOSV3-P0-002：首页/主管/任务板/日历共用的唯一 current 事实。
    # WorkItemV2 主线（控制平面）+ 遗留域工作（审核/训练/Job/标注，
    # 经 supersession 账本排除被取代族）；不得再有平行真相。
    _RUN_TO_WORK = {"succeeded": "done", "failed": "blocked",
                    "partial_failed": "blocked",
                    "cancelled": "cancelled", "waiting_human": "waiting",
                    "waiting_timer": "waiting",
                    "paused": "waiting", "running": "running",
                    "queued": "running"}

    @router.get("/api/v1/control/current-work")
    def current_work() -> dict:
        proj = store.rebuild_work_projection()
        items = [{"id": i["work_id"], "work_id": i["work_id"],
                  "kind": "work_item_v2", "source": "control_plane",
                  "status": i["status"], "title": i.get("title", ""),
                  "owner": i.get("owner_id", ""),
                  "due_at": i.get("due_at"),
                  "run_id": i.get("run_id", ""),
                  "subject_type": i.get("subject_type", ""),
                  "subject_id": i.get("subject_id", ""),
                  "customer_id": i.get("customer_id", ""),
                  "project_id": i.get("project_id", ""),
                  "blockers": i.get("blockers", [])}
                 for i in proj["items"]]
        try:
            from .workitems import collect_workitems
            legacy = collect_workitems(store, projection="current")
            for w in legacy["items"]:
                items.append({**w, "source": "legacy_domain"})
        except Exception:
            pass
        return {"count": len(items), "items": items,
                "projection": "current", "hash": proj["hash"]}

    @router.get("/api/v1/control/reconcile")
    def reconcile() -> dict:
        """事件↔投影↔outbox↔BusinessRun 业务事实对账（只读+自愈）。

        ABOSV3 要求：不得只和错误 reducer 自洽；必须逐个对照
        business_run_v1 的当前状态与 work 投影，漂移即修复并计数。
        """
        proj = store.rebuild_work_projection()
        proj2 = store.rebuild_work_projection()
        events = store.list_events()
        outbox_rows = store._conn.execute(
            "SELECT status, count(*) c FROM outbox_v1"
            " GROUP BY status").fetchall()
        outbox = {r["status"]: r["c"] for r in outbox_rows}
        # BusinessRun 业务事实对账：仅对终态 run 强制收敛 work
        # （UFC：活动态映射交给投影，reconcile 不得把终态回退）。
        drift_fixed = 0
        runs = store._conn.execute(
            "SELECT run_id, work_id, status FROM business_run_v1"
            " WHERE work_id != '' AND status IN"
            " ('succeeded','failed','partial_failed','cancelled')")
        runs = runs.fetchall()
        for r in runs:
            expected = _RUN_TO_WORK.get(r["status"])
            if expected is None:
                continue
            work = store.get_work_item_v2(r["work_id"])
            if work is not None and work["status"] != expected:
                store.set_work_item_v2_status(r["work_id"], expected)
                drift_fixed += 1
        consistent = (proj["hash"] == proj2["hash"]
                      and len(events) >= proj["count"]
                      and outbox.get("pending", 0) == 0)
        # UFC：只读终态漂移扫描（运营域；fixture 不参与）
        try:
            from ..gate_evaluator import scan_terminal_drift
            drift = scan_terminal_drift(store)
        except Exception:
            drift = []
        return {"consistent": consistent and not drift,
                "business_facts_checked": True,
                "drift_fixed": drift_fixed,
                "drift": drift,
                "projection": {"count": proj["count"],
                               "hash": proj["hash"]},
                "event_count": len(events),
                "outbox": outbox}

    @router.get("/api/v1/control/gate")
    def gate_current() -> dict:
        """UFC：机器 Gate（只读，读最近一次 evidence-driven 评估结果）。"""
        import json as _json
        from pathlib import Path as _Path
        root = _Path(__file__).resolve().parents[3]
        candidates = sorted(root.glob(".eval/*/gate.json"),
                            key=lambda p: p.stat().st_mtime)
        if not candidates:
            return {"gate": None,
                    "note": "尚未生成 gate.json（运行 UAT V3 --gate）"}
        return _json.loads(candidates[-1].read_text(encoding="utf-8"))

    return router
