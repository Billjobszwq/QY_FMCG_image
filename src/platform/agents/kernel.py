"""SLTF §11：Agent Kernel（通用，不绑 FMCG）。

AgentManifest 注册 + capability scope 白名单 + UIIntent 白名单。
内置六 Agent：supervisor / modelops / data_steward / workbench /
recognition_agent / system_agent（ABOS T6）。
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
    "recognition.task.create", "recognition.task.read",
    "system.health.read",
    # ABOSV2 Z-2：Domain Agent 作用域（各自 allowlist，不借用管理员）
    "workflow.read", "workflow.draft.propose",
    "iam.read", "master.read",
    "survey.read", "survey.respond",
    "analytics.read", "analytics.anomaly.answer",
    "geo.read", "geo.visit.evidence",
    "finance.read",
    "command.gateway.submit",
})

# UIIntent 白名单（ABOS §八）：navigate/open_panel/filter/highlight/
# compare/pin/show_evidence；禁 HTML/JS 注入。
UI_INTENT_KINDS = frozenset({
    "navigate", "open_panel", "filter", "highlight",
    "compare", "pin", "pin_card", "show_evidence",
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
    AgentManifest("recognition_agent", "1", "vision",
                  ["recognition.task.create", "recognition.task.read",
                   "evidence.read", "blackboard.append", "ui.intent",
                   "registry.read"],
                  ["vision.recognition.create", "command.preview"],
                  ["project:*"], "l1_l2", ["workspace", "evidence_drawer"],
                  ["recognition_graph"], "medium",
                  ["human_approval_for_batch"], "recognition_call",
                  "/health"),
    AgentManifest("system_agent", "1", "system",
                  ["system.health.read", "registry.read", "evidence.read",
                   "blackboard.append"],
                  ["system.health.query"],
                  ["project:*"], "l1_l2", ["status"],
                  [], "low", [], "call", "/health"),
    # ABOSV2 Z-2：六个 Domain Agent（独立身份/allowlist/数据 scope/
    # 预算/记忆 ACL；发布与高风险动作必须人工批准）。
    AgentManifest("workflow_agent", "1", "workflow",
                  ["workflow.read", "workflow.draft.propose",
                   "registry.read", "evidence.read", "blackboard.append"],
                  ["workflow.draft.propose"],
                  ["project:*"], "l1_l2", ["workflow_studio"],
                  [], "medium", ["human_approval_for_publish"],
                  "workflow_node_execution", "/health"),
    AgentManifest("iam_agent", "1", "iam",
                  ["iam.read", "registry.read", "evidence.read",
                   "blackboard.append"],
                  ["iam.audit.query"],
                  ["tenant:*"], "l2_l3", ["iam_accounts"],
                  [], "medium", ["human_approval_for_grant"],
                  "query", "/health"),
    AgentManifest("survey_agent", "1", "survey",
                  ["survey.read", "survey.respond", "master.read",
                   "evidence.read", "blackboard.append"],
                  ["survey.suggestion.review"],
                  ["customer:*"], "l1_l2", ["survey_field"],
                  [], "medium", ["human_final_answer_required"],
                  "response", "/health"),
    AgentManifest("analytics_agent", "1", "analytics",
                  ["analytics.read", "analytics.anomaly.answer",
                   "data.query.readonly", "evidence.read",
                   "blackboard.append"],
                  ["analytics.report.draft"],
                  ["customer:*"], "l1_l2", ["analytics_reports"],
                  [], "medium", ["human_approval_for_publish"],
                  "query", "/health"),
    AgentManifest("fieldops_agent", "1", "geo_field",
                  ["geo.read", "geo.visit.evidence", "evidence.read",
                   "blackboard.append"],
                  ["geo.dispatch.propose"],
                  ["customer:*"], "l1_l2", ["geo_field"],
                  [], "medium",
                  ["human_confirmation_for_low_confidence_address",
                   "face_compare_requires_explicit_consent"],
                  "field_visit", "/health"),
    AgentManifest("finance_agent", "1", "finance",
                  ["finance.read", "evidence.read", "blackboard.append"],
                  ["finance.invoice.draft"],
                  ["customer:*"], "l2_l3", ["finance_invoices"],
                  [], "medium",
                  ["human_approval_for_settlement",
                   "usage_only_billing"],
                  "query", "/health"),
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
