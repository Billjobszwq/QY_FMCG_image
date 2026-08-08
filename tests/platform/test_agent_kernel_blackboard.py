"""SLTF §11/§12：Agent Kernel + Shared Blackboard + Memory 契约。

- AgentManifest 注册（通用，不绑 FMCG）；capability scope 校验；
- 四内置 Agent 可独立注册/调用；
- Workbench UIIntent 仅限白名单类型，禁任意 HTML/JS；
- Blackboard typed append-only，Agent 不得覆盖他人/人工结论；
- Memory 分级 + ACL + supersedes，向量仅为派生物。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.platform.agents.kernel import (
    AgentManifest,
    AgentRegistry,
    UIIntentError,
    validate_ui_intent,
)
from src.platform.agents.blackboard import (
    BlackboardService,
    BlackboardTypeError,
    MemoryService,
)
from src.platform.data.store import PlatformStore


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


class TestAgentKernel:
    def test_builtin_agents_registered(self, store):
        reg = AgentRegistry(store)
        ids = {a["agent_id"] for a in reg.list_agents()}
        assert {"supervisor", "modelops", "data_steward",
                "workbench"} <= ids

    def test_capability_scope_enforced(self, store):
        reg = AgentRegistry(store)
        m = AgentManifest(agent_id="rogue", version="1", domain="x",
                          capability_scopes=["production.switch"],
                          command_schemas=[], allowed_data_scopes=[],
                          memory_policy="none", ui_slots=[],
                          graph_templates=[], risk_level="high",
                          approval_rules=[], billing_unit="call",
                          health_endpoint="/health")
        with pytest.raises(ValueError):
            reg.register(m)  # production.switch 不在可授予 scope

    def test_ui_intent_whitelist(self):
        for kind in ("navigate", "open_panel", "filter", "highlight",
                     "compare", "pin_card", "show_evidence"):
            validate_ui_intent({"kind": kind, "target": "training"})
        with pytest.raises(UIIntentError):
            validate_ui_intent({"kind": "inject_html",
                                "html": "<script>"})


class TestBlackboard:
    def test_append_only_and_typed(self, store):
        bb = BlackboardService(store)
        bb.append("modelops", "Finding", {"text": "leak 47.7pp"},
                  evidence_refs=["reports/nextgen_v2/classifier_split_compare.json"])
        with pytest.raises(BlackboardTypeError):
            bb.append("modelops", "FreeText", {"text": "x"})
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute("DELETE FROM blackboard_event_v1")

    def test_no_silent_overwrite_of_others(self, store):
        bb = BlackboardService(store)
        e1 = bb.append("modelops", "Decision", {"text": "A"})
        with pytest.raises(PermissionError):
            bb.append("data_steward", "Decision", {"text": "override"},
                      supersedes=e1)  # 跨 Agent 覆盖需人工

    def test_memory_acl_and_supersedes(self, store):
        ms = MemoryService(store)
        mid = ms.put("project", "leakage 严重", scope="project",
                     acl=["project:llm-image"], confidence=0.9,
                     evidence=["reports/nextgen_v2/classifier_split_compare.json"])
        assert ms.get(mid, requester_acl=["project:llm-image"]) is not None
        assert ms.get(mid, requester_acl=["tenant:other"]) is None
        mid2 = ms.put("project", "leakage 修正", scope="project",
                      acl=["project:llm-image"], confidence=1.0,
                      evidence=["x"], supersedes=mid)
        old = ms.get(mid, requester_acl=["project:llm-image"])
        assert old["valid_to"] is not None
EOF_GUARD=1
