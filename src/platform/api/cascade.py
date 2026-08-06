"""Task 14（VLM-014）：统一 cascade API（shadow 默认，旧 8091/recognition 不变）。

端点（7 个）：
- POST /api/v1/cascade/tasks          提交级联任务（session+CSRF）
- GET  /api/v1/cascade/tasks          任务列表（登录只读）
- GET  /api/v1/cascade/tasks/{id}     任务详情 + 终局结果（登录只读）
- GET  /api/v1/cascade/tasks/{id}/regions   检测区域（登录只读）
- GET  /api/v1/cascade/tasks/{id}/trail     决策轨迹（登录只读）
- POST /api/v1/cascade/tasks/{id}/cancel    取消（session+CSRF）
- GET  /api/v1/models/runtime         模型驻留状态（登录只读）

红线：
- 请求只接受 customer tier、source 与已批准选项；任意 file path/model/
  prompt/graph 定义字段一律拒绝（pydantic extra=forbid → 422）；
- 单文件/批量/URL/API/内部 Agent 共用同一 RecognitionTask 台账（entry 区分）；
- URL SSRF 防护沿用现有规则：仅 http/https，拒绝 localhost/私网/链路本地；
- 默认 shadow：不改变 /api/v1/recognition/recognize 与 8091 行为。
"""

from __future__ import annotations

import ipaddress
import json
import secrets
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from ..auth import AuthService, require_principal
from ..data.store import StoreError

TIERS = ("fast", "standard", "deep", "expert")
SOURCES = ("single_file", "batch_file", "url", "api", "agent")
_ENTRY_PREFIX = "cascade_"


class CascadeTaskBody(BaseModel):
    """只允许已批准字段；file_path/model/prompt/graph 等额外字段 → 422。"""

    model_config = ConfigDict(extra="forbid")

    tier: str
    source: str
    asset: dict[str, Any] | None = None
    url: str | None = None


