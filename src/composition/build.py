"""组合根构建：PlatformBundle + 双 Graph 注册 + FastAPI app。"""

from __future__ import annotations

import os
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
    label_studio_adapter: Any | None = None,
    services=DEFAULT_SERVICES,
    probe=probe_service,
    engine_kwargs: dict | None = None,
) -> PlatformBundle:
    db_path = db_path or (REPO_ROOT / ".platform" / "platform.sqlite")
    cas_root = cas_root or (REPO_ROOT / ".platform" / "cas")
    store = PlatformStore(db_path)
    cas = ContentAddressedStore(cas_root, store)
    capabilities = bootstrap_default_registry(
        recognition_adapter, monitor_adapter, label_studio_adapter
    )

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


def build_labeling_router(bundle: PlatformBundle):
    """M4：组合根唯一允许同时持有 platform 与 labeling 域的位置。"""
    from src.modules.labeling import LabelingService
    from src.modules.labeling.service import predictions_from_recognition
    from src.platform.api.labeling import create_labeling_router

    ls_adapter = bundle.capabilities.get("legacy.label_studio")
    recognition = bundle.capabilities.get("legacy.recognition.v2")
    service = LabelingService(bundle.store, ls_adapter)
    label_config = (REPO_ROOT / "configs/label-studio/label_config.xml").read_text(
        encoding="utf-8"
    )

    def builder(photos):
        return predictions_from_recognition(
            recognition, photos, model_version="legacy.recognition.v2@cascade_v3"
        )

    return create_labeling_router(
        service, label_config=label_config, prediction_builder=builder
    )


def build_training_router(bundle: PlatformBundle):
    """M5：组合根唯一允许同时持有 platform 与 training_gov 域的位置。"""
    from src.modules.training_gov import TrainingGovernanceService
    from src.platform.api.training import create_training_router
    from src.platform.auth import AuthService

    return create_training_router(
        TrainingGovernanceService(bundle.store),
        auth=AuthService(bundle.store))


def build_jobs_router(bundle: PlatformBundle):
    """M6：可恢复 Job Worker（platform.echo 内置 handler）+ Jobs router。"""
    from datetime import datetime, timezone

    from src.platform.api.jobs import create_jobs_router
    from src.platform.auth import AuthService
    from src.platform.worker import RecoverableJobWorker

    def _echo(ctx):
        return {
            "echo": ctx["payload"],
            "attempt_no": ctx["attempt_no"],
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

    worker = RecoverableJobWorker(
        bundle.store,
        {"platform.echo": _echo},
        max_concurrent=int(os.environ.get("PLATFORM_WORKER_MAX_CONCURRENT", "2")),
        lease_seconds=int(os.environ.get("PLATFORM_WORKER_LEASE_SECONDS", "300")),
    )
    return worker, create_jobs_router(worker, auth=AuthService(bundle.store))


def build_share_router(bundle: PlatformBundle):
    from src.platform.api.jobs import create_share_router
    from src.platform.auth import AuthService

    return create_share_router(bundle.store, auth=AuthService(bundle.store))


def build_app_with_bundle(
    bundle: PlatformBundle | None = None,
    *,
    web_dist: Path | None = None,
    services=DEFAULT_SERVICES,
    probe=probe_service,
) -> FastAPI:
    if bundle is not None:
        _worker, jobs_router = build_jobs_router(bundle)
        share_router = build_share_router(bundle)
    else:
        jobs_router, share_router = None, None
    return create_app(
        services=services,
        probe=probe,
        web_dist=web_dist if web_dist is not None else (REPO_ROOT / "web" / "dist"),
        bundle=bundle,
        labeling_router=build_labeling_router(bundle) if bundle is not None else None,
        training_router=build_training_router(bundle) if bundle is not None else None,
        jobs_router=jobs_router,
        share_router=share_router,
    )
