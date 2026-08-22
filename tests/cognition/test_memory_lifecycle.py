"""Task 6（G4）测试：规范 L1/L2/L3 记忆生命周期（治理强化后）。

要求（05 计划 Task 6 + 评审修复）：
- L1 append-only；普通 Agent 不能写 L2/L3；角色与 principal 绑定；
- L3 candidate 未批准不可检索为 published；
- L1→L2 candidate 确定性幂等 + 人类批准账本发布门；
- L2→L3 candidate + 反例/最小**独立**事件数校验；
- CAS 拒绝重复发布；冲突并存标记；source lineage/supersession/retention。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.platform.cognition.context import CognitiveContext
from src.platform.cognition.errors import (
    CognitionConflictError,
    CognitionPermissionDeniedError,
    CognitionValidationError,
)
from src.platform.cognition.memory.service import (
    APPROVAL_KIND_L2,
    APPROVAL_KIND_L3,
    MemoryLifecycleService,
)
from src.platform.data.store import PlatformStore

from .helpers import approve

AS_OF = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


@pytest.fixture()
def ctx():
    return CognitiveContext(
        principal_id="alice", tenant_id="local", customer_id="cust-a",
        project_id="prj-1", test_run_id="", data_scope="operational",
        action="cognition.memory.search", permission_tags=("project:p1",),
        purpose="memory-test", correlation_id="corr-1",
        parent_run_id=None, as_of=AS_OF)


@pytest.fixture()
def svc(store):
    return MemoryLifecycleService(store)


def _l1(svc, ctx, i: int, task_id: str = "task-1") -> str:
    return svc.append_l1(
        ctx, task_id=task_id, run_id=f"run-{i}", node_id="n",
        actor_id="recognition_agent", actor_kind="agent",
        event_type="Finding", payload={"text": f"事件 {i}"},
        permission_tags=("project:p1",), retention_class="permanent")


def _consolidate(svc, ctx, l1_ids, task_id="task-1"):
    return svc.consolidate_l1_to_l2(
        ctx, actor_role="consolidator", actor="memory_consolidator",
        task_id=task_id, period_start="2026-08-01",
        period_end="2026-08-20", l1_ids=l1_ids)


def _publish_l2(svc, store, episode_id):
    ap = approve(store, kind=APPROVAL_KIND_L2,
                 subject_ref=f"l2:{episode_id}",
                 requested_by="memory_consolidator",
                 decider="human-bill")
    return svc.publish_l2(episode_id, approver="human-bill",
                          approval_id=ap)


class TestL1AppendOnly:
    def test_append_and_lineage_fields(self, svc, ctx):
        eid = _l1(svc, ctx, 1)
        row = svc.get_l1(eid)
        assert row["actor_kind"] == "agent"
        assert row["retention_class"] == "permanent"
        assert row["ingested_at"] and row["occurred_at"]

    def test_l1_immutable_triggers(self, svc, ctx, store):
        eid = _l1(svc, ctx, 1)
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute("DELETE FROM memory_l1_event")
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute(
                "UPDATE memory_l1_event SET payload_json='{}'"
                " WHERE event_id=?", (eid,))

    def test_l1_requires_permission_tags(self, svc, ctx):
        with pytest.raises(CognitionValidationError):
            svc.append_l1(ctx, task_id="t", run_id="r", node_id="n",
                          actor_id="a", actor_kind="agent",
                          event_type="Note", payload={},
                          permission_tags=(),
                          retention_class="permanent")

    def test_supersedes_target_must_exist(self, svc, ctx):
        with pytest.raises(CognitionValidationError):
            svc.append_l1(ctx, task_id="t", run_id="r", node_id="n",
                          actor_id="a", actor_kind="agent",
                          event_type="Note", payload={},
                          permission_tags=("p",),
                          supersedes="l1-does-not-exist")


class TestL2ConsolidationGate:
    def test_regular_agent_cannot_write_l2(self, svc, ctx):
        e1 = _l1(svc, ctx, 1)
        with pytest.raises(CognitionPermissionDeniedError):
            svc.consolidate_l1_to_l2(
                ctx, actor_role="domain_agent", actor="finance_agent",
                task_id="task-1", period_start="2026-08-01",
                period_end="2026-08-20", l1_ids=[e1])

    def test_role_principal_binding_enforced(self, svc, ctx):
        """自报 consolidator 角色但 principal 不匹配 → 拒绝（评审 #13）。"""
        e1 = _l1(svc, ctx, 1)
        with pytest.raises(CognitionPermissionDeniedError):
            svc.consolidate_l1_to_l2(
                ctx, actor_role="consolidator", actor="finance_agent",
                task_id="task-1", period_start="2026-08-01",
                period_end="2026-08-20", l1_ids=[e1])

    def test_consolidator_creates_candidate_only(self, svc, ctx):
        e1, e2 = _l1(svc, ctx, 1), _l1(svc, ctx, 2)
        ep = _consolidate(svc, ctx, [e1, e2])
        assert ep["status"] == "candidate"
        assert sorted(ep["source_l1_ids"]) == sorted([e1, e2])

    def test_candidate_not_retrievable_as_published(self, svc, ctx,
                                                    store):
        e1 = _l1(svc, ctx, 1)
        ep = _consolidate(svc, ctx, [e1])
        assert svc.published_l2_episodes(ctx, task_id="task-1") == []
        _publish_l2(svc, store, ep["episode_id"])
        got = svc.published_l2_episodes(ctx, task_id="task-1")
        assert len(got) == 1 and got[0]["episode_id"] == ep["episode_id"]

    def test_consolidation_idempotent_by_source_hash(self, svc, ctx):
        e1, e2 = _l1(svc, ctx, 1), _l1(svc, ctx, 2)
        a = _consolidate(svc, ctx, [e1, e2])
        b = _consolidate(svc, ctx, [e1, e2])
        assert a["episode_id"] == b["episode_id"]
        assert svc.count_l2() == 1

    def test_publish_l2_requires_human_approval(self, svc, ctx, store):
        e1 = _l1(svc, ctx, 1)
        ep = _consolidate(svc, ctx, [e1])
        with pytest.raises(CognitionValidationError):
            svc.publish_l2(ep["episode_id"], approver="",
                           approval_id="")
        with pytest.raises(Exception):
            svc.publish_l2(ep["episode_id"], approver="human-bill",
                           approval_id="apr-nonexistent")

    def test_double_publish_l2_cas_rejected(self, svc, ctx, store):
        e1 = _l1(svc, ctx, 1)
        ep = _consolidate(svc, ctx, [e1])
        _publish_l2(svc, store, ep["episode_id"])
        ap = approve(store, kind=APPROVAL_KIND_L2,
                     subject_ref=f"l2:{ep['episode_id']}",
                     requested_by="memory_consolidator",
                     decider="human-2")
        with pytest.raises(CognitionConflictError):
            svc.publish_l2(ep["episode_id"], approver="human-2",
                           approval_id=ap)

    def test_conflict_marking_coexists(self, svc, ctx):
        e1 = _l1(svc, ctx, 1)
        ep = _consolidate(svc, ctx, [e1])
        got = svc.mark_l2_conflict(ep["episode_id"], actor="rules_agent")
        assert got["status"] == "conflict"


