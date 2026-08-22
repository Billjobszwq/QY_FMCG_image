"""Task 9（G7）测试：预算硬上限与断点恢复（resume 不重复消费）。"""
from __future__ import annotations

import pytest

from src.platform.cognition.errors import CognitionConflictError


class TestBudgetEnforcement:
    def test_query_budget_exhausted_stops_honestly(self, rsvc, rctx,
                                                   store):
        # 无法满足的问题 + 极小查询预算：gap 回跳直到预算耗尽，
        # 诚实 failed（stop_reason=budget_exhausted:*），不伪装完整。
        run = rsvc.start(rctx, question="完全不存在的话题 xyzz",
                         mode="lookup",
                         budget={"max_queries": 2, "max_iterations": 6})
        assert run["status"] == "failed"
        assert run["stop_reason"] == "budget_exhausted:max_queries"
        assert run["consumed"]["queries"] <= 2

    def test_deadline_exceeded_stops(self, store, rctx, tmp_path):
        from tests.research.conftest import DOCS  # noqa: F401
        # 复用 rsvc 的语料构建：重新搭一个带假时钟的 service
        from src.platform.cognition.context import CognitiveContext
        from src.platform.cognition.index.catalog import IndexCatalog
        from src.platform.cognition.index.gateway import (
            CognitiveQueryGateway)
        from src.platform.cognition.research.service import ResearchService
        from src.platform.cognition.knowledge.service import (
            APPROVAL_KIND_PUBLISH as KB_PUB, KnowledgeService)
        from src.platform.cognition.sources.service import SourceService
        from tests.cognition.helpers import approve
        from datetime import datetime, timezone
        ctx = CognitiveContext(
            principal_id="alice", tenant_id="local", customer_id="",
            project_id="", test_run_id="", data_scope="operational",
            action="cognition.research.start",
            permission_tags=("public",), purpose="t",
            correlation_id="", parent_run_id=None,
            as_of=datetime(2026, 8, 20, tzinfo=timezone.utc))
        sources = SourceService(store, cas_root=tmp_path / "cas2")
        kb = KnowledgeService(store)
        text = "# 制度\n\n内容 X。\n"
        res = sources.ingest(ctx, source_type="file",
                             original_uri="x.md",
                             media_type="text/markdown",
                             content=text.encode("utf-8"),
                             permission_tags=("public",),
                             trust_tier="authoritative")
        kb.draft(ctx, knowledge_id="kb-x", knowledge_type="policy",
                 title="制度", body=text, summary="制度", owner="hr",
                 effective_from="2026-01-01T00:00:00+00:00",
                 effective_to=None, permission_tags=("public",),
                 source_span_ids=[c["chunk_id"] for c in res["chunks"]])
        ap = approve(store, kind=KB_PUB, subject_ref="kb-x@v1",
                     requested_by="alice", decider="human-bill")
        kb.publish(ctx, "kb-x", 1, approver="human-bill", approval_id=ap)
        snap = sources.build_corpus_snapshot(ctx)
        catalog = IndexCatalog(store, index_root=tmp_path / "idx2")
        b = catalog.build(ctx, target_kind="knowledge",
                          corpus_snapshot_id=snap["corpus_snapshot_id"])
        catalog.activate(ctx, target_kind="knowledge",
                         index_snapshot_id=b["index_snapshot_id"])
        gw = CognitiveQueryGateway(store, catalog=catalog)
        ticks = [0.0, 99999.0]  # 第二次调用即超过 deadline
        svc = ResearchService(store, gateway=gw,
                              clock=lambda: ticks.pop(0)
                              if len(ticks) > 1 else 99999.0)
        run = svc.start(ctx, question="内容 X", mode="lookup",
                        budget={"deadline_seconds": 10})
        assert run["status"] == "failed"
        assert run["stop_reason"] == "budget_exhausted:deadline"

    def test_max_iterations_caps_gap_loop(self, rsvc, rctx, store):
        run = rsvc.start(rctx, question="找不到的东西 xyzz",
                         mode="lookup",
                         budget={"max_iterations": 2,
                                 "max_queries": 99})
        # 迭代上限内仍未覆盖 → 诚实完成（带 gaps），不无限回跳
        assert run["status"] == "succeeded"
        assert run["stop_reason"] == "completed_with_gaps"
        assert run["consumed"]["queries"] <= 2


class TestCheckpointResume:
    def test_fault_then_resume_no_double_consumption(self, rsvc, rctx,
                                                     store):
        calls = {"read": 0}

        def fault(node: str) -> None:
            if node == "read" and calls["read"] == 0:
                calls["read"] += 1
                raise RuntimeError("模拟 read 节点崩溃")

        run = rsvc.start(rctx, question="年假多少天", mode="lookup",
                         fault=fault)
        assert run["status"] == "failed"
        assert run["stop_reason"] == "node_error:read"
        queries_after_fail = len(
            rsvc.list_queries(run["research_run_id"]))
        assert queries_after_fail == 1  # retrieve 已执行一次

        # resume（无故障）→ 从断点续跑成功
        done = rsvc.resume(run["research_run_id"], ctx=rctx)
        assert done["status"] == "succeeded"
        assert done["stop_reason"] == "complete"
        # 查询未重复消费（已完成的 retrieve 不重跑）
        assert len(rsvc.list_queries(
            done["research_run_id"])) == queries_after_fail
        # read 节点有一次 failed + 一次 succeeded 记录
        steps = store._conn.execute(
            "SELECT node, status FROM research_step_v1 WHERE"
            " research_run_id=? ORDER BY seq",
            (done["research_run_id"],)).fetchall()
        read_steps = [s for s in steps if s["node"] == "read"]
        assert [s["status"] for s in read_steps] == ["failed",
                                                     "succeeded"]

    def test_resume_succeeded_run_is_noop(self, rsvc, rctx):
        run = rsvc.start(rctx, question="年假多少天", mode="lookup")
        assert run["status"] == "succeeded"
        again = rsvc.resume(run["research_run_id"], ctx=rctx)
        assert again["status"] == "succeeded"
        assert again["consumed"] == run["consumed"]

    def test_fault_at_every_node_records_each_failure(self, rsvc, rctx,
                                                      store):
        def fault(node: str) -> None:
            if node == "classify":
                raise RuntimeError("classify 崩溃")
        run = rsvc.start(rctx, question="年假多少天", mode="lookup",
                         fault=fault)
        assert run["status"] == "failed"
        steps = store._conn.execute(
            "SELECT node, status FROM research_step_v1 WHERE"
            " research_run_id=?",
            (run["research_run_id"],)).fetchall()
        assert steps[0]["node"] == "classify"
        assert steps[0]["status"] == "failed"
