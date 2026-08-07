"""GLTC-006 红测试：TrainingControlGraph 与 Hook（任务书 Task 6 / 01 §6）。

- 四 lane 共享同一控制图，通道差异只经 adapter/policy 注入；
- 状态机非法跃迁拒绝并写审计；
- 13 个 Hook 只能推进合法状态；
- 人工 gate 写 checkpoint，可恢复可回放；
- Agent 只能调用白名单 DomainCommand（无任意 SQL/shell/文件写）。
"""
from __future__ import annotations

import pytest

from src.modules.training_control import vocabulary as V
from src.modules.training_control.graph import (
    GraphError,
    TrainingControlGraph,
)
from src.modules.training_control.hooks import HookRegistry
from src.modules.training_control.policy import AgentCommandGate


@pytest.fixture()
def graph():
    return TrainingControlGraph()


def _run(graph, lane="detector"):
    return graph.create_run(lane=lane, plan_id="p1")


class TestStateMachine:
    def test_full_legal_path(self, graph):
        rid = _run(graph)
        for target in ("READY_FOR_APPROVAL", "APPROVED", "QUEUED",
                       "STARTING", "RUNNING", "STOPPING", "STOPPED"):
            graph.advance(rid, target, actor="admin")
        assert graph.status(rid) == "STOPPED"

    def test_illegal_transition_rejected_and_audited(self, graph):
        rid = _run(graph)
        with pytest.raises(GraphError):
            graph.advance(rid, "RUNNING", actor="admin")
        audit = graph.audit_trail(rid)
        assert any(a["kind"] == "illegal_transition" for a in audit)
        assert graph.status(rid) == "DRAFT"

    def test_four_lanes_share_one_graph(self, graph):
        ids = [_run(graph, lane=l) for l in V.TRAINING_LANES]
        assert len(set(type(graph).__mro__)) > 0
        for rid in ids:
            graph.advance(rid, "READY_FOR_APPROVAL", actor="admin")
        # 同一状态机实现，无 lane 专属分支
        assert all(graph.status(r) == "READY_FOR_APPROVAL" for r in ids)


class TestHooks:
    def test_all_thirteen_hooks_registered(self):
        reg = HookRegistry()
        assert set(V.HOOK_NAMES) <= set(reg.names())

    def test_hook_only_advances_legal_state(self, graph):
        reg = HookRegistry()
        rid = _run(graph)
        # HOOK_RUN_STARTED 只能作用于 STARTING 的 run
        graph.advance(rid, "READY_FOR_APPROVAL", actor="admin")
        with pytest.raises(GraphError):
            reg.emit("HOOK_RUN_STARTED", graph, rid, actor="worker")
        graph.advance(rid, "APPROVED", actor="admin")
        graph.advance(rid, "QUEUED", actor="admin")
        graph.advance(rid, "STARTING", actor="admin")
        reg.emit("HOOK_RUN_STARTED", graph, rid, actor="worker")
        assert graph.status(rid) == "RUNNING"

    def test_human_gate_checkpoint_replay(self, graph):
        reg = HookRegistry()
        rid = _run(graph)
        graph.advance(rid, "READY_FOR_APPROVAL", actor="admin")
        reg.emit("HOOK_TRAINING_APPROVAL_REQUIRED", graph, rid,
                 actor="system")
        cp = graph.checkpoint(rid)
        assert cp["waiting_for"] == "human_approval"
        # 恢复：从 checkpoint 重建后仍可继续审批
        g2 = TrainingControlGraph.restore(cp)
        g2.advance(rid, "APPROVED", actor="admin")
        assert g2.status(rid) == "APPROVED"


class TestAgentCommandGate:
    def test_whitelist_commands_only(self):
        gate = AgentCommandGate()
        assert "training.plan.create" in gate.allowed()
        assert "training.run.safe_stop" in gate.allowed()
        with pytest.raises(GraphError):
            gate.validate("sql.execute", {})
        with pytest.raises(GraphError):
            gate.validate("shell.run", {})
        with pytest.raises(GraphError):
            gate.validate("file.write", {})
        gate.validate("training.plan.create", {"lane": "detector"})

    def test_agent_cannot_self_approve(self):
        gate = AgentCommandGate()
        with pytest.raises(GraphError):
            gate.validate("training.plan.approve", {}, actor_kind="agent")
        with pytest.raises(GraphError):
            gate.validate("training.publish.approve", {},
                          actor_kind="agent")
