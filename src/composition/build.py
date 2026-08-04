"""组合根构建：PlatformBundle + 双 Graph 注册 + FastAPI app。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI

from src.modules import fmcg as fmcg_pack
from src.modules import system_health as health_pack
from src.platform.api.app import create_app
from src.platform.api.bundle import PlatformBundle
from src.platform.api.health import DEFAULT_SERVICES, probe_service
from src.platform.assets.cas import ContentAddressedStore
from src.platform.data.store import PlatformStore
from src.platform.kernel.definition import GraphRegistry
from src.platform.kernel.engine import GraphEngine
from src.platform.registry import bootstrap_default_registry

REPO_ROOT = Path(__file__).resolve().parents[2]


def build_production_bundle(
    *,
    db_path: Path | None = None,
    cas_root: Path | None = None,
    recognition_adapter: Any | None = None,
    monitor_adapter: Any | None = None,
    services=DEFAULT_SERVICES,
    probe=probe_service,
    engine_kwargs: dict | None = None,
) -> PlatformBundle:
    db_path = db_path or (REPO_ROOT / ".platform" / "platform.sqlite")
    cas_root = cas_root or (REPO_ROOT / ".platform" / "cas")
    store = PlatformStore(db_path)
    cas = ContentAddressedStore(cas_root, store)
    capabilities = bootstrap_default_registry(recognition_adapter, monitor_adapter)

    graphs = GraphRegistry()
    graphs.register(fmcg_pack.DEFINITION)
    graphs.register(health_pack.DEFINITION)

    engine = GraphEngine(store, graphs, **(engine_kwargs or {}))
    handlers = {
        fmcg_pack.GRAPH_NAME: fmcg_pack.build_handlers(
            capabilities=capabilities, cas=cas, store=store
        ),
        health_pack.GRAPH_NAME: health_pack.build_handlers(
            services=services, probe=probe, store=store
        ),
    }
    return PlatformBundle(
        store=store, cas=cas, capabilities=capabilities, graphs=graphs,
        engine=engine, handlers=handlers,
    )


def build_app_with_bundle(
    bundle: PlatformBundle | None = None,
    *,
    web_dist: Path | None = None,
    services=DEFAULT_SERVICES,
    probe=probe_service,
) -> FastAPI:
    return create_app(
        services=services,
        probe=probe,
        web_dist=web_dist if web_dist is not None else (REPO_ROOT / "web" / "dist"),
        bundle=bundle,
    )