def validate_cascade_url(url: str) -> None:
    """SSRF 防护（沿用平台现有规则）：仅 http/https，拒绝内网/本机地址。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"仅支持 http/https URL（拒绝 {parsed.scheme or '空'}）")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("URL 缺少主机名")
    if host == "localhost":
        raise ValueError("拒绝本机地址（SSRF 防护）")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    ):
        raise ValueError("拒绝私网/保留地址（SSRF 防护）")


def _cascade_task(store, task_id: str) -> dict[str, Any]:
    task = store.get_recognition_task(task_id)
    if task is None or not str(task.get("entry", "")).startswith(_ENTRY_PREFIX):
        raise HTTPException(status_code=404, detail="cascade 任务不存在")
    return task


def _run_id_of(task: dict[str, Any]) -> str | None:
    try:
        return (json.loads(task.get("result_json") or "{}") or {}).get("run_id")
    except (TypeError, ValueError):
        return None


def create_cascade_router(
    store: Any,
    service: Any,
    *,
    auth: AuthService | None,
    residency: Any = None,
) -> APIRouter:
    router = APIRouter(tags=["cascade"])

    @router.post("/api/v1/cascade/tasks")
    def submit_task(body: CascadeTaskBody, request: Request):
        p = require_principal(auth, request)
        if body.tier not in TIERS:
            raise HTTPException(
                status_code=400,
                detail=f"未知客户档位: {body.tier}（合法 {', '.join(TIERS)}）")
        if body.source not in SOURCES:
            raise HTTPException(
                status_code=400,
                detail=f"未知入口: {body.source}（合法 {', '.join(SOURCES)}）")
        if body.source == "url":
            if not body.url:
                raise HTTPException(status_code=400, detail="url 入口缺少 url")
            try:
                validate_cascade_url(body.url)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
        if not body.asset:
            raise HTTPException(status_code=400,
                                detail="缺少 asset（asset_id/sha256/宽高）")

        idem = request.headers.get("idempotency-key")
        if idem:
            hit = store.find_recognition_task_by_idempotency_key(idem)
            if hit is not None:
                return {"task": hit, "run_id": _run_id_of(hit),
                        "idempotent_replay": True}

        out = service.submit(body.asset, tier=body.tier, idempotency_key=idem)
        run_id = out.get("run_id")
        task = store.create_recognition_task(
            task_id=secrets.token_hex(16),
            entry=_ENTRY_PREFIX + body.source,
            status="completed" if out.get("status") == "completed"
            else str(out.get("status") or "running"),
            file_count=1,
            sku_count=0,
            created_by=p["actor"],
            result_json=json.dumps({"run_id": run_id, "tier": body.tier,
                                    "source": body.source},
                                   ensure_ascii=False),
            idempotency_key=idem,
        )
        store.append_audit(actor=p["actor"], action="cascade.task_submitted",
                           subject_type="recognition_task",
                           subject_id=task["task_id"],
                           detail={"run_id": run_id, "tier": body.tier,
                                   "source": body.source})
        return {"task": task, "run_id": run_id,
                "status": out.get("status"),
                "production_switch": False}  # shadow 默认

    @router.get("/api/v1/cascade/tasks")
    def list_tasks(request: Request, limit: int = 100, offset: int = 0):
        require_principal(auth, request, csrf=False)
        rows = [t for t in store.list_recognition_tasks(
            limit=max(limit, 1) + offset, offset=0)
            if str(t.get("entry", "")).startswith(_ENTRY_PREFIX)]
        return {"count": len(rows), "tasks": rows[offset:offset + limit]}

    @router.get("/api/v1/cascade/tasks/{task_id}")
    def task_detail(task_id: str, request: Request):
        require_principal(auth, request, csrf=False)
        task = _cascade_task(store, task_id)
        run_id = _run_id_of(task)
        final = service.result(run_id) if run_id else None
        return {"task": task, "run_id": run_id, "result": final}

    @router.get("/api/v1/cascade/tasks/{task_id}/regions")
    def task_regions(task_id: str, request: Request):
        require_principal(auth, request, csrf=False)
        task = _cascade_task(store, task_id)
        run_id = _run_id_of(task)
        regions: list[dict[str, Any]] = []
        if run_id:
            for node in store.list_nodes(run_id):
                if node.get("node_name") != "detect":
                    continue
                try:
                    out = json.loads(node.get("output_json") or "{}")
                except (TypeError, ValueError):
                    continue
                regions.extend(out.get("regions") or [])
        return {"task_id": task_id, "run_id": run_id, "regions": regions}

    @router.get("/api/v1/cascade/tasks/{task_id}/trail")
    def task_trail(task_id: str, request: Request):
        require_principal(auth, request, csrf=False)
        task = _cascade_task(store, task_id)
        run_id = _run_id_of(task)
        trail = service.trail(run_id) if run_id else []
        return {"task_id": task_id, "run_id": run_id, "trail": trail}

    @router.post("/api/v1/cascade/tasks/{task_id}/cancel")
    def cancel_task(task_id: str, request: Request):
        p = require_principal(auth, request)
        task = _cascade_task(store, task_id)
        run_id = _run_id_of(task)
        if run_id:
            try:
                store.set_run_status(run_id, "cancelled")
            except StoreError:
                pass  # run 可能已终态或不存在（shadow 记录缺失不阻断）
        store.append_audit(actor=p["actor"], action="cascade.task_cancelled",
                           subject_type="recognition_task",
                           subject_id=task_id,
                           detail={"run_id": run_id})
        return {"task_id": task_id, "run_id": run_id,
                "status": "cancelled"}

    @router.get("/api/v1/models/runtime")
    def models_runtime(request: Request):
        require_principal(auth, request, csrf=False)
        models = residency.models() if residency is not None else []
        return {"count": len(models), "models": models}

    return router
