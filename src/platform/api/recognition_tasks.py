"""U2-3 + ABOS T7：识别统一任务（单文件/批量/URL/API/Agent 同源）。

四入口共用同一服务层 run_recognition_batch：
- 单文件/批量文件：POST /api/v1/recognition/tasks/upload；
- URL：POST /api/v1/recognition/tasks/url；
- API/Agent：同一 HTTP 端点（身份来自服务端 session，禁止 header 自证）。

ABOS T7 契约：请求必须携带 recognition_profile_id/service_tier/source；
服务端只接受已注册且 enabled 的 Profile ID，拒绝任意权重路径
（.pt/目录/..）；任务行与响应回显冻结后的 profile/tier/source/
project/trace。Profile resolve 由组合根注入（平台不 import 领域模块）。

每个任务落 recognition_task 行，形成统一任务历史；识别结果口径与旧
bridge（products/count）一致。
"""
from __future__ import annotations

import json
import secrets
import time
import uuid
from typing import Any, Callable

import httpx
from fastapi import APIRouter, Form, HTTPException, Request, UploadFile, File
from pydantic import BaseModel

from src.platform.adapters.legacy.recognition import RecognitionAdapterError
from src.platform.auth import AuthService, require_principal

MAX_FILES_PER_BATCH = 32
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_SOURCES = ("web", "api", "agent", "internal")
ALLOWED_TIERS = ("fast", "standard", "high", "extreme")
DEFAULT_PROFILE_ID = "production_legacy"


class ProfileResolveError(Exception):
    """profile 未注册/被禁用/输入非法（fail-closed）。"""

    def __init__(self, reason: str, *, blockers: list[str] | None = None):
        super().__init__(reason)
        self.reason = reason
        self.blockers = blockers or []


def validate_profile_input(profile_id: str) -> None:
    """结构上拒绝任意权重路径/未注册模型 ID 形式输入。"""
    if not profile_id or not isinstance(profile_id, str):
        raise ProfileResolveError("recognition_profile_id 必填")
    if len(profile_id) > 128 or any(
            c in profile_id for c in ("/", "\\", "..", "\x00")) \
            or profile_id.endswith(".pt"):
        raise ProfileResolveError(
            f"非法 profile 输入（拒绝权重路径）: {profile_id!r}")


def resolve_profile(profile_id: str,
                    profiles_service: Any | None) -> dict[str, Any]:
    """服务端解析已注册 Profile；未知/disabled fail-closed。"""
    validate_profile_input(profile_id)
    if profiles_service is None:
        raise ProfileResolveError("profile 服务未装配（fail-closed）")
    for p in profiles_service.list_profiles():
        if p["profile_id"] == profile_id:
            if p.get("status") != "enabled":
                raise ProfileResolveError(
                    f"profile {profile_id} 当前不可用",
                    blockers=p.get("blockers", []))
            return p
    raise ProfileResolveError(f"profile 未注册: {profile_id}")


def fetch_url_bytes(url: str, timeout: float = 10.0) -> bytes:
    """URL 入口下载器（可被测试 monkeypatch）。仅允许 http/https。"""
    if not url.startswith(("http://", "https://")):
        raise ValueError("仅支持 http/https URL")
    r = httpx.get(url, timeout=timeout, follow_redirects=False)
    r.raise_for_status()
    return r.content


def _replay(existing: dict[str, Any]) -> dict[str, Any]:
    """幂等重放：同一 Idempotency-Key 重复请求返回同一任务。"""
    results = json.loads(existing.get("result_json") or "[]")
    errors = [e for e in (existing.get("error") or "").split("; ") if e]
    return {
        "task": existing,
        "results": results,
        "errors": errors,
        "elapsed_ms": 0,
        "idempotent_replay": True,
        "recognition_profile_id": existing.get("recognition_profile_id", ""),
        "service_tier": existing.get("service_tier", ""),
        "trace_id": existing.get("trace_id", ""),
    }


