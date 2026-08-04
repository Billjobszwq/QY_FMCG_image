"""U2-3：识别统一（单文件/批量/URL/API/Agent 共用 RecognitionTask）。

四入口共用同一服务层 run_recognition_batch：
- 单文件/批量文件：POST /api/v1/recognition/tasks/upload；
- URL：POST /api/v1/recognition/tasks/url；
- API/Agent：同一 HTTP 端点（身份来自服务端 session，禁止 header 自证）。

每个任务落 recognition_task 行（entry/file_count/sku_count/结果），
形成统一任务历史；识别结果口径与旧 bridge（products/count）一致。
"""
from __future__ import annotations

import json
import secrets
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel

from src.platform.adapters.legacy.recognition import RecognitionAdapterError
from src.platform.auth import AuthService, require_principal

MAX_FILES_PER_BATCH = 32
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def fetch_url_bytes(url: str, timeout: float = 10.0) -> bytes:
    """URL 入口下载器（可被测试 monkeypatch）。仅允许 http/https。"""
    if not url.startswith(("http://", "https://")):
        raise ValueError("仅支持 http/https URL")
    r = httpx.get(url, timeout=timeout, follow_redirects=False)
    r.raise_for_status()
    return r.content


def run_recognition_batch(
    adapter: Any, images: list[tuple[str, bytes]], *, conf: float,
    store: Any, entry: str, actor: str,
) -> dict[str, Any]:
    """四入口共用服务层：逐图识别 → 落任务行 → 返回 task+results。"""
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
        error="; ".join(errors))
    return {
        "task": task,
        "results": results,
        "errors": errors,
        "elapsed_ms": round((time.monotonic() - t0) * 1000, 2),
    }


class UrlBody(BaseModel):
    url: str
    conf: float = 0.25


def create_recognition_tasks_router(
    store: Any, adapter: Any, auth: AuthService | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/recognition/tasks/upload")
    async def upload(files: list[UploadFile] = File(...),
                     conf: float = 0.25, request: Request = None):
        p = require_principal(auth, request)
        if not files or len(files) > MAX_FILES_PER_BATCH:
            raise HTTPException(
                status_code=400,
                detail=f"文件数需在 1～{MAX_FILES_PER_BATCH}")
        images = [(f.filename or f"file_{i}", await f.read())
                  for i, f in enumerate(files)]
        entry = "single_file" if len(files) == 1 else "batch_file"
        return run_recognition_batch(
            adapter, images, conf=conf, store=store,
            entry=entry, actor=p["actor"])

    @router.post("/api/v1/recognition/tasks/url")
    def by_url(body: UrlBody, request: Request):
        p = require_principal(auth, request)
        try:
            data = fetch_url_bytes(body.url)
        except Exception as e:
            raise HTTPException(status_code=400,
                                detail=f"URL 下载失败：{e}")
        return run_recognition_batch(
            adapter, [(body.url, data)], conf=body.conf, store=store,
            entry="url", actor=p["actor"])

    @router.get("/api/v1/recognition/tasks")
    def list_tasks(limit: int = 100):
        tasks = store.list_recognition_tasks(limit=limit)
        return {"count": len(tasks), "tasks": tasks}

    return router
