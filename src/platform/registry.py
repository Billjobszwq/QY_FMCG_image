"""W6/M2：Module Manifest + Capability Registry。

红线：平台不得直接 import Domain Pack；模块必须通过 Manifest 注册能力。
注册时每个 capability 必须提供 adapter 实例（fail-closed）。

ABOS T3：ModuleManifestV2 —— 唯一模块事实源，同时驱动：
一级模块/色系、二级 route、三级 actions、Domain Agent、capabilities、
commands/queries/events、API prefix/OpenAPI tag、data products、
permission scopes、UI slots、feature flags、依赖/兼容、billing、
health checks、live/beta/planned/degraded/disabled 状态。
"""

from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

MODULE_STATUSES = ("live", "beta", "planned", "degraded", "disabled")
UI_INTENT_WHITELIST = ("navigate", "open_panel", "filter", "highlight",
                       "compare", "pin", "show_evidence")


class RegistryError(Exception):
    """重复注册 / 缺失 adapter / 未知能力 / route 或 ID 冲突。"""


class CapabilitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str
    kind: str
    description: str = ""
    # VLM-002：通用运行元数据（有默认值，旧 manifest 无需修改）。
    # 只描述运行特征；平台内不得出现具体领域模型名称。
    resource_class: str = "cpu"
    residency: Literal["hot", "warm", "cold"] = "hot"
    meter_units: tuple[str, ...] = ("call",)


class ModuleManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    module_id: str
    name: str
    version: str
    capabilities: list[CapabilitySpec] = Field(default_factory=list)


class NavRoute(BaseModel):
    """二级导航：独立、可深链接、可刷新恢复的功能 route。"""
    model_config = ConfigDict(extra="forbid", frozen=True)

    route: str
    label: str
    description: str = ""
    # 三级 actions（页面工具栏/步骤条/抽屉中的结构化操作）
    actions: tuple[str, ...] = ()


class ModuleManifestV2(BaseModel):
    """唯一模块事实源（ABOS §五）。前端导航/Agent/API/权限投影均读此。"""
    model_config = ConfigDict(extra="forbid", frozen=True)

    module_id: str
    name: str
    version: str
    domain: str = "general"
    status: Literal["live", "beta", "planned",
                    "degraded", "disabled"] = "planned"
    theme_token: str = "slate"          # 模块色系 token（accent，非整块涂色）
    primary_route: str = "/"
    navigation: tuple[NavRoute, ...] = ()
    agents: tuple[str, ...] = ()        # 关联 AgentManifest.agent_id
    capabilities: tuple[CapabilitySpec, ...] = ()
    commands: tuple[str, ...] = ()
    queries: tuple[str, ...] = ()
    events: tuple[str, ...] = ()
    api_prefix: str = ""
    openapi_tag: str = ""
    data_products: tuple[str, ...] = ()
    permission_scopes: tuple[str, ...] = ()
    ui_slots: tuple[str, ...] = ()
    feature_flags: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()  # 依赖的 module_id
    compatibility: dict[str, str] = Field(default_factory=dict)
    billing_units: tuple[str, ...] = ()
    health_checks: tuple[str, ...] = ()


class ModuleRegistry:
    """ModuleManifestV2 注册表：route/ID 冲突 fail-closed；
    缺依赖模块投影为 degraded（不伪造 live）。"""

    def __init__(self) -> None:
        self._modules: dict[str, ModuleManifestV2] = {}
        self._routes: dict[str, str] = {}     # route -> module_id
        self._agents: dict[str, str] = {}     # agent_id -> module_id
        self._capabilities: dict[str, str] = {}  # capability_id -> module_id

    def register(self, m: ModuleManifestV2) -> None:
        if m.module_id in self._modules:
            raise RegistryError(f"module 已注册: {m.module_id}")
        for route in [m.primary_route, *(n.route for n in m.navigation)]:
            if route in self._routes and self._routes[route] != m.module_id:
                raise RegistryError(
                    f"route 冲突（fail-closed）: {route} 已被 "
                    f"{self._routes[route]} 注册，{m.module_id} 再次声明")
            self._routes[route] = m.module_id
        for agent_id in m.agents:
            if agent_id in self._agents:
                raise RegistryError(
                    f"agent 冲突（fail-closed）: {agent_id} 已属于 "
                    f"{self._agents[agent_id]}")
            self._agents[agent_id] = m.module_id
        for cap in m.capabilities:
            if cap.capability_id in self._capabilities:
                raise RegistryError(
                    f"capability 冲突（fail-closed）: {cap.capability_id}")
            self._capabilities[cap.capability_id] = m.module_id
        self._modules[m.module_id] = m

    def get(self, module_id: str) -> ModuleManifestV2 | None:
        return self._modules.get(module_id)

    def modules(self) -> list[ModuleManifestV2]:
        return list(self._modules.values())

    def effective_status(self, m: ModuleManifestV2,
                         degraded: set[str] | None = None) -> str:
        """live 依赖缺失或服务降级 → degraded（不伪造 live）。"""
        degraded = degraded or set()
        if m.status in ("planned", "disabled"):
            return m.status
        for dep in m.dependencies:
            dm = self._modules.get(dep)
            if dm is None or dm.status in ("planned", "disabled"):
                return "degraded"
        if m.module_id in degraded:
            return "degraded"
        return m.status

    def project(self, degraded: set[str] | None = None) -> list[dict]:
        """只读投影：导航/状态/API/权限单一事实源输出。"""
        out = []
        for m in self._modules.values():
            status = self.effective_status(m, degraded)
            out.append({
                "module_id": m.module_id,
                "name": m.name,
                "version": m.version,
                "domain": m.domain,
                "status": status,
                "declared_status": m.status,
                "theme_token": m.theme_token,
                "primary_route": m.primary_route,
                "navigation": [{"route": n.route, "label": n.label,
                                "description": n.description,
                                "actions": list(n.actions)}
                               for n in m.navigation],
                "agents": list(m.agents),
                "capabilities": [c.capability_id for c in m.capabilities],
                "api_prefix": m.api_prefix,
                "data_products": list(m.data_products),
                "permission_scopes": list(m.permission_scopes),
                "feature_flags": list(m.feature_flags),
                "dependencies": list(m.dependencies),
                "billing_units": list(m.billing_units),
                "health_checks": list(m.health_checks),
            })
        return out


