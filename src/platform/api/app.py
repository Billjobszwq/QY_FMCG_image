"""W1 统一 API 应用工厂：FastAPI 控制面（8400，前缀 /api/v1）。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .health import DEFAULT_SERVICES, aggregate_platform, probe_service

PLATFORM_VERSION = "0.1.0"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_app(
    services=DEFAULT_SERVICES,
    probe=probe_service,
    web_dist: Path | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Unified Platform API",
        version=PLATFORM_VERSION,
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
    )

    @app.get("/api/v1/version")
    def version():
        return {"platform": "platform-v2", "version": PLATFORM_VERSION}

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
