"""SLTF §11：Agent Kernel（通用，不绑 FMCG）。

AgentManifest 注册 + capability scope 白名单 + UIIntent 白名单。
内置四 Agent：supervisor / modelops / data_steward / workbench。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

# 可授予 Agent 的 capability scope（production.switch 等高风险不在此列）
GRANTABLE_SCOPES = frozenset({
    "training.experiment.bounded", "training.run.read",
    "snapshot.build", "sam.teacher", "label_studio.manage",
    "registry.read", "data.query.readonly", "blackboard.append",
    "ui.intent", "evidence.read", "lease.acquire",
})

UI_INTENT_KINDS = frozenset({
    "navigate", "open_panel", "filter", "highlight",
    "compare", "pin_card", "show_evidence",
})


class UIIntentError(ValueError):
    """UIIntent 非法（禁任意 HTML/JS 注入）。"""


def validate_ui_intent(intent: dict[str, Any]) -> None:
    kind = intent.get("kind")
    if kind not in UI_INTENT_KINDS:
        raise UIIntentError(f"UIIntent 类型不在白名单: {kind}")
    if any(k in intent for k in ("html", "js", "script")):
        raise UIIntentError("UIIntent 禁含 html/js/script 字段")


@dataclass(frozen=True)
class AgentManifest:
    agent_id: str
    version: str
    domain: str
    capability_scopes: list[str]
    command_schemas: list[str]
    allowed_data_scopes: list[str]
    memory_policy: str
    ui_slots: list[str]
    graph_templates: list[str]
    risk_level: str
    approval_rules: list[str]
    billing_unit: str
    health_endpoint: str


_BUILTIN = [
    AgentManifest("supervisor", "1", "general",
                  ["training.run.read", "evidence.read", "blackboard.append",
                   "ui.intent", "data.query.readonly"],
                  ["graph.decompose", "agent.invoke", "command.preview"],
                  ["project:*"], "l1_l2", ["drawer", "taskboard"],
                  ["training_cycle"], "medium",
                  ["human_approval_for_publish"], "call", "/health"),
    AgentManifest("modelops", "1", "modelops",
                  ["training.experiment.bounded", "snapshot.build",
                   "sam.teacher", "label_studio.manage", "lease.acquire",
                   "training.run.read", "blackboard.append", "evidence.read"],
                  ["training.plan.create", "training.run.launch_bounded",
                   "snapshot.freeze", "candidate.register"],
                  ["project:*"], "l1_l2", ["training_cards"],
                  ["training_cycle"], "medium",
                  ["human_approval_for_production"], "gpu_minute", "/health"),
    AgentManifest("data_steward", "1", "data",
                  ["data.query.readonly", "blackboard.append", "evidence.read",
                   "registry.read"],
                  ["data.correction.propose", "data.lineage.query"],
                  ["project:*"], "l2_l3", ["data_cards"],
                  ["data_quality_graph"], "low",
                  ["human_approval_for_correction"], "query", "/health"),
    AgentManifest("workbench", "1", "ui",
                  ["ui.intent", "blackboard.append", "evidence.read",
                   "training.run.read"],
                  ["ui.intent.emit", "taskboard.update"],
                  ["project:*"], "l0_l1", ["drawer", "taskboard"],
                  ["taskboard_graph"], "low", [], "call", "/health"),
]


class AgentRegistry:
    def __init__(self, store: Any) -> None:
        self.store = store
        self._ensure_builtin()

    def _ensure_builtin(self) -> None:
        for m in _BUILTIN:
            if not self.store._conn.execute(
                    "SELECT 1 FROM agent_manifest_v1 WHERE agent_id=?",
                    (m.agent_id,)).fetchone():
                self.register(m, _builtin=True)

    def register(self, m: AgentManifest, *, _builtin: bool = False) -> None:
        bad = set(m.capability_scopes) - GRANTABLE_SCOPES
        if bad and not _builtin:
            raise ValueError(f"capability scope 不可授予: {sorted(bad)}")
        self.store._conn.execute(
            "INSERT INTO agent_manifest_v1 (agent_id, version, domain,"
            " manifest_json, created_at) VALUES (?,?,?,?,?)",
            (m.agent_id, m.version, m.domain,
             json.dumps(asdict(m), ensure_ascii=False),
             datetime.now(timezone.utc).isoformat()))
        self.store._conn.commit()

    def list_agents(self) -> list[dict[str, Any]]:
        rows = self.store._conn.execute(
            "SELECT manifest_json FROM agent_manifest_v1").fetchall()
        return [json.loads(r["manifest_json"]) for r in rows]
