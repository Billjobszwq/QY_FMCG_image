"""M5：训练治理 API（snapshot/gates/dry-run/授权/发布分离）。

平台只承载 HTTP 边界；治理逻辑在 src/modules/training_gov（经组合根注入）。
角色经 X-Actor/X-Role 头传递（本机单租户最小 IAM，fail-closed）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel


def _actor_role(
    x_actor: str | None, x_role: str | None
) -> tuple[str, str]:
    return (x_actor or "web-operator", x_role or "operator")


class SnapshotBody(BaseModel):
    name: str
    version: str
    mode: str = "product"
    manifest: dict[str, Any]
    source_conclusion: str = "人工审核通过"
    quality: dict[str, Any] | None = None


class DryRunBody(BaseModel):
    snapshot_id: str
    epochs: int = 3
    imgsz: int = 1280
    device: str = "mps"
    budget_minutes: int = 60
    stop_lines: list[str] | None = None


class AuthorizeBody(BaseModel):
    value: bool


def create_training_router(service: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/training/gates")
    def gates():
        return service.gates()

    @router.get("/api/v1/training/snapshots")
    def list_snapshots():
        snaps = service.list_snapshots()
        return {"count": len(snaps), "snapshots": snaps}

    @router.post("/api/v1/training/snapshots")
    def create_snapshot(
        body: SnapshotBody,
        x_actor: str | None = Header(default=None),
        x_role: str | None = Header(default=None),
    ):
        actor, _role = _actor_role(x_actor, x_role)
        try:
            snap = service.register_snapshot(
                body.name, body.version, body.mode, body.manifest,
                source_actor=actor, source_conclusion=body.source_conclusion,
                quality=body.quality,
            )
        except Exception as e:  # split guard 失败等
            raise HTTPException(status_code=400, detail=str(e))
        return {"snapshot": snap}

    @router.get("/api/v1/training/runs")
    def list_runs():
        runs = service.list_runs()
        return {"count": len(runs), "runs": runs}

    @router.post("/api/v1/training/runs/dry-run")
    def dry_run(
        body: DryRunBody,
        x_actor: str | None = Header(default=None),
        x_role: str | None = Header(default=None),
    ):
        actor, _role = _actor_role(x_actor, x_role)
        try:
            run = service.dry_run(
                body.snapshot_id, actor=actor, epochs=body.epochs,
                imgsz=body.imgsz, device=body.device,
                budget_minutes=body.budget_minutes, stop_lines=body.stop_lines,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="snapshot 不存在")
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"run": run}

    @router.post("/api/v1/training/authorize")
    def authorize(
        body: AuthorizeBody,
        x_actor: str | None = Header(default=None),
        x_role: str | None = Header(default=None),
    ):
        actor, role = _actor_role(x_actor, x_role)
        try:
            service.set_training_authorized(body.value, actor=actor, role=role)
        except Exception as e:
            raise HTTPException(status_code=403, detail=str(e))
        return {"training_authorized": body.value, "actor": actor}

    @router.post("/api/v1/training/runs/{run_id}/start")
    def start(
        run_id: str,
        x_actor: str | None = Header(default=None),
        x_role: str | None = Header(default=None),
    ):
        actor, role = _actor_role(x_actor, x_role)
        try:
            run = service.start_training(run_id, actor=actor, role=role)
        except KeyError:
            raise HTTPException(status_code=404, detail="run 不存在")
        except Exception as e:
            raise HTTPException(status_code=403, detail=str(e))
        return {"run": run}

    @router.post("/api/v1/training/runs/{run_id}/publish/request")
    def publish_request(
        run_id: str,
        x_actor: str | None = Header(default=None),
        x_role: str | None = Header(default=None),
    ):
        actor, role = _actor_role(x_actor, x_role)
        try:
            run = service.request_publish(run_id, actor=actor, role=role)
        except KeyError:
            raise HTTPException(status_code=404, detail="run 不存在")
        except Exception as e:
            raise HTTPException(status_code=403, detail=str(e))
        return {"run": run}

    @router.post("/api/v1/training/runs/{run_id}/publish/approve")
    def publish_approve(
        run_id: str,
        x_actor: str | None = Header(default=None),
        x_role: str | None = Header(default=None),
    ):
        actor, role = _actor_role(x_actor, x_role)
        try:
            run = service.approve_publish(run_id, actor=actor, role=role)
        except KeyError:
            raise HTTPException(status_code=404, detail="run 不存在")
        except Exception as e:
            raise HTTPException(status_code=403, detail=str(e))
        return {"run": run}

    return router
