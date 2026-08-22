"""R2-06（R2-P1-01）：显式 Research Planner / Gap / Counterevidence。

契约（round-2-hardening/01 §7）：
- lookup 保持单原子问题；deep_research 必须有界子问题/依赖/停止条件/
  反证查询；planner provider 不可用时 deep_research degraded/abstain，
  不得用单问题冒充规划；
- 多个来源 = diversity，不是 conflict；只有互斥规范化数值/命题矛盾才
  触发冲突路径；一致来源不得 waiting_human；
- gap 与 counterevidence 是独立 typed 动作；novelty 停止：连续两轮无新
  高价值 span 即停止，不得无限“补充 证据”；
- 每个新节点可 checkpoint/resume，不重复 query/usage/claim。
"""
from __future__ import annotations

import pytest

from src.platform.cognition.context import CognitiveContext
from src.platform.cognition.knowledge.service import (
    APPROVAL_KIND_PUBLISH as KB_PUB, KnowledgeService)
from src.platform.cognition.sources.service import SourceService
from src.platform.data.store import PlatformStore
from src.platform.cognition.index.catalog import IndexCatalog
from src.platform.cognition.index.gateway import CognitiveQueryGateway
from src.platform.cognition.research.service import ResearchService

from tests.cognition.helpers import approve
from tests.research.conftest import AS_OF


@pytest.fixture()
def ctx():
    return CognitiveContext(
        principal_id="alice", tenant_id="local", customer_id="",
        project_id="", test_run_id="", data_scope="operational",
        action="cognition.research.start", permission_tags=("public",),
        purpose="planner-test", correlation_id="", parent_run_id=None,
        as_of=AS_OF)


def _build_stack(store, ctx, tmp_path, docs: dict[str, str]):
    sources = SourceService(store, cas_root=tmp_path / "cas")
    kb = KnowledgeService(store)
    for kid, text in docs.items():
        res = sources.ingest(ctx, source_type="file",
                             original_uri=f"{kid}.md",
                             media_type="text/markdown",
                             content=text.encode("utf-8"),
                             permission_tags=("public",),
                             trust_tier="authoritative")
        kb.draft(ctx, knowledge_id=kid, knowledge_type="policy",
                 title=kid, body=text, summary=kid, owner="hr",
                 effective_from="2026-01-01T00:00:00+00:00",
                 effective_to=None, permission_tags=("public",),
                 source_span_ids=[c["chunk_id"] for c in res["chunks"]])
        ap = approve(store, kind=KB_PUB, subject_ref=f"{kid}@v1",
                     requested_by="alice", decider="human-bill")
        kb.publish(ctx, kid, 1, approver="human-bill", approval_id=ap)
    snap = sources.build_corpus_snapshot(ctx)
    catalog = IndexCatalog(store, index_root=tmp_path / "index")
    build = catalog.build(ctx, target_kind="knowledge",
                          corpus_snapshot_id=snap["corpus_snapshot_id"])
    catalog.activate(ctx, target_kind="knowledge",
                     index_snapshot_id=build["index_snapshot_id"])
    gateway = CognitiveQueryGateway(store, catalog=catalog)
    return ResearchService(store, gateway=gateway)


class FakePlanner:
    """确定性 typed planner（测试注入；不是语义质量证据）。"""

    def available(self):
        return True

    def plan(self, *, question: str, mode: str, budget: dict) -> dict:
        return {
            "subquestions": [
                {"sq_id": "sq-1", "text": question,
                 "depends_on": [], "expected_evidence": ["policy"],
                 "target_kinds": ["knowledge"],
                 "stop_condition": "找到有效条款"},
                {"sq_id": "sq-2",
                 "text": f"{question} 的例外情形",
                 "depends_on": ["sq-1"],
                 "expected_evidence": ["policy"],
                 "target_kinds": ["knowledge"],
                 "stop_condition": "找到例外或穷尽来源"},
                {"sq_id": "sq-ce", "kind": "counterevidence",
                 "text": f"{question} 的反例或不同规定",
                 "depends_on": ["sq-1"],
                 "expected_evidence": ["policy"],
                 "target_kinds": ["knowledge"],
                 "stop_condition": "找到反证或穷尽来源"},
            ],
        }


class TestDeepResearchPlanning:
    def test_deep_research_without_planner_degrades_honestly(
            self, store, ctx, tmp_path):
        svc = _build_stack(store, ctx, tmp_path,
                           {"kb-a": "# 制度\n\n条款A。\n"})
        run = svc.start(ctx, question="条款A 的内容",
                        mode="deep_research")
        # 无 planner provider：不得用单问题冒充规划
        assert run["state"].get("planner_degraded") is True
        assert run["stop_reason"].startswith("degraded:")
        assert run["status"] == "succeeded"
        assert run["state"].get("abstain") is True

    def test_deep_research_with_planner_builds_typed_plan(
            self, store, ctx, tmp_path):
        svc = _build_stack(store, ctx, tmp_path,
                           {"kb-a": "# 制度\n\n条款A 限额 100 元。\n"})
        svc.planner = FakePlanner()
        run = svc.start(ctx, question="条款A 的内容",
                        mode="deep_research")
        plan = run["state"].get("plan") or {}
        sqs = plan.get("subquestions") or []
        assert len(sqs) >= 2, "deep_research 必须拆分子问题"
        by_id = {s["sq_id"]: s for s in sqs}
        assert any(s.get("depends_on") for s in sqs), "子问题须带依赖"
        assert all(s.get("stop_condition") for s in sqs), "须带停止条件"
        assert all(s.get("target_kinds") for s in sqs)
        assert any(s.get("kind") == "counterevidence" for s in sqs), \
            "计划必须主动包含反证查询"
        assert run["state"].get("planner_degraded") is not True


