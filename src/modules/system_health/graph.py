"""非识别 Graph：system_health_v1 —— 证明 Kernel 无 FMCG 硬编码。

节点链：probe → summarize。探测函数与目标服务清单由组合根注入（模块不 import 平台健康实现）。
"""

from __future__ import annotations

import json
from typing import Callable, Sequence

from src.platform.data.store import PlatformStore
from src.platform.kernel.definition import GraphDefinition, NodeSpec
from src.platform.kernel.engine import NodeContext

GRAPH_NAME = "system_health_v1"
GRAPH_VERSION = "1"

DEFINITION = GraphDefinition(
    name=GRAPH_NAME,
    version=GRAPH_VERSION,
    nodes=[NodeSpec("probe"), NodeSpec("summarize")],
)


def _node_output(store: PlatformStore, run_id: str, node_name: str) -> dict:
    for n in store.list_nodes(run_id):
        if n["node_name"] == node_name and n["status"] == "completed" and n["output_json"]:
            return json.loads(n["output_json"])
    return {}


def build_handlers(*, services: Sequence, probe: Callable, store: PlatformStore) -> dict:
    def do_probe(ctx: NodeContext) -> dict:
        results = []
        for spec in services:
            st = probe(spec)
            results.append(
                {
                    "name": spec.name,
                    "status": getattr(st, "status", "unknown"),
                    "critical": getattr(spec, "critical", False),
                }
            )
        return {"services": results}

    def summarize(ctx: NodeContext) -> dict:
        probe_out = _node_output(store, ctx.run_id, "probe")
        svcs = probe_out.get("services", [])
        unhealthy = [s["name"] for s in svcs if s["status"] != "healthy"]
        return {
            "total": len(svcs),
            "unhealthy": unhealthy,
            "overall": "degraded" if unhealthy else "healthy",
        }

    return {"probe": do_probe, "summarize": summarize}