class TestL3MethodologyGate:
    def _three_published_episodes(self, svc, ctx, store):
        ids = []
        for i in range(3):
            e = _l1(svc, ctx, i, task_id=f"task-{i}")
            ep = _consolidate(svc, ctx, [e], task_id=f"task-{i}")
            _publish_l2(svc, store, ep["episode_id"])
            ids.append(ep["episode_id"])
        return ids

    def test_regular_agent_cannot_write_l3(self, svc, ctx):
        with pytest.raises(CognitionPermissionDeniedError):
            svc.propose_l3(ctx, actor_role="domain_agent",
                           actor="analytics_agent",
                           statement="方法 X",
                           source_l2_ids=["a", "b", "c"])

    def test_min_event_count_enforced(self, svc, ctx, store):
        ids = self._three_published_episodes(svc, ctx, store)
        with pytest.raises(CognitionValidationError):
            svc.propose_l3(ctx, actor_role="consolidator",
                           actor="memory_consolidator",
                           statement="单个案例不成方法论",
                           source_l2_ids=ids[:1])

    def test_duplicate_l2_ids_do_not_inflate_count(self, svc, ctx,
                                                   store):
        """同一 L2 重复 3 次 ≠ 3 个独立事件（评审 #3）。"""
        ids = self._three_published_episodes(svc, ctx, store)
        with pytest.raises(CognitionValidationError):
            svc.propose_l3(ctx, actor_role="consolidator",
                           actor="memory_consolidator",
                           statement="重复 ID 虚增",
                           source_l2_ids=[ids[0]] * 3)

    def test_candidate_not_published_until_human_approval(self, svc, ctx,
                                                          store):
        ids = self._three_published_episodes(svc, ctx, store)
        m = svc.propose_l3(ctx, actor_role="consolidator",
                           actor="memory_consolidator",
                           statement="延误前先核对上游交付时间",
                           source_l2_ids=ids)
        assert m["status"] == "candidate"
        assert svc.published_l3(ctx) == []
        with pytest.raises(CognitionValidationError):
            svc.publish_l3(m["methodology_id"], m["version"],
                           approver="", approval_id="")
        ap = approve(store, kind=APPROVAL_KIND_L3,
                     subject_ref=f"l3:{m['methodology_id']}@v"
                                 f"{m['version']}",
                     requested_by="memory_consolidator",
                     decider="human-bill")
        svc.publish_l3(m["methodology_id"], m["version"],
                       approver="human-bill", approval_id=ap)
        got = svc.published_l3(ctx)
        assert len(got) == 1 and got[0]["statement"].startswith("延误前")

    def test_counterexample_blocks_publish(self, svc, ctx, store):
        ids = self._three_published_episodes(svc, ctx, store)
        m = svc.propose_l3(ctx, actor_role="consolidator",
                           actor="memory_consolidator",
                           statement="存在反例的方法",
                           source_l2_ids=ids,
                           counterexample_ids=["ep-counter-1"])
        ap = approve(store, kind=APPROVAL_KIND_L3,
                     subject_ref=f"l3:{m['methodology_id']}@v"
                                 f"{m['version']}",
                     requested_by="memory_consolidator",
                     decider="human-bill")
        with pytest.raises(CognitionConflictError):
            svc.publish_l3(m["methodology_id"], m["version"],
                           approver="human-bill", approval_id=ap)

    def test_counterexample_recorded_after_propose_blocks_publish(
            self, svc, ctx, store):
        """提议后补录反例同样阻断发布（评审 #12）。"""
        ids = self._three_published_episodes(svc, ctx, store)
        m = svc.propose_l3(ctx, actor_role="consolidator",
                           actor="memory_consolidator",
                           statement="后来被证伪的方法",
                           source_l2_ids=ids)
        svc.record_counterexample(m["methodology_id"], m["version"],
                                  counterexample_id="ep-late-counter",
                                  actor="silent_agent")
        ap = approve(store, kind=APPROVAL_KIND_L3,
                     subject_ref=f"l3:{m['methodology_id']}@v"
                                 f"{m['version']}",
                     requested_by="memory_consolidator",
                     decider="human-bill")
        with pytest.raises(CognitionConflictError):
            svc.publish_l3(m["methodology_id"], m["version"],
                           approver="human-bill", approval_id=ap)

    def test_source_l2_must_be_published(self, svc, ctx, store):
        e1 = _l1(svc, ctx, 1)
        ep = _consolidate(svc, ctx, [e1])
        with pytest.raises(CognitionValidationError):
            svc.propose_l3(ctx, actor_role="consolidator",
                           actor="memory_consolidator",
                           statement="引用未发布 L2",
                           source_l2_ids=[ep["episode_id"], "x", "y"])

    def test_revoke_published_l3(self, svc, ctx, store):
        ids = self._three_published_episodes(svc, ctx, store)
        m = svc.propose_l3(ctx, actor_role="consolidator",
                           actor="memory_consolidator",
                           statement="将被证伪的方法",
                           source_l2_ids=ids)
        ap_pub = approve(store, kind=APPROVAL_KIND_L3,
                         subject_ref=f"l3:{m['methodology_id']}@v1",
                         requested_by="memory_consolidator",
                         decider="human-bill")
        svc.publish_l3(m["methodology_id"], 1, approver="human-bill",
                       approval_id=ap_pub)
        ap_rev = approve(store, kind="cognition.l3.revoke",
                         subject_ref=f"l3:{m['methodology_id']}@v1",
                         requested_by="silent_agent",
                         decider="human-bill")
        got = svc.revoke_l3(m["methodology_id"], 1, actor="human-bill",
                            approval_id=ap_rev)
        assert got["status"] == "revoked"
        assert svc.published_l3(ctx) == []


class TestBlackboardProjection:
    def test_current_cards_from_l1_supersession(self, svc, ctx):
        from src.platform.cognition.memory.projection import (
            current_cards_from_l1)
        e1 = _l1(svc, ctx, 1)
        e2 = svc.append_l1(
            ctx, task_id="task-1", run_id="run-2", node_id="n",
            actor_id="human", actor_kind="human", event_type="Decision",
            payload={"text": "修正结论"},
            permission_tags=("project:p1",), retention_class="permanent",
            supersedes=e1)
        cards = current_cards_from_l1(svc.store, task_id="task-1")
        ids = {c["event_id"] for c in cards}
        assert e2 in ids and e1 not in ids