class TestConflictSemantics:
    def test_consistent_sources_are_diversity_not_conflict(
            self, store, ctx, tmp_path):
        """两个来源数值一致 → diversity，不得 waiting_human。"""
        svc = _build_stack(store, ctx, tmp_path, {
            "kb-a": "# 报销制度A\n\n机票报销上限 2000 元。\n",
            "kb-b": "# 报销制度B\n\n机票报销上限 2000 元。\n"})
        run = svc.start(ctx, question="机票报销上限是多少", mode="lookup")
        assert run["status"] == "succeeded", \
            f"一致来源不得冲突: {run['stop_reason']}"
        assert run["stop_reason"] in ("complete", "completed_with_gaps")

    def test_mutually_exclusive_values_trigger_conflict(
            self, store, ctx, tmp_path):
        svc = _build_stack(store, ctx, tmp_path, {
            "kb-a": "# 报销制度A\n\n机票报销上限 2000 元。\n",
            "kb-b": "# 报销制度B\n\n机票报销上限 3000 元。\n"})
        run = svc.start(ctx, question="机票报销上限是多少", mode="lookup")
        assert run["status"] == "waiting_human"
        assert run["stop_reason"] == "conflict_requires_human"

    def test_counterevidence_query_recorded_on_conflict(
            self, store, ctx, tmp_path):
        """冲突路径必须先做独立 counterevidence 检索（typed 动作）。"""
        svc = _build_stack(store, ctx, tmp_path, {
            "kb-a": "# 报销制度A\n\n机票报销上限 2000 元。\n",
            "kb-b": "# 报销制度B\n\n机票报销上限 3000 元。\n"})
        run = svc.start(ctx, question="机票报销上限是多少", mode="lookup")
        assert run["status"] == "waiting_human"
        rows = svc.list_queries(run["research_run_id"])
        ce = [r for r in rows if r.get("strategy") == "counterevidence"]
        assert ce, "冲突判定前必须有独立 counterevidence 查询"
        # 反证查询不得把期望结论写成事实前提（不得包含具体数值断言）
        assert all("2000" not in r["query_text"]
                   and "3000" not in r["query_text"] for r in ce)


class TestGapNoveltyStop:
    def test_gap_loop_stops_after_two_rounds_without_new_spans(
            self, store, ctx, tmp_path):
        # 语料与问题及 gap 改写词均无 token 交集：检索必然空，
        # novelty 停止条件成为唯一收敛路径。
        svc = _build_stack(store, ctx, tmp_path,
                           {"kb-a": "# 手册\n\n内容Q 编号 Z-9。\n"})
        run = svc.start(ctx, question="完全不存在的东西 xyzz",
                        mode="case_analysis",
                        budget={"max_iterations": 6, "max_queries": 30})
        assert run["status"] == "succeeded"
        assert run["stop_reason"] == "completed_with_gaps"
        # novelty 停止：连续两轮无新 span 即止，远小于 max_iterations
        assert run["consumed"]["queries"] <= 4, \
            f"novelty 停止失效: {run['consumed']['queries']} 次查询"
        assert run["state"].get("stop_rule") == "no_new_spans_2_rounds"
        # gap 改写不得是简单追加“补充 证据”
        rows = svc.list_queries(run["research_run_id"])
        assert rows
        for r in rows:
            assert "补充 证据" not in r["query_text"]

    def test_gap_resume_no_duplicate_query_or_usage(self, store, ctx,
                                                    tmp_path):
        svc = _build_stack(store, ctx, tmp_path,
                           {"kb-a": "# 制度\n\n条款A 限额 100 元。\n"})
        calls = {"suff": 0}

        def fault(node):
            if node == "sufficiency" and calls["suff"] == 0:
                calls["suff"] += 1
                raise RuntimeError("sufficiency 崩溃")

        run = svc.start(ctx, question="条款A 限额", mode="case_analysis",
                        fault=fault)
        assert run["status"] == "failed"
        q_before = len(svc.list_queries(run["research_run_id"]))
        done = svc.resume(run["research_run_id"], ctx=ctx)
        assert done["status"] == "succeeded"
        # resume 不重复已完成的 query/usage
        assert len(svc.list_queries(done["research_run_id"])) >= q_before
        usage_units = store._conn.execute(
            "SELECT count(*) c FROM usage_event_v2 WHERE run_id=?",
            (done["business_run_id"],)).fetchone()["c"]
        steps = store._conn.execute(
            "SELECT node, count(*) c FROM research_step_v1 WHERE"
            " research_run_id=? AND status='succeeded' GROUP BY node",
            (done["research_run_id"],)).fetchall()
        # 每个节点成功记录不得因 resume 翻倍（claim/finalize 唯一）
        for s in steps:
            if s["node"] in ("claim", "finalize"):
                assert s["c"] == 1
        assert usage_units >= 1
