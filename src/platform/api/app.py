"""W1 统一 API 应用工厂：FastAPI 控制面（8400，前缀 /api/v1）。"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..adapters.legacy.monitor import MonitorAdapter, MonitorAdapterError
from ..adapters.legacy.recognition import (
    CAPABILITY_ID as RECOGNITION_CAPABILITY,
    RecognitionAdapterError,
    RecognitionV2Adapter,
)
from ..registry import CapabilityRegistry, bootstrap_default_registry
from .bundle import PlatformBundle
from .context import install_request_context_middleware
from .health import DEFAULT_SERVICES, aggregate_platform, probe_service
from .runs import create_runs_router

PLATFORM_VERSION = "0.1.0"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB；超限 413，与 8091 限制对齐


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_app(
    services=DEFAULT_SERVICES,
    probe=probe_service,
    web_dist: Path | None = None,
    recognition_adapter: RecognitionV2Adapter | None = None,
    monitor_adapter: MonitorAdapter | None = None,
    registry: CapabilityRegistry | None = None,
    bundle: PlatformBundle | None = None,
    labeling_router=None,
    training_router=None,
    jobs_router=None,
    share_router=None,
) -> FastAPI:
    app = FastAPI(
        title="Unified Platform API",
        version=PLATFORM_VERSION,
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
    )
    # M6 CORS 白名单：仅显式配置的 Origin 授予跨域（默认拒绝 = 浏览器同源策略）。
    # CSRF：状态变更端点均为 JSON body/自定义头，非白名单 Origin 预检被拒。
    origins = [
        o.strip()
        for o in os.environ.get("PLATFORM_CORS_ORIGINS", "").split(",")
        if o.strip()
    ]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "X-Actor", "X-Role", "X-Request-Id",
                           "X-CSRF-Token"],
            allow_credentials=True,
        )
    install_request_context_middleware(app)
    rec_adapter = recognition_adapter or RecognitionV2Adapter()
    mon_adapter = monitor_adapter or MonitorAdapter()
    cap_registry = registry or bootstrap_default_registry(rec_adapter, mon_adapter)

    @app.get("/api/v1/version")
    def version():
        return {"platform": "platform-v2", "version": PLATFORM_VERSION}

    # ---- W6/M2 Capability Registry（模块经 Manifest 注册，不直接 import）----
    @app.get("/api/v1/capabilities")
    def capabilities():
        caps = cap_registry.capabilities()
        return {"count": len(caps), "capabilities": caps}

    # ---- W9/W10 Graph Runs（组合根注入 bundle 时启用）----
    if bundle is not None:
        app.include_router(create_runs_router(bundle))
        # UMT-006：本机登录 session/CSRF（身份不再由客户端 header 自证）
        from src.platform.auth import AuthService, create_auth_router
        app.include_router(create_auth_router(AuthService(bundle.store)))

    # ---- M4 Label Studio 闭环（组合根注入 router 时启用）----
    if labeling_router is not None:
        app.include_router(labeling_router)

    # ---- M5 训练治理（组合根注入 router 时启用）----
    if training_router is not None:
        app.include_router(training_router)

    # ---- M6 可恢复 Job Worker + 分享链接（组合根注入 router 时启用）----
    if jobs_router is not None:
        app.include_router(jobs_router)
    if share_router is not None:
        app.include_router(share_router)

    @app.get("/api/v1/health")
    def health():
        pairs = [(spec, probe(spec)) for spec in services]
        return {
            "status": aggregate_platform(pairs),
            "generated_at": _utcnow_iso(),
            "services": [
                {**st.to_dict(), "critical": spec.critical, "description": spec.description}
                for spec, st in pairs
            ],
        }

    # ---- W4 Recognition bridge（legacy.recognition.v2 → 8091）----
    @app.post("/api/v1/recognition/recognize")
    async def recognize(file: UploadFile = File(...), conf: float = 0.25):
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="payload too large")
        if len(data) == 0:
            raise HTTPException(status_code=400, detail="empty file")
        t0 = time.monotonic()
        try:
            upstream = rec_adapter.recognize(data, conf=conf)
        except RecognitionAdapterError as e:
            status = {
                "bad_request": 400,
                "overloaded": 429,
                "model_unavailable": 503,
                "timeout": 504,
            }.get(e.kind, 502)
            return JSONResponse(
                status_code=status,
                content={"error": e.kind, "detail": e.detail, "capability": RECOGNITION_CAPABILITY},
            )
        return {
            "capability": RECOGNITION_CAPABILITY,
            "bridge_elapsed_ms": round((time.monotonic() - t0) * 1000, 2),
            **upstream,
        }

    # ---- 8092 监控只读代理（legacy.training.monitor）----
    @app.get("/api/v1/monitor/live")
    def monitor_live():
        try:
            return mon_adapter.live()
        except MonitorAdapterError as e:
            raise HTTPException(status_code=503, detail=f"{e.kind}: {e.detail}")

    @app.get("/api/v1/monitor/overview")
    def monitor_overview():
        try:
            return mon_adapter.overview()
        except MonitorAdapterError as e:
            raise HTTPException(status_code=503, detail=f"{e.kind}: {e.detail}")

    # 静态托管 React Web Shell 构建产物；未构建时返回明确 JSON（不谎报）
    if web_dist is not None and web_dist.is_dir():
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="web")
    else:

        @app.get("/")
        def root():
            return JSONResponse(
                {
                    "platform": "platform-v2",
                    "web_shell": "not_built",
                    "hint": "web/dist 尚未构建；API 在 /api/v1/health",
                }
            )

    return app
