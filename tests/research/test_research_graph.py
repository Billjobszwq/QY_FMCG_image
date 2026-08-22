"""Task 9（G7）测试：Research Graph 状态机、节点账本与冲突人工裁决。"""
from __future__ import annotations


class TestResearchStateMachine:
    def test_lookup_run_succeeds_with_cited_claims(self, rsvc, rctx,
                                                   store):
        run = rsvc.start(rctx, question="年假多少天", mode="lookup")
        assert run["status"] == "succeeded"
        assert run["stop_reason"] == "complete"
        claims = rsvc.list_claims(run["research_run_id"])
        assert len(claims) == 1
        claim = claims[0]
        assert claim["claim_type"] == "fact"
        assert claim["support_status"] == "supported"
        # claim → evidence span 绑定（每个可验证 claim 有证据）
        rows = store._conn.execute(
            "SELECT * FROM claim_evidence_v1 WHERE claim_id=?",
            (claim["claim_id"],)).fetchall()
        assert len(rows) >= 1
        assert all(r["relation"] == "supports" for r in rows)

    def test_pipeline_steps_recorded_in_order(self, rsvc, rctx, store):
        run = rsvc.start(rctx, question="年假多少天", mode="lookup")
        steps = store._conn.execute(
            "SELECT node, status FROM research_step_v1 WHERE"
            " research_run_id=? ORDER BY seq",
            (run["research_run_id"],)).fetchall()
        nodes = [s["node"] for s in steps]
        assert nodes == ["classify", "plan", "retrieve", "read",
                         "sufficiency", "claim", "finalize"]
        assert all(s["status"] == "succeeded" for s in steps)

    def test_unified_run_usage_evidence_attached(self, rsvc, rctx,
                                                 store):
        run = rsvc.start(rctx, question="年假多少天", mode="lookup")
        biz = store.get_business_run(run["business_run_id"])
        assert biz is not None and biz["status"] == "succeeded"
        assert biz["command_kind"] == "research.run"
        # NodeAttempt（统一 node execution）
        attempts = store._conn.execute(
            "SELECT node_id FROM workflow_node_execution_v1 WHERE run_id=?",
            (run["business_run_id"],)).fetchall()
        assert any(a["node_id"].startswith("research.") for a in attempts)
        # Usage（检索计量）
        usage = store._conn.execute(
            "SELECT unit, quantity FROM usage_event_v2 WHERE run_id=?",
            (run["business_run_id"],)).fetchall()
        assert any(u["unit"] == "research_query" for u in usage)
        # Evidence（研究证据 bundle）
        evid = store._conn.execute(
            "SELECT kind FROM evidence_bundle_v1 WHERE run_id=?",
            (run["business_run_id"],)).fetchall()
        assert any(e["kind"] == "research_run" for e in evid)
        # 查询账本
        queries = rsvc.list_queries(run["research_run_id"])
        assert len(queries) >= 1

    def test_insufficient_evidence_yields_unknown_claim(self, rsvc, rctx,
                                                        store):
        run = rsvc.start(rctx, question="完全不相关的主题 xyzz",
                         mode="lookup")
        assert run["status"] == "succeeded"
        assert run["stop_reason"] == "completed_with_gaps"
        claims = rsvc.list_claims(run["research_run_id"])
        assert claims[0]["claim_type"] == "unknown"
        assert claims[0]["support_status"] == "unsupported"

    def test_cancel_run(self, rsvc, rctx, store):
        run = rsvc.start(rctx, question="年假多少天", mode="lookup")
        # 已完成的 run cancel 为 no-op；用 waiting 场景另测。此处验证
        # 终态不被改写。
        got = rsvc.cancel(run["research_run_id"], actor="alice",
                              ctx=rctx)
        assert got["status"] == "succeeded"


class TestConflictRequiresHuman:
    def test_conflicting_sources_wait_for_human(self, rsvc, rctx, store):
        # “机票报销”命中 kb-travel-a 与 kb-travel-b 两个来源 → 冲突
        run = rsvc.start(rctx, question="机票报销上限是多少", mode="lookup")
        assert run["status"] == "waiting_human"
        assert run["stop_reason"] == "conflict_requires_human"
        # 未裁决前 resume 被拒
        import pytest
        from src.platform.cognition.errors import CognitionConflictError
        with pytest.raises(CognitionConflictError):
            rsvc.resume(run["research_run_id"], ctx=rctx)

    def test_human_decision_resumes_to_success(self, rsvc, rctx, store):
        run = rsvc.start(rctx, question="机票报销上限是多少", mode="lookup")
        assert run["status"] == "waiting_human"
        done = rsvc.decide_conflict(
            run["research_run_id"], actor="human-bill",
            resolution="以制度A为准", ctx=rctx)
        assert done["status"] == "succeeded"
        claims = rsvc.list_claims(done["research_run_id"])
        assert claims and claims[0]["support_status"] == "supported"
