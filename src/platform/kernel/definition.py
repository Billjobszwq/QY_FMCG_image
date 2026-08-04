"""W7 Graph Kernel：GraphDefinition/Version 不可原地修改 + Registry。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


class GraphVersionError(Exception):
    """同名同版本内容不一致（禁止原地修改），或查询未注册 Graph。"""


@dataclass(frozen=True)
class NodeSpec:
    node_name: str


@dataclass(frozen=True)
class GraphDefinition:
    name: str
    version: str
    nodes: tuple[NodeSpec, ...] = field(default_factory=tuple)

    def content_hash(self) -> str:
        payload = json.dumps(
            {"name": self.name, "version": self.version,
             "nodes": [n.node_name for n in self.nodes]},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class GraphRegistry:
    """GraphVersion 一旦注册不可变；修改必须发布新版本。"""

    def __init__(self) -> None:
        self._defs: dict[tuple[str, str], GraphDefinition] = {}
        self._hashes: dict[tuple[str, str], str] = {}

    def register(self, defn: GraphDefinition) -> None:
        key = (defn.name, defn.version)
        digest = defn.content_hash()
        if key in self._hashes and self._hashes[key] != digest:
            raise GraphVersionError(
                f"Graph {defn.name}@{defn.version} 已注册且内容不同；禁止原地修改，请发布新版本"
            )
        self._defs[key] = defn
        self._hashes[key] = digest

    def get(self, name: str, version: str) -> GraphDefinition:
        key = (name, version)
        if key not in self._defs:
            raise GraphVersionError(f"Graph 未注册: {name}@{version}")
        return self._defs[key]

    def list(self) -> list[dict[str, str]]:
        return [
            {"name": d.name, "version": d.version, "nodes": len(d.nodes)}
            for d in self._defs.values()
        ]
