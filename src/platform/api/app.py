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
    training_control_router=None,
    jobs_router=None,
    share_router=None,
    cascade_router=None,
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

    # no-cache-middleware：HTML 永不缓存（破坏旧版缓存），hash 资产长缓存
    @app.middleware("http")
    async def _html_nocache(request, call_next):
        resp = await call_next(request)
        ct = resp.headers.get("content-type", "")
        if "text/html" in ct:
            resp.headers["Cache-Control"] = "no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
        elif "/assets/" in request.url.path:
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp
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
        # U2-1：统一任务中心（只读聚合，角色首页数据源）
        from src.platform.api.workitems import create_workitems_router
        app.include_router(create_workitems_router(bundle.store))
        # U2-2：数据中心 Asset API（真实台账 source_asset_inventory_v1）
        from src.platform.api.assets import create_assets_router
        app.include_router(create_assets_router(bundle.store))
        # U3-6：人工质量金标准入口（status/confusion 只读；
        # build/verdict 需服务端 session+CSRF，reviewer 取登录身份）
        from src.platform.api.gold import create_gold_router
        app.include_router(create_gold_router(
            bundle.store, auth=AuthService(bundle.store)))
        # U4-2：标注审核闭环（status 只读；认领/提交/导出需
        # 服务端 session+CSRF，actor 取登录身份，仲裁仅限 admin）
        from src.platform.api.review import create_review_router
        app.include_router(create_review_router(
            bundle.store, auth=AuthService(bundle.store)))
        # GLTC Task 8：四训练通道统一控制面 router 由组合根注入
        # （依赖方向红线：src/platform 不 import src/modules）
        # SLTF §11/12/13：Agent/Blackboard/TaskBoard API
        from src.platform.api.agents_api import create_agents_router
        app.include_router(create_agents_router(
            bundle.store, auth=AuthService(bundle.store)))
        from src.platform.api.agent_runtime_api import (
            create_agent_runtime_router)
        app.include_router(create_agent_runtime_router(
            bundle.store, auth=AuthService(bundle.store)))
        from src.platform.api.recon_api import create_recon_router
        from src.platform.api.modules_api import create_modules_router
        app.include_router(create_recon_router(bundle.store))
        app.include_router(create_modules_router())
        # U5-2/U5-3：Graph+Loop v2 运行（runs/trail 登录只读；
        # start/gate 需 session+CSRF 且仅限 admin）
        from src.platform.api.loops import create_loops_router
        app.include_router(create_loops_router(
            bundle.store, auth=AuthService(bundle.store)))
        # U2-3：识别统一（单文件/批量/URL/API 共用 RecognitionTask）
        from src.platform.api.recognition_tasks import (
            create_recognition_tasks_router)
        app.include_router(create_recognition_tasks_router(
            bundle.store, rec_adapter,
            auth=AuthService(bundle.store)))
        # VLM-014：若组合根注入 cascade_service，则自动装配统一 cascade API
        if cascade_router is None and bundle.cascade_service is not None:
            from src.platform.api.cascade import create_cascade_router
            cascade_router = create_cascade_router(
                bundle.store, bundle.cascade_service,
                auth=AuthService(bundle.store),
                residency=bundle.model_residency)

    # ---- M4 Label Studio 闭环（组合根注入 router 时启用）----
    if labeling_router is not None:
        app.include_router(labeling_router)

    # ---- M5 训练治理（组合根注入 router 时启用）----
    if training_router is not None:
        app.include_router(training_router)

    # ---- GLTC 四训练通道统一控制面（组合根注入）----
    if training_control_router is not None:
        app.include_router(training_control_router)

    # ---- M6 可恢复 Job Worker + 分享链接（组合根注入 router 时启用）----
    if jobs_router is not None:
        app.include_router(jobs_router)
    if share_router is not None:
        app.include_router(share_router)

    # ---- VLM-014：统一 cascade API（shadow 默认，旧 8091/recognition 不变）----
    if cascade_router is not None:
        app.include_router(cascade_router)

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
