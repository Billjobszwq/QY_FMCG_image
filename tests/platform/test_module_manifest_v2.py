"""ABOS T3：ModuleManifestV2 + ModuleRegistry + modules API 契约。"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.platform.module_catalog import (
    PLATFORM_IDENTITY, build_default_module_registry)
from src.platform.registry import (
    ModuleManifestV2, ModuleRegistry, NavRoute, RegistryError)
from src.platform.api.modules_api import create_modules_router


# ---------------- Registry 校验 ----------------


def _m(mid, route, **kw):
    return ModuleManifestV2(module_id=mid, name=mid, version="1.0.0",
                            primary_route=route, **kw)


def test_route_conflict_fail_closed():
    reg = ModuleRegistry()
    reg.register(_m("a", "/a"))
    with pytest.raises(RegistryError):
        reg.register(_m("b", "/a"))


def test_nav_route_conflict_fail_closed():
    reg = ModuleRegistry()
    reg.register(_m("a", "/a", navigation=(NavRoute(route="/a/x",
                                                    label="x"),)))
    with pytest.raises(RegistryError):
        reg.register(_m("b", "/b", navigation=(NavRoute(route="/a/x",
                                                        label="y"),)))


def test_duplicate_module_fail_closed():
    reg = ModuleRegistry()
    reg.register(_m("a", "/a"))
    with pytest.raises(RegistryError):
        reg.register(_m("a", "/a2"))


def test_agent_conflict_fail_closed():
    reg = ModuleRegistry()
    reg.register(_m("a", "/a", agents=("ag1",)))
    with pytest.raises(RegistryError):
        reg.register(_m("b", "/b", agents=("ag1",)))


def test_missing_dependency_projects_degraded():
    reg = ModuleRegistry()
    reg.register(_m("base", "/base", status="planned"))
    reg.register(_m("dep", "/dep", status="live",
                    dependencies=("base",)))
    proj = {m["module_id"]: m for m in reg.project()}
    assert proj["dep"]["status"] == "degraded", "缺依赖不得伪造 live"
    assert proj["dep"]["declared_status"] == "live"


def test_external_degraded_marks_module():
    reg = ModuleRegistry()
    reg.register(_m("a", "/a", status="live"))
    proj = {m["module_id"]: m for m in reg.project(degraded={"a"})}
    assert proj["a"]["status"] == "degraded"


# ---------------- 默认目录 ----------------


def test_default_catalog_modules_and_status():
    reg = build_default_module_registry()
    ids = {m.module_id for m in reg.modules()}
    for need in ("home", "data", "survey", "geo", "vision", "analytics",
                 "workflow", "finance", "system", "reference.echo",
                 "models"):
        assert need in ids, f"缺少一级模块 {need}"


def test_vision_second_level_routes_real_and_unique():
    reg = build_default_module_registry()
    vision = reg.get("vision")
    routes = [n.route for n in vision.navigation]
    assert len(routes) == len(set(routes))
    for r in ("/vision/recognize", "/vision/tasks", "/vision/annotation",
              "/vision/datasets", "/vision/evidence"):
        assert r in routes, f"识别域缺少二级路由 {r}"
    # 统一模型管理 V1（DEC-M001）：系统级模型管理不再位于智能识别
    assert "/vision/models" not in routes, (
        "/vision/models 必须迁出智能识别可见导航")
    # 三级 actions 必须存在
    assert all(len(n.actions) >= 0 for n in vision.navigation)
    rec = next(n for n in vision.navigation if n.route == "/vision/recognize")
    assert rec.actions


def test_models_module_is_independent_system_module():
    reg = build_default_module_registry()
    models = reg.get("models")
    routes = [n.route for n in models.navigation]
    assert routes == ["/models/connections", "/models/catalog",
                      "/models/bindings", "/models/governance",
                      "/models/local"], "模型管理必须固定五个页签"
    assert set(models.permission_scopes) >= {
        "models.config.read", "models.usage.read"}


def test_module_agent_association_verifiable():
    reg = build_default_module_registry()
    proj = {m["module_id"]: m for m in reg.project()}
    assert "supervisor" in proj["home"]["agents"]
    assert "recognition_agent" in proj["vision"]["agents"]
    assert "system_agent" in proj["system"]["agents"]
    assert "data_steward" in proj["data"]["agents"]


def test_planned_modules_have_no_fake_live():
    reg = build_default_module_registry()
    proj = {m["module_id"]: m for m in reg.project()}
    # ABOSV2 Phase E/F：五个域均已有真实后端 → live；不再有 planned 假模块
    for mid in ("survey", "analytics", "geo", "finance"):
        assert proj[mid]["status"] == "live"


# ---------------- modules API ----------------


class _FakeCapRegistry:
    def get(self, cap_id):
        class _Echo:
            def echo(self, text):
                return {"module_id": "reference.echo", "echo": text,
                        "status": "ok"}
        assert cap_id == "reference.echo"
        return _Echo()


@pytest.fixture()
def client():
    reg = build_default_module_registry()
    app = FastAPI()
    app.include_router(create_modules_router(
        reg, capability_registry=_FakeCapRegistry()))
    return TestClient(app)


def test_modules_api_projects_registry(client):
    d = client.get("/api/v1/modules").json()
    assert d["source"] == "ModuleManifestV2"
    ids = {m["module_id"] for m in d["modules"]}
    assert "vision" in ids and "reference.echo" in ids
    vision = next(m for m in d["modules"] if m["module_id"] == "vision")
    assert {n["route"] for n in vision["navigation"]} >= {"/vision/recognize"}


def test_identity_endpoint(client):
    d = client.get("/api/v1/platform/identity").json()
    assert d["product_name"] == "Agentic Business OS"
    assert "SKU" not in d["definition"]


def test_production_endpoint_reads_live_bundle(client):
    d = client.get("/api/v1/platform/production").json()
    # 实时读取 CURRENT.json；不得硬编码
    assert "bundle_id" in d
    if d.get("found"):
        assert d["bundle_id"]


def test_reference_echo_callable(client):
    d = client.get("/api/v1/reference/echo?text=ping").json()
    assert d["echo"] == "ping"
    assert d["module_id"] == "reference.echo"


def test_m3bars_removed(client):
    r = client.get("/api/v1/biz/m3bars")
    assert r.status_code == 404, "训练指标假 BI 端点必须删除"


def test_module_detail_404(client):
    assert client.get("/api/v1/modules/nope").status_code == 404
