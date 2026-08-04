"""M6：Jobs API（提交/poll/取消/观测）+ 分享链接（scope/有效期）。

安全边界：
- 仅允许提交已注册 handler 的 kind（未知 kind → 400）；
- 取消仅作用于 queued（running 靠 lease 过期回收），留审计痕迹；
- 分享 token fail-closed：不存在/已吊销/已过期/scope 不匹配 → 一律拒绝；
- CSRF：所有状态变更均为 JSON POST（需预检/自定义头），无简单表单可达路径。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel


class JobSubmitBody(BaseModel):
    kind: str
    payload: dict[str, Any] | None = None
    max_attempts: int = 3


def create_jobs_router(worker: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/jobs")
    def list_jobs(status: str | None = None, limit: int = 100):
        jobs = worker._store.list_jobs(status=status, limit=min(limit, 500))
        return {"stats": worker.stats(), "count": len(jobs), "jobs": jobs}

    @router.post("/api/v1/jobs")
    def submit_job(
        body: JobSubmitBody,
        x_actor: str | None = Header(default=None),
    ):
        if body.kind not in worker._handlers:
            raise HTTPException(status_code=400, detail=f"未注册 kind: {body.kind}")
        if not 1 <= body.max_attempts <= 10:
            raise HTTPException(status_code=400, detail="max_attempts 越界（1-10）")
        job_id = worker.submit(
            body.kind, body.payload, max_attempts=body.max_attempts
        )
        worker._store.append_audit(
            actor=x_actor or "api", action="job.submit",
            subject_type="job", subject_id=job_id,
            detail={"kind": body.kind},
        )
        return {"job": worker._store.get_job(job_id)}

    @router.post("/api/v1/jobs/poll")
    def poll():
        outcomes = worker.poll()
        return {"processed": len(outcomes), "outcomes": outcomes}

    @router.get("/api/v1/jobs/{job_id}")
    def get_job(job_id: str):
        try:
            job = worker._store.get_job(job_id)
        except Exception:
            raise HTTPException(status_code=404, detail="job 不存在")
        return {"job": job, "attempts": worker._store.list_attempts(job_id)}

    @router.post("/api/v1/jobs/{job_id}/cancel")
    def cancel_job(
        job_id: str,
        x_actor: str | None = Header(default=None),
    ):
        try:
            worker._store.get_job(job_id)
        except Exception:
            raise HTTPException(status_code=404, detail="job 不存在")
        ok = worker.cancel(job_id, actor=x_actor or "api")
        if not ok:
            raise HTTPException(
                status_code=409, detail="仅 queued 状态可取消（running 靠 lease 回收）"
            )
        return {"job_id": job_id, "status": "cancelled"}

    return router


class ShareBody(BaseModel):
    scope: str
    subject_id: str | None = None
    ttl_seconds: int = 3600


def create_share_router(store: Any) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/shares")
    def create_share(
        body: ShareBody,
        x_actor: str | None = Header(default=None),
    ):
        if not body.scope or not 60 <= body.ttl_seconds <= 7 * 24 * 3600:
            raise HTTPException(
                status_code=400, detail="scope 必填；ttl 限 60s–7d"
            )
        tok = store.create_share_token(
            scope=body.scope, subject_id=body.subject_id,
            ttl_seconds=body.ttl_seconds, created_by=x_actor or "api",
        )
        store.append_audit(
            actor=x_actor or "api", action="share.create",
            subject_type="share_token", subject_id=tok["token"][:8],
            detail={"scope": body.scope, "ttl_seconds": body.ttl_seconds},
        )
        return {"token": tok["token"], "scope": tok["scope"],
                "expires_at": tok["expires_at"]}

    @router.get("/api/v1/shares/{token}/check")
    def check_share(token: str, scope: str):
        row = store.validate_share_token(token, scope=scope)
        if row is None:
            raise HTTPException(
                status_code=403, detail="token 无效（不存在/已吊销/已过期/scope 不匹配）"
            )
        return {"valid": True, "scope": row["scope"], "subject_id": row["subject_id"],
                "expires_at": row["expires_at"]}

    @router.post("/api/v1/shares/{token}/revoke")
    def revoke_share(
        token: str,
        x_actor: str | None = Header(default=None),
    ):
        ok = store.revoke_share_token(token)
        if not ok:
            raise HTTPException(status_code=404, detail="token 不存在")
        store.append_audit(
            actor=x_actor or "api", action="share.revoke",
            subject_type="share_token", subject_id=token[:8],
        )
        return {"revoked": True}

    return router
