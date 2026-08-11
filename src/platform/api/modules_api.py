"""ABOS T3：模块注册表 API —— 只消费 ModuleManifestV2 投影。

本文件不再持有任何业务模块常量（唯一事实源在
src/platform/module_catalog.py + registry.ModuleRegistry）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from ..module_catalog import PLATFORM_IDENTITY
from ..registry import ModuleRegistry

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _current_production() -> dict[str, Any]:
    """production bundle 实时读取（不硬编码；缺失时诚实返回）。"""
    f = _REPO_ROOT / ".models" / "bundles" / "CURRENT.json"
    if not f.is_file():
        return {"bundle_id": None, "source": str(f), "found": False}
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        return {"bundle_id": d.get("bundle_id"),
                "previous": d.get("previous"),
                "published_at": d.get("published_at"),
                "source": str(f), "found": True}
    except Exception as e:  # 读取失败不谎报
        return {"bundle_id": None, "found": False,
                "source": str(f), "error": str(e)}


def create_modules_router(
    module_registry: ModuleRegistry,
    *,
    capability_registry: Any | None = None,
    degraded_modules: set[str] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["modules"])

    @router.get("/api/v1/platform/identity")
    def identity() -> dict:
        """平台唯一身份（登录/标题/footer/OpenAPI/Agent prompt 共用）。"""
        return dict(PLATFORM_IDENTITY)

    @router.get("/api/v1/platform/production")
    def production() -> dict:
        """当前 production bundle（运行态实时读取）。"""
        return _current_production()

    @router.get("/api/v1/modules")
    def modules() -> dict:
        proj = module_registry.project(degraded=degraded_modules)
        return {"count": len(proj), "modules": proj,
                "source": "ModuleManifestV2",
                "contract": "导航/Agent/API/权限/UI 均由 Module Manifest V2 "
                            "单一事实源投影；新模块注册 manifest 即接入"}

    @router.get("/api/v1/modules/{module_id}")
    def module_detail(module_id: str) -> dict:
        m = module_registry.get(module_id)
        if m is None:
            raise HTTPException(404, f"module 未注册: {module_id}")
        return next(x for x in module_registry.project(
            degraded=degraded_modules) if x["module_id"] == module_id)

    @router.get("/api/v1/reference/echo")
    def reference_echo(text: str = "hello") -> dict:
        """reference.echo：非识别模块证明平台内核没有绑定 FMCG。"""
        if capability_registry is None:
            raise HTTPException(503, "capability registry 未装配")
        adapter = capability_registry.get("reference.echo")
        return adapter.echo(text)

    return router
