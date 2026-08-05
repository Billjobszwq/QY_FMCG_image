"""U4-2：标注审核闭环 API（链接派发/认领/提交/导出）。

口径（与 quality/gold 一致）：
- 只读 status 公开；其余端点强制服务端 session+CSRF，
  actor 一律取登录身份（禁止客户端 header 自证）；
- 仲裁（role=arbiter）仅 admin；
- SAM prediction 永远不是最终标注，final_box 只来自人工终态；
- 队列任务不得伪造完成：无终态事件的任务一律显示进行中状态。
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..annotate.review import (claim_task, export_review, final_box,
                               submit_review, task_view, _derive_status)
from ..auth import AuthService, require_principal

REPO_ROOT = Path(__file__).resolve().parents[3]


class ClaimBody(BaseModel):
    claim_token: str


class SubmitBody(BaseModel):
    task_id: str
    verdict: str
    box: list[float]
    role: str = "annotator"


def create_review_router(store, auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["review"])

    @router.get("/api/v1/review/status")
    def status() -> dict:
        tasks = store.list_review_tasks()
        dist: dict[str, int] = {}
        for t in tasks:
            st = _derive_status(store, t)["status"]
            dist[st] = dist.get(st, 0) + 1
        return {
            "n_tasks": len(tasks),
            "status_distribution": dist,
            "note": "final_box 只来自人工终态；未完成任务不得伪造完成",
        }

    @router.get("/api/v1/review/tasks")
    def tasks(request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        items = []
        for t in store.list_review_tasks(limit=5000):
            st = _derive_status(store, t)
            items.append({**st, "claim_token": t["claim_token"]})
        return {"n_tasks": len(items), "tasks": items}

    @router.get("/api/v1/review/task/by-token/{claim_token}")
    def task_by_token(claim_token: str, request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        try:
            return task_view(store, claim_token)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @router.post("/api/v1/review/claim")
    def claim(body: ClaimBody, request: Request) -> dict:
        p = require_principal(auth, request)
        try:
            return claim_task(store, body.claim_token, actor=p["actor"])
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @router.post("/api/v1/review/submit")
    def submit(body: SubmitBody, request: Request) -> dict:
        p = require_principal(auth, request)
        role = body.role
        if role == "arbiter" and p.get("role") != "admin":
            raise HTTPException(status_code=403,
                                detail="仲裁仅限 admin 角色")
        try:
            return submit_review(store, task_id=body.task_id,
                                 actor=p["actor"], verdict=body.verdict,
                                 box=body.box, role=role)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @router.get("/api/v1/review/task/{task_id}/final-box")
    def fbox(task_id: str, request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        try:
            return {"task_id": task_id,
                    "final_box": final_box(store, task_id)}
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @router.post("/api/v1/review/export")
    def export(request: Request) -> dict:
        p = require_principal(auth, request)
        if p.get("role") != "admin":
            raise HTTPException(status_code=403, detail="导出仅限 admin")
        ts = time.strftime("%Y%m%d_%H%M%S")
        out = REPO_ROOT / ".eval" / "u4" / f"review_export_{ts}.json"
        return export_review(store, out)

    return router
