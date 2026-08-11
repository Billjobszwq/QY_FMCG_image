"""ABOSV2 Z-1/Z-2 契约测试：集成契约交叉验证 + 六个 Domain Agent。

- ModuleUIRegistry（前端 MODULE_ROUTES）↔ 后端 UI_ROUTES_MIRROR ↔
  module_catalog 导航路由 三方严格一致（缺失 fail-closed）；
- Manifest 投影必须含 commands/queries/events（P1-002）；
- 集成报告：agent/scope/command/route/openapi 任一缺失 → error；
- 六个 Domain Agent 注册且 scope 全部在 GRANTABLE_SCOPES 白名单内。
"""
from __future__ import annotations

import re
from pathlib import Path

from src.platform.agents.kernel import GRANTABLE_SCOPES, _BUILTIN
from src.platform.integration import (PLATFORM_COMMANDS, UI_ROUTES_MIRROR,
                                      integration_report)
from src.platform.module_catalog import build_default_module_registry

ROOT = Path(__file__).resolve().parents[2]
UI_REGISTRY = ROOT / "web" / "src" / "platform" / "ui_registry.tsx"


def _frontend_routes() -> set[str]:
    src = UI_REGISTRY.read_text(encoding="utf-8")
    # MODULE_ROUTES 块内的路由键
    block = src.split("export const MODULE_ROUTES", 1)[1]
    block = block.split("export const MODULE_REDIRECTS", 1)[0]
    return set(re.findall(r'"(/[A-Za-z0-9/_-]+)":', block))


def _catalog_routes() -> set[str]:
    reg = build_default_module_registry()
    routes = set()
    for m in reg.project():
        for n in m["navigation"]:
            routes.add(n["route"])
    return routes


class TestUIRegistryCrossValidation:
    def test_frontend_matches_backend_mirror(self):
        assert _frontend_routes() == set(UI_ROUTES_MIRROR), \
            "前端 MODULE_ROUTES 与后端镜像不一致（fail-closed）"

    def test_mirror_covers_all_catalog_routes(self):
        missing = _catalog_routes() - set(UI_ROUTES_MIRROR)
        assert missing == set(), f"导航路由缺少 UI 组件注册: {missing}"

    def test_no_orphan_frontend_routes(self):
        extra = _frontend_routes() - _catalog_routes()
        assert extra == set(), f"前端存在目录外路由: {extra}"

    def test_app_no_longer_handwrites_module_routes(self):
        app = (ROOT / "web" / "src" / "App.tsx").read_text(encoding="utf-8")
        assert "MODULE_ROUTES" in app, "App 必须消费 ModuleUIRegistry"
        assert 'path="/survey/design"' not in app, \
            "P1-003：App 不得再手写模块路由"


class TestManifestProjection:
    def test_projection_includes_execution_contracts(self):
        reg = build_default_module_registry()
        by_id = {m["module_id"]: m for m in reg.project()}
        assert by_id["vision"]["commands"] == ["vision.recognition.create"]
        assert "commands" in by_id["workflow"]
        assert "queries" in by_id["iam"] and "events" in by_id["vision"]


class _FakeRegistry:
    def __init__(self, modules: list[dict]):
        self._modules = modules

    def project(self, degraded=None):
        return self._modules


def _base_module(**over) -> dict:
    m = {"module_id": "demo", "status": "live", "agents": [],
         "permission_scopes": ["vision.read"], "commands": [],
         "navigation": [], "api_prefix": "", "billing_units": ("x",),
         "health_checks": ("h",)}
    m.update(over)
    return m


def _run(modules, **kw):
    defaults = dict(agent_ids={"survey_agent"},
                    ui_routes=set(UI_ROUTES_MIRROR),
                    openapi_paths=[], gateway_commands=set(),
                    agent_command_schemas=set())
    defaults.update(kw)
    return integration_report(_FakeRegistry(modules), **defaults)


class TestIntegrationFailClosed:
    def test_missing_agent_flagged(self):
        rep = _run([_base_module(agents=["no_such_agent"])])
        assert rep["ok"] is False
        assert any("agent 未注册" in e for e in rep["modules"][0]["errors"])

    def test_unregistered_scope_flagged(self):
        rep = _run([_base_module(permission_scopes=["evil.scope"])])
        assert rep["ok"] is False
        assert any("IAM 注册" in e for e in rep["modules"][0]["errors"])

    def test_unregistered_command_flagged(self):
        rep = _run([_base_module(commands=["demo.unknown.command"])])
        assert rep["ok"] is False
        assert any("command 未在任何注册表登记" in e
                   for e in rep["modules"][0]["errors"])

    def test_missing_ui_route_flagged_for_live(self):
        rep = _run([_base_module(
            navigation=[{"route": "/demo/missing", "label": "x"}])])
        assert rep["ok"] is False
        assert any("UI 组件注册" in e for e in rep["modules"][0]["errors"])

    def test_missing_openapi_prefix_flagged(self):
        rep = _run([_base_module(api_prefix="/api/v1/demo")],
                   openapi_paths=["/api/v1/other"])
        assert rep["ok"] is False
        assert any("OpenAPI" in e for e in rep["modules"][0]["errors"])

    def test_real_catalog_passes(self):
        reg = build_default_module_registry()
        agent_ids = {m.agent_id for m in _BUILTIN}
        schemas = set()
        for m in _BUILTIN:
            schemas.update(m.command_schemas)
        prefixes = {m["api_prefix"] for m in reg.project()
                    if m.get("api_prefix")}
        openapi_paths = [f"{p}/x" for p in prefixes]
        rep = integration_report(
            reg, agent_ids=agent_ids, ui_routes=set(UI_ROUTES_MIRROR),
            openapi_paths=openapi_paths,
            gateway_commands={"vision.recognition.create"},
            agent_command_schemas=schemas)
        assert rep["ok"] is True, [m["errors"] for m in rep["modules"]
                                   if m["errors"]]


class TestDomainAgents:
    def test_six_domain_agents_registered(self):
        ids = {m.agent_id for m in _BUILTIN}
        for want in ("workflow_agent", "iam_agent", "survey_agent",
                     "analytics_agent", "fieldops_agent", "finance_agent"):
            assert want in ids, f"缺少 Domain Agent: {want}"

    def test_agent_scopes_within_grantable_whitelist(self):
        for m in _BUILTIN:
            bad = set(m.capability_scopes) - GRANTABLE_SCOPES
            assert bad == set(), f"{m.agent_id} 越权 scope: {bad}"

    def test_high_risk_rules_require_human_approval(self):
        by_id = {m.agent_id: m for m in _BUILTIN}
        assert any("human_approval_for_publish" in r
                   for r in by_id["workflow_agent"].approval_rules)
        assert any("human_final_answer_required" in r
                   for r in by_id["survey_agent"].approval_rules)
        assert any("face_compare_requires_explicit_consent" in r
                   for r in by_id["fieldops_agent"].approval_rules)
        assert any("usage_only_billing" in r
                   for r in by_id["finance_agent"].approval_rules)
