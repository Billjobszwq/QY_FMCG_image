"""W9：PlatformBundle —— 组合根注入的运行时依赖容器（平台保持领域无关）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ..assets.cas import ContentAddressedStore
from ..data.store import PlatformStore
from ..kernel.engine import GraphEngine
from ..registry import CapabilityRegistry
from ..kernel.definition import GraphRegistry


@dataclass
class PlatformBundle:
    store: PlatformStore
    cas: ContentAddressedStore
    capabilities: CapabilityRegistry
    graphs: GraphRegistry
    engine: GraphEngine
    handlers: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def handlers_for(self, graph_name: str) -> Mapping[str, Any]:
        return self.handlers[graph_name]
