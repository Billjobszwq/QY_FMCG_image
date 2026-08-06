"""W6/M2：Module Manifest + Capability Registry。

红线：平台不得直接 import Domain Pack；模块必须通过 Manifest 注册能力。
注册时每个 capability 必须提供 adapter 实例（fail-closed）。
"""

from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field


class RegistryError(Exception):
    """重复注册 / 缺失 adapter / 未知能力。"""


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
