"""U3-6：人工质量金标准 API（只读状态 + 登录身份写入口）。

- GET /api/v1/quality/gold/status：队列与 waiting_human/done 进度；
- GET /api/v1/quality/gold/confusion：仅对有人工结论的对计算混淆矩阵；
- POST /api/v1/quality/gold/build：分层建队（需登录 session+CSRF）；
- POST /api/v1/quality/gold/verdict：人工结论，reviewer 强制取服务端
  session 身份（禁止客户端自证）；人工未完成只能显示 waiting_human。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..auth import AuthService, require_principal
from ..quality.gold import (build_gold_queue, confusion_matrix,
                            gold_status, submit_human_verdict)

REPO_ROOT = Path(__file__).resolve().parents[3]


class BuildBody(BaseModel):
    size: int = Field(default=500, ge=1, le=1000)


class VerdictBody(BaseModel):
    sha256: str
    verdict: str
    dims: dict | None = None


def create_gold_router(store, auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["quality-gold"])

    @router.get("/api/v1/quality/gold/status")
    def status() -> dict:
        st = gold_status(store)
        return {**st,
                "note": "人工未完成只能显示 waiting_human，禁止伪造通过"}

    @router.get("/api/v1/quality/gold/confusion")
    def confusion() -> dict:
        return confusion_matrix(store)

    @router.post("/api/v1/quality/gold/build")
    def build(body: BuildBody, request: Request) -> dict:
        require_principal(auth, request)
        return build_gold_queue(store, size=body.size, root=REPO_ROOT)

    @router.post("/api/v1/quality/gold/verdict")
    def verdict(body: VerdictBody, request: Request) -> dict:
        p = require_principal(auth, request)
        try:
            return submit_human_verdict(
                store, sha256=body.sha256, verdict=body.verdict,
                reviewer=p["actor"], dims=body.dims)
        except ValueError as e:
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(e))

    return router
