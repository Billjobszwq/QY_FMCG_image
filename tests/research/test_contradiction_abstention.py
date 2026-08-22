"""Task 10（G8）测试：冲突并列与证据不足 abstain（不编造）。"""
from __future__ import annotations

import uuid

import pytest

from src.platform.cognition.errors import CognitionPolicyError
from src.platform.cognition.research.citations import CitationVerifier
from src.platform.cognition.research.synthesizer import Synthesizer

from .test_claim_citation_gate import _seed_ce, _seed_claim, _seed_run


class TestContradiction:
    def test_contradicted_high_claim_blocks_publish(self, store, rctx,
                                                    tmp_path):
        """有反证的 claim → research_more；高重要性 → gate 失败。"""
        from src.platform.cognition.knowledge.service import (
            APPROVAL_KIND_PUBLISH as KB_PUB, KnowledgeService)
        from src.platform.cognition.sources.service import SourceService
        from tests.cognition.helpers import approve
        sources = SourceService(store, cas_root=tmp_path / "cas")
        kb = KnowledgeService(store)
        text = "# 制度\n\n报销上限 2000 元。\n"
        res = sources.ingest(rctx, source_type="file",
                             original_uri="s.md",
                             media_type="text/markdown",
                             content=text.encode("utf-8"),
                             permission_tags=("public",),
                             trust_tier="authoritative")
        span_ids = [c["chunk_id"] for c in res["chunks"]]
        kb.draft(rctx, knowledge_id="kb-s", knowledge_type="policy",
                 title="制度", body=text, summary="制度", owner="hr",
                 effective_from="2026-01-01T00:00:00+00:00",
                 effective_to=None, permission_tags=("public",),
                 source_span_ids=span_ids)
        ap = approve(store, kind=KB_PUB, subject_ref="kb-s@v1",
                     requested_by="alice", decider="human-bill")
        kb.publish(rctx, "kb-s", 1, approver="human-bill",
                   approval_id=ap)
        run_id = _seed_run(store)
        cid = _seed_claim(store, run_id, importance="high",
                          support_status="contradicted")
        _seed_ce(store, cid, span_ids[0], relation="supports")
        _seed_ce(store, cid, span_ids[0], relation="contradicts")
        ver = CitationVerifier(store).verify_run(run_id, ctx=rctx)
        assert ver["verdicts"][0]["verdict"] == "research_more"
        assert ver["gate_ok"] is False
        with pytest.raises(CognitionPolicyError):
            Synthesizer(store).synthesize(run_id, ctx=rctx)

    def test_contradiction_surfaced_not_silently_resolved(self, store,
                                                          rctx):
        """冲突必须显式 surfaced（research_more），不静默选边。"""
        run_id = _seed_run(store)
        cid = _seed_claim(store, run_id, importance="low",
                          support_status="contradicted")
        _seed_ce(store, cid, "sp-1", relation="contradicts")
        ver = CitationVerifier(store).verify_run(run_id, ctx=rctx)
        assert ver["verdicts"][0]["verdict"] == "research_more"
        # 低重要性不阻断 gate，但 verdict 必须是冲突处理而非 pass
        assert ver["verdicts"][0]["verdict"] != "pass"


class TestAbstention:
    def test_insufficient_evidence_abstains(self, rsvc, rctx, store):
        """证据不足 → abstain，不编造结论。"""
        run = rsvc.start(rctx, question="完全不相关 xyzz", mode="lookup")
        assert run["status"] == "succeeded"
        assert run["stop_reason"] == "completed_with_gaps"
        syn = Synthesizer(store)
        rep = syn.synthesize(run["research_run_id"], ctx=rctx)
        # unknown claim 被 remove（unsupported）→ 无有效 claim → abstain
        assert rep["abstain"] is True
        assert rep["body"]["note"], "abstain 必须显式说明"
        # 无编造的 fact
        assert rep["body"]["sections"]["facts"] == []

    def test_abstain_report_still_persisted(self, rsvc, rctx, store):
        run = rsvc.start(rctx, question="无关主题 xyzz", mode="lookup")
        rep = Synthesizer(store).synthesize(run["research_run_id"],
                                            ctx=rctx)
        row = store._conn.execute(
            "SELECT abstain FROM research_report_v1 WHERE report_id=?",
            (rep["report_id"],)).fetchone()
        assert row is not None and row["abstain"] == 1
