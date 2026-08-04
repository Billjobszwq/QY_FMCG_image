"""M5：训练治理 API（snapshot/gates/dry-run/授权/发布分离）。

平台只承载 HTTP 边界；治理逻辑在 src/modules/training_gov（经组合根注入）。
UMT-003：Snapshot 只能由服务端 builder 生成，不再接受客户端自由
manifest JSON；注册入口返回 410，改用 /snapshots/build。
UMT-006：写端点只信任服务端登录 session + CSRF token；X-Actor/X-Role
头不再作为身份依据（禁止客户端自证）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.platform.auth import AuthService, require_principal


class SnapshotBody(BaseModel):
    name: str
    version: str
    mode: str = "product"
    manifest: dict[str, Any] | None = None
    source_conclusion: str = "人工审核通过"
    quality: dict[str, Any] | None = None


class BuildEntry(BaseModel):
    path: str
    label_path: str
    photo_id: str
    store: str
    session: str
    split: str
    review_status: str
    quality_status: str


class BuildSnapshotBody(BaseModel):
    name: str
    version: str
    mode: str = "product"
    entries: list[BuildEntry]
    protocol_dir: str | None = None


class DryRunBody(BaseModel):
    snapshot_id: str
    epochs: int = 3
    imgsz: int = 960
    device: str = "mps"
    budget_minutes: int = 60
    stop_lines: list[str] | None = None


class AuthorizeBody(BaseModel):
    value: bool


def create_training_router(service: Any,
                           auth: AuthService | None = None) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/training/gates")
    def gates():
        return service.gates()

    @router.get("/api/v1/training/snapshots")
    def list_snapshots():
        snaps = service.list_snapshots()
        return {"count": len(snaps), "snapshots": snaps}

    @router.post("/api/v1/training/snapshots")
    def create_snapshot(body: SnapshotBody):
        """UMT-003：自由 JSON manifest 注册已禁用（410）。"""
        raise HTTPException(
            status_code=410,
            detail=("客户端自由 manifest/自由文本审核结论已禁用；"
                    "Snapshot 必须由服务端 builder 生成："
                    "POST /api/v1/training/snapshots/build"))

    @router.post("/api/v1/training/snapshots/build")
    def build_snapshot(body: BuildSnapshotBody, request: Request):
        p = require_principal(auth, request)
        import os
        from pathlib import Path
        datasets_root = Path(os.environ.get(
            "PLATFORM_DATASETS_ROOT", ".datasets"))
        try:
            out = service.build_and_register_snapshot(
                body.name, body.version, body.mode,
                [e.model_dump() for e in body.entries],
                actor=p["actor"], datasets_root=datasets_root,
                protocol_dir=(Path(body.protocol_dir)
                              if body.protocol_dir else None))
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        return out

    @router.get("/api/v1/training/runs")
    def list_runs():
        runs = service.list_runs()
        return {"count": len(runs), "runs": runs}

    @router.post("/api/v1/training/runs/dry-run")
    def dry_run(body: DryRunBody, request: Request):
        p = require_principal(auth, request)
        try:
            run = service.dry_run(
                body.snapshot_id, actor=p["actor"], epochs=body.epochs,
                imgsz=body.imgsz, device=body.device,
                budget_minutes=body.budget_minutes, stop_lines=body.stop_lines,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="snapshot 不存在")
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"run": run}

    @router.post("/api/v1/training/authorize")
    def authorize(body: AuthorizeBody, request: Request):
        p = require_principal(auth, request)
        try:
            service.set_training_authorized(
                body.value, actor=p["actor"], role=p["role"])
        except Exception as e:
            raise HTTPException(status_code=403, detail=str(e))
        return {"training_authorized": body.value, "actor": p["actor"]}

    @router.post("/api/v1/training/runs/{run_id}/start")
    def start(run_id: str, request: Request):
        p = require_principal(auth, request)
        try:
            run = service.start_training(
                run_id, actor=p["actor"], role=p["role"])
        except KeyError:
            raise HTTPException(status_code=404, detail="run 不存在")
        except Exception as e:
            raise HTTPException(status_code=403, detail=str(e))
        return {"run": run}

    @router.post("/api/v1/training/runs/{run_id}/publish/request")
    def publish_request(run_id: str, request: Request):
        p = require_principal(auth, request)
        try:
            run = service.request_publish(
                run_id, actor=p["actor"], role=p["role"])
        except KeyError:
            raise HTTPException(status_code=404, detail="run 不存在")
        except Exception as e:
            raise HTTPException(status_code=403, detail=str(e))
        return {"run": run}

    @router.post("/api/v1/training/runs/{run_id}/publish/approve")
    def publish_approve(run_id: str, request: Request):
        p = require_principal(auth, request)
        try:
            run = service.approve_publish(
                run_id, actor=p["actor"], role=p["role"])
        except KeyError:
            raise HTTPException(status_code=404, detail="run 不存在")
        except Exception as e:
            raise HTTPException(status_code=403, detail=str(e))
        return {"run": run}

    return router