def run_recognition_batch(
    adapter: Any, images: list[tuple[str, bytes]], *, conf: float,
    store: Any, entry: str, actor: str,
    idempotency_key: str | None = None,
    recognition_profile_id: str = DEFAULT_PROFILE_ID,
    service_tier: str = "standard", source: str = "api",
    project_id: str = "",
    profiles_service: Any | None = None,
) -> dict[str, Any]:
    """四入口共用服务层：profile resolve → 逐图识别 → 落任务行。"""
    if idempotency_key:
        hit = store.find_recognition_task_by_idempotency_key(idempotency_key)
        if hit is not None:
            return _replay(hit)
    # ABOS T7：服务端只接受已注册 enabled Profile（fail-closed）
    try:
        profile = resolve_profile(recognition_profile_id, profiles_service)
    except ProfileResolveError as e:
        raise HTTPException(
            status_code=400,
            detail={"code": "profile_rejected", "message": e.reason,
                    "blockers": e.blockers,
                    "next_action": "在“即时识别”页选择已启用的 Profile"})
    if service_tier not in ALLOWED_TIERS:
        raise HTTPException(400, f"service_tier 必须在 {ALLOWED_TIERS}")
    if source not in ALLOWED_SOURCES:
        raise HTTPException(400, f"source 必须在 {ALLOWED_SOURCES}")
    trace_id = "tr-" + uuid.uuid4().hex[:12]
    task_id = secrets.token_hex(16)
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    sku_total = 0
    t0 = time.monotonic()
    for name, data in images:
        if len(data) == 0:
            errors.append(f"{name}: 空文件")
            continue
        if len(data) > MAX_UPLOAD_BYTES:
            errors.append(f"{name}: 超过大小上限")
            continue
        try:
            up = adapter.recognize(data, conf=conf)
        except RecognitionAdapterError as e:
            errors.append(f"{name}: {e.kind}: {e.detail}")
            continue
        sku_total += int(up.get("count", 0))
        results.append({"name": name, **up})
    status = "completed" if not errors else (
        "failed" if not results else "completed")
    task = store.create_recognition_task(
        task_id=task_id, entry=entry, status=status,
        file_count=len(images), sku_count=sku_total, created_by=actor,
        result_json=json.dumps(results, ensure_ascii=False),
        error="; ".join(errors), idempotency_key=idempotency_key,
        recognition_profile_id=profile["profile_id"],
        service_tier=service_tier, source=source,
        project_id=project_id, trace_id=trace_id)
    return {
        "task": task,
        "results": results,
        "errors": errors,
        "elapsed_ms": round((time.monotonic() - t0) * 1000, 2),
        # ABOS T7：回显冻结后的 profile/tier/source/trace
        "recognition_profile_id": profile["profile_id"],
        "profile_components": profile.get("components", []),
        "profile_status": profile.get("status"),
        "service_tier": service_tier,
        "source": source,
        "trace_id": trace_id,
    }


class UrlBody(BaseModel):
    url: str
    conf: float = 0.25
    recognition_profile_id: str = DEFAULT_PROFILE_ID
    service_tier: str = "standard"
    source: str = "api"
    project_id: str = ""


def create_recognition_tasks_router(
    store: Any, adapter: Any, auth: AuthService | None = None,
    profiles_service: Any | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/recognition/profiles")
    def list_profiles() -> dict:
        """Profile 选择器数据源（运行态实时派生，不硬编码）。"""
        if profiles_service is None:
            return {"count": 0, "profiles": [],
                    "note": "profile 服务未装配"}
        profs = profiles_service.list_profiles()
        return {"count": len(profs), "profiles": profs}

    @router.post("/api/v1/recognition/tasks/upload")
    async def upload(
            files: list[UploadFile] = File(...),
            conf: float = 0.25,
            recognition_profile_id: str = Form(DEFAULT_PROFILE_ID),
            service_tier: str = Form("standard"),
            source: str = Form("web"),
            project_id: str = Form(""),
            request: Request = None):
        p = require_principal(auth, request)
        if not files or len(files) > MAX_FILES_PER_BATCH:
            raise HTTPException(
                status_code=400,
                detail=f"文件数需在 1～{MAX_FILES_PER_BATCH}")
        images = [(f.filename or f"file_{i}", await f.read())
                  for i, f in enumerate(files)]
        entry = "single_file" if len(files) == 1 else "batch_file"
        idem = request.headers.get("idempotency-key") if request else None
        return run_recognition_batch(
            adapter, images, conf=conf, store=store,
            entry=entry, actor=p["actor"], idempotency_key=idem,
            recognition_profile_id=recognition_profile_id,
            service_tier=service_tier, source=source,
            project_id=project_id, profiles_service=profiles_service)

    @router.post("/api/v1/recognition/tasks/url")
    def by_url(body: UrlBody, request: Request):
        p = require_principal(auth, request)
        idem = request.headers.get("idempotency-key")
        if idem:
            hit = store.find_recognition_task_by_idempotency_key(idem)
            if hit is not None:
                return _replay(hit)
        try:
            data = fetch_url_bytes(body.url)
        except Exception as e:
            raise HTTPException(status_code=400,
                                detail=f"URL 下载失败：{e}")
        return run_recognition_batch(
            adapter, [(body.url, data)], conf=body.conf, store=store,
            entry="url", actor=p["actor"], idempotency_key=idem,
            recognition_profile_id=body.recognition_profile_id,
            service_tier=body.service_tier, source=body.source,
            project_id=body.project_id,
            profiles_service=profiles_service)

    @router.get("/api/v1/recognition/tasks")
    def list_tasks(limit: int = 100, offset: int = 0,
                   status: str | None = None):
        tasks = store.list_recognition_tasks(
            limit=limit, offset=offset, status=status)
        total = store.count_recognition_tasks(status=status)
        return {"count": total, "tasks": tasks}

    return router
