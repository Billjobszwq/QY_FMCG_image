"""Task 10（G8）测试：Claim 引证门与综合器。

要求（05 计划 Task 10）：
- 高重要性 Claim 无 span / 引证不支持 / 时间/scope 错误 / 伪造 span →
  Gate 失败，报告不得发布；
- Synthesizer 只基于已核验 Claim；报告绑定 corpus/index/model/prompt/
  policy snapshot；
- 逐 Claim verdict：pass/narrow/relabel/remove/research_more。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from src.platform.cognition.context import CognitiveContext
from src.platform.cognition.errors import CognitionPolicyError
from src.platform.cognition.research.citations import CitationVerifier
from src.platform.cognition.research.synthesizer import Synthesizer

AS_OF = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)


def _seed_run(store, run_id: str = None) -> str:
    run_id = run_id or "rrun-" + uuid.uuid4().hex[:10]
    store._conn.execute(
        "INSERT INTO research_run_v1 (research_run_id, business_run_id,"
        " question, mode, budget_json, consumed_json, state_json, status,"
        " tenant_id, customer_id, project_id, data_scope, test_run_id,"
        " permission_tags_json, created_by, created_at, updated_at)"
        " VALUES (?, 'run-x', 'q', 'lookup', '{}', '{}', '{}',"
        " 'succeeded', 'local', '', '', 'operational', '',"
        " '[\"public\"]', 'alice', '2026-08-20T00:00:00Z',"
        " '2026-08-20T00:00:00Z')", (run_id,))
    store._conn.commit()
    return run_id


def _seed_claim(store, run_id, *, claim_id=None, importance="high",
                support_status="supported", claim_type="fact") -> str:
    claim_id = claim_id or "clm-" + uuid.uuid4().hex[:8]
    store._conn.execute(
        "INSERT INTO research_claim_v1 (claim_id, research_run_id,"
        " subquestion_id, text, claim_type, importance, support_status,"
        " confidence, created_at) VALUES (?,?, 'sq-1','claim text',"
        " ?,?,?,0.9,'2026-08-20T00:00:00Z')",
        (claim_id, run_id, claim_type, importance, support_status))
    store._conn.commit()
    return claim_id


def _seed_ce(store, claim_id, span_id, relation="supports") -> None:
    store._conn.execute(
        "INSERT OR IGNORE INTO claim_evidence_v1 (claim_id, span_id,"
        " relation, verifier_score, verifier_version, created_at)"
        " VALUES (?,?,?,1.0,'verifier@1','2026-08-20T00:00:00Z')",
        (claim_id, span_id, relation))
    store._conn.commit()


@pytest.fixture()
def ctx():
    return CognitiveContext(
        principal_id="alice", tenant_id="local", customer_id="",
        project_id="", test_run_id="", data_scope="operational",
        action="cognition.research.start", permission_tags=("public",),
        purpose="cite-test", correlation_id="", parent_run_id=None,
        as_of=AS_OF)


class TestValidPath:
    def test_synthesize_real_run_binds_snapshots(self, rsvc, rctx, store):
        run = rsvc.start(rctx, question="年假多少天", mode="lookup")
        assert run["status"] == "succeeded"
        syn = Synthesizer(store)
        rep = syn.synthesize(run["research_run_id"], ctx=rctx,
                             corpus_snapshot_id="corpus-x",
                             index_snapshot_ids=["idx-1"],
                             model_profile_ids=["model-a"])
        assert rep["abstain"] is False
        assert rep["claims"], "应有已核验 claim"
        assert rep["citations"], "应有引证"
        # 每个 included fact/inference claim 都有 ≥1 引证
        cited = {c["claim_id"] for c in rep["citations"]}
        for e in rep["claims"]:
            if e["claim_type"] in ("fact", "inference"):
                assert e["claim_id"] in cited
        assert rep["snapshots"]["corpus_snapshot_id"] == "corpus-x"
        assert rep["snapshots"]["index_snapshot_ids"] == ["idx-1"]
        # 报告持久化且不可变
        row = store._conn.execute(
            "SELECT * FROM research_report_v1 WHERE report_id=?",
            (rep["report_id"],)).fetchone()
        assert row is not None


class TestCitationGateBlocks:
    def test_high_importance_without_evidence_blocked(self, store, ctx):
        run_id = _seed_run(store)
        _seed_claim(store, run_id, importance="high",
                    support_status="unsupported")
        ver = CitationVerifier(store).verify_run(run_id, ctx=ctx)
        assert ver["gate_ok"] is False
        assert ver["blocking_claims"]
        with pytest.raises(CognitionPolicyError):
            Synthesizer(store).synthesize(run_id, ctx=ctx)

    def test_fake_span_blocked(self, store, ctx):
        run_id = _seed_run(store)
        cid = _seed_claim(store, run_id, importance="high")
        _seed_ce(store, cid, "span-does-not-exist")
        ver = CitationVerifier(store).verify_run(run_id, ctx=ctx)
        assert ver["gate_ok"] is False
        v = ver["verdicts"][0]
        assert v["verdict"] == "remove"
        assert "span_missing" in v["reason"]

    def test_expired_source_citation_invalid(self, store, ctx, tmp_path):
        """来源已过 effective_to → 引证失效（temporal validity）。"""
        from src.platform.cognition.index.catalog import IndexCatalog
        from src.platform.cognition.knowledge.service import (
            APPROVAL_KIND_PUBLISH as KB_PUB, KnowledgeService)
        from src.platform.cognition.sources.service import SourceService
        from tests.cognition.helpers import approve
        sources = SourceService(store, cas_root=tmp_path / "cas")
        kb = KnowledgeService(store)
        text = "# 旧制度\n\n已于年中废止的规定。\n"
        res = sources.ingest(ctx, source_type="file",
                             original_uri="old.md",
                             media_type="text/markdown",
                             content=text.encode("utf-8"),
                             permission_tags=("public",),
                             trust_tier="authoritative")
        span_ids = [c["chunk_id"] for c in res["chunks"]]
        kb.draft(ctx, knowledge_id="kb-old", knowledge_type="policy",
                 title="旧制度", body=text, summary="旧制度", owner="hr",
                 effective_from="2026-01-01T00:00:00+00:00",
                 effective_to="2026-06-01T00:00:00+00:00",  # 早于 as_of
                 permission_tags=("public",), source_span_ids=span_ids)
        ap = approve(store, kind=KB_PUB, subject_ref="kb-old@v1",
                     requested_by="alice", decider="human-bill")
        kb.publish(ctx, "kb-old", 1, approver="human-bill",
                   approval_id=ap)
        run_id = _seed_run(store)
        cid = _seed_claim(store, run_id, importance="high")
        _seed_ce(store, cid, span_ids[0])
        ver = CitationVerifier(store).verify_run(run_id, ctx=ctx)
        assert ver["gate_ok"] is False
        assert ver["verdicts"][0]["verdict"] == "remove"
        assert "expired" in ver["verdicts"][0]["reason"]

    def test_low_importance_partial_invalid_narrows_not_blocks(
            self, store, ctx, tmp_path):
        """低重要性 claim 部分引证失效 → narrow（不阻断整份报告）。"""
        from src.platform.cognition.knowledge.service import (
            APPROVAL_KIND_PUBLISH as KB_PUB, KnowledgeService)
        from src.platform.cognition.sources.service import SourceService
        from tests.cognition.helpers import approve
        sources = SourceService(store, cas_root=tmp_path / "cas")
        kb = KnowledgeService(store)
        text = "# 制度\n\n有效规定。\n"
        res = sources.ingest(ctx, source_type="file",
                             original_uri="ok.md",
                             media_type="text/markdown",
                             content=text.encode("utf-8"),
                             permission_tags=("public",),
                             trust_tier="authoritative")
        span_ids = [c["chunk_id"] for c in res["chunks"]]
        kb.draft(ctx, knowledge_id="kb-ok", knowledge_type="policy",
                 title="制度", body=text, summary="制度", owner="hr",
                 effective_from="2026-01-01T00:00:00+00:00",
                 effective_to=None, permission_tags=("public",),
                 source_span_ids=span_ids)
        ap = approve(store, kind=KB_PUB, subject_ref="kb-ok@v1",
                     requested_by="alice", decider="human-bill")
        kb.publish(ctx, "kb-ok", 1, approver="human-bill",
                   approval_id=ap)
        run_id = _seed_run(store)
        cid = _seed_claim(store, run_id, importance="low")
        _seed_ce(store, cid, span_ids[0])          # 有效
        _seed_ce(store, cid, "span-fake")          # 失效
        ver = CitationVerifier(store).verify_run(run_id, ctx=ctx)
        assert ver["verdicts"][0]["verdict"] == "narrow"
        assert ver["gate_ok"] is True