class CapabilityRegistry:
    def __init__(self) -> None:
        self._modules: dict[str, ModuleManifest] = {}
        self._adapters: dict[str, Any] = {}
        self._owner: dict[str, str] = {}

    def register(self, manifest: ModuleManifest, adapters: Mapping[str, Any]) -> None:
        if manifest.module_id in self._modules:
            raise RegistryError(f"module 已注册: {manifest.module_id}")
        for cap in manifest.capabilities:
            if cap.capability_id in self._adapters:
                raise RegistryError(f"capability 已被注册: {cap.capability_id}")
            if cap.capability_id not in adapters:
                raise RegistryError(
                    f"capability 缺少 adapter: {cap.capability_id}（fail-closed）"
                )
        self._modules[manifest.module_id] = manifest
        for cap in manifest.capabilities:
            self._adapters[cap.capability_id] = adapters[cap.capability_id]
            self._owner[cap.capability_id] = manifest.module_id

    def get(self, capability_id: str) -> Any:
        if capability_id not in self._adapters:
            raise RegistryError(f"capability 未注册: {capability_id}")
        return self._adapters[capability_id]

    def capabilities(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for module_id, manifest in self._modules.items():
            for cap in manifest.capabilities:
                out.append(
                    {
                        "capability_id": cap.capability_id,
                        "module_id": module_id,
                        "module_name": manifest.name,
                        "module_version": manifest.version,
                        "kind": cap.kind,
                        "description": cap.description,
                        "resource_class": cap.resource_class,
                        "residency": cap.residency,
                        "meter_units": cap.meter_units,
                    }
                )
        return out


def bootstrap_default_registry(
    recognition_adapter: Any | None = None,
    monitor_adapter: Any | None = None,
    label_studio_adapter: Any | None = None,
) -> CapabilityRegistry:
    """注册 legacy 8091/8092/8300 适配器为平台 Capability（M2/M4 要求）。"""
    from .adapters.legacy.label_studio import (
        CAPABILITY_ID as LS_CAP,
        LabelStudioAdapter,
    )
    from .adapters.legacy.monitor import CAPABILITY_ID as MONITOR_CAP, MonitorAdapter
    from .adapters.legacy.recognition import (
        CAPABILITY_ID as RECOGNITION_CAP,
        RecognitionV2Adapter,
    )

    reg = CapabilityRegistry()
    reg.register(
        ModuleManifest(
            module_id="legacy.recognition",
            name="Legacy Recognition Bridge (8091)",
            version="2.0.0",
            capabilities=[
                CapabilitySpec(
                    capability_id=RECOGNITION_CAP,
                    kind="recognition",
                    description="cascade_v3 识别（HTTP 代理 8091 /v2/recognize）",
                )
            ],
        ),
        adapters={RECOGNITION_CAP: recognition_adapter or RecognitionV2Adapter()},
    )
    reg.register(
        ModuleManifest(
            module_id="legacy.training.monitor",
            name="Legacy Training Monitor (8092)",
            version="1.0.0",
            capabilities=[
                CapabilitySpec(
                    capability_id=MONITOR_CAP,
                    kind="monitor",
                    description="训练监控只读（HTTP 代理 8092 /api/live|overview）",
                )
            ],
        ),
        adapters={MONITOR_CAP: monitor_adapter or MonitorAdapter()},
    )
    reg.register(
        ModuleManifest(
            module_id="legacy.label_studio",
            name="Legacy Label Studio Bridge (8300)",
            version="1.23.0",
            capabilities=[
                CapabilitySpec(
                    capability_id=LS_CAP,
                    kind="labeling",
                    description="Label Studio 项目/任务/标注代理（HTTP 8300 REST API）",
                )
            ],
        ),
        adapters={LS_CAP: label_studio_adapter or LabelStudioAdapter()},
    )
    return reg
