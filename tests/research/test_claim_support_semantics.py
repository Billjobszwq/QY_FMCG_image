"""R2-07（R2-P1-02）：Claim 支持性验证与 Citation Gate。

契约（round-2-hardening/01 §8）：
- ClaimBuilder 不得在未验证时写 supports 或 verifier_score=1.0；
- 两层验证：确定性（source/span/ACL/time/scope/locator、数字/实体/
  单位/否定）+ 支持性语义（supports/contradicts/context/insufficient），
  记录 verifier id/version、input hash、score、reason；
- span 存在 ≠ 支持：不同主体/数值/时间/否定方向/仅背景 → 高重要性
  Claim 必须 research_more/remove，不得发布；
- 验证结果持久化回 claim_evidence（relation/score/verifier_version）。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from src.platform.cognition.context import CognitiveContext
from src.platform.cognition.errors import CognitionPolicyError
from src.platform.cognition.research.citations import CitationVerifier
from src.platform.cognition.research.synthesizer import Synthesizer
from src.platform.cognition.index.catalog import IndexCatalog
from src.platform.cognition.index.gateway import CognitiveQueryGateway
from src.platform.cognition.knowledge.service import (
    APPROVAL_KIND_PUBLISH as KB_PUB, KnowledgeService)
from src.platform.cognition.research.service import ResearchService
from src.platform.cognition.sources.service import SourceService
from src.platform.data.store import PlatformStore

from tests.cognition.helpers import approve

AS_OF = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
DOC_TRAVEL = "# 差旅报销制度\n\n机票报销上限 2000 元。\n"
DOC_LEAVE = "# 年假制度\n\n入职满一年年假 5 天。\n"


@pytest.fixture()
def ctx():
    return CognitiveContext(
        principal_id="alice", tenant_id="local", customer_id="",
        project_id="", test_run_id="", data_scope="operational",
        action="cognition.research.start", permission_tags=("public",),
        purpose="claim-support-test", correlation_id="",
        parent_run_id=None, as_of=AS_OF)


@pytest.fixture()
def env(store, ctx, tmp_path):
    """发布差旅+年假知识并激活索引，返回可检索的 research service。"""
    sources = SourceService(store, cas_root=tmp_path / "cas")
    kb = KnowledgeService(store)
    span_ids = {}
    for kid, text in (("kb-travel", DOC_TRAVEL), ("kb-leave", DOC_LEAVE)):
        res = sources.ingest(ctx, source_type="file",
                             original_uri=f"{kid}.md",
                             media_type="text/markdown",
                             content=text.encode("utf-8"),
                             permission_tags=("public",),
                             trust_tier="authoritative")
        span_ids[kid] = [c["chunk_id"] for c in res["chunks"]]
        kb.draft(ctx, knowledge_id=kid, knowledge_type="policy",
                 title=kid, body=text, summary=kid, owner="hr",
                 effective_from="2026-01-01T00:00:00+00:00",
                 effective_to=None, permission_tags=("public",),
                 source_span_ids=span_ids[kid])
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
    svc = ResearchService(store, gateway=gateway)
    return {"svc": svc, "spans": span_ids}


def _seed_claim(store, run_id, *, text, importance="high",
                claim_type="fact", support_status="supported"):
    claim_id = "clm-" + uuid.uuid4().hex[:8]
    store._conn.execute(
        "INSERT INTO research_run_v1 (research_run_id,"
        " business_run_id, question, mode, budget_json, consumed_json,"
        " state_json, status, tenant_id, customer_id, project_id,"
        " data_scope, test_run_id, permission_tags_json, created_by,"
        " created_at, updated_at) VALUES (?, 'run-x', 'q', 'lookup',"
        " '{}','{}','{}','succeeded','local','','','operational','','"
        "[\"public\"]','alice','2026-08-20T00:00:00Z',"
        "'2026-08-20T00:00:00Z') ON CONFLICT(research_run_id) DO"
        " NOTHING", (run_id,))
    store._conn.execute(
        "INSERT INTO research_claim_v1 (claim_id, research_run_id,"
        " subquestion_id, text, claim_type, importance, support_status,"
        " confidence, created_at) VALUES (?,?,'sq-1',?,?,?,?,"
        " 0.9,'2026-08-20T00:00:00Z')",
        (claim_id, run_id, text, claim_type, importance, support_status))
    store._conn.commit()
    return claim_id


def _bind(store, claim_id, span_id, relation="unverified", score=0.0):
    store._conn.execute(
        "INSERT OR IGNORE INTO claim_evidence_v1 (claim_id, span_id,"
        " relation, verifier_score, verifier_version, created_at)"
        " VALUES (?,?,?,?,?,'2026-08-20T00:00:00Z')",
        (claim_id, span_id, relation, score, ""))
    store._conn.commit()


class TestNoPrematureSupport:
    def test_builder_writes_unverified_not_supports(self, env, ctx):
        """ClaimBuilder 初始关系必须是 unverified，不得预填
        supports/verifier_score=1.0。"""
        svc = env["svc"]
        observed = {}
        orig = svc.verifier.verify_run

        def spy(run_id, *, ctx):
            rows = svc.store._conn.execute(
                "SELECT relation, verifier_score FROM claim_evidence_v1"
            ).fetchall()
            observed["rows"] = [dict(r) for r in rows]
            return orig(run_id, ctx=ctx)

        svc.verifier.verify_run = spy
        run = svc.start(ctx, question="年假多少天", mode="lookup")
        assert run["status"] == "succeeded"
        assert observed["rows"], "claim 必须先落 claim_evidence"
        for r in observed["rows"]:
            assert r["relation"] == "unverified", \
                f"验证前不得写 supports: {r}"
            assert r["verifier_score"] != 1.0

    def test_unverified_relation_cannot_satisfy_gate(self, env, store, ctx):
        run_id = "rrun-" + uuid.uuid4().hex[:8]
        # 真实 span，但关系从未验证 → 不得视为支持
        cid = _seed_claim(store, run_id, text="任意高重要性断言",
                          importance="high")
        _bind(store, cid, env["spans"]["kb-leave"][0],
              relation="unverified")
        ver = CitationVerifier(store).verify_run(run_id, ctx=ctx)
        assert ver["gate_ok"] is False


class TestSupportSemantics:
    def test_contradicting_value_blocks_high_claim(self, env, store, ctx):
        """span 说 2000 元，Claim 断言 2500 元 → contradicts →
        高重要性不得发布。"""
        run_id = "rrun-" + uuid.uuid4().hex[:8]
        cid = _seed_claim(store, run_id,
                          text="机票报销上限是 2500 元", importance="high")
        _bind(store, cid, env["spans"]["kb-travel"][0])
        ver = CitationVerifier(store).verify_run(run_id, ctx=ctx)
        assert ver["gate_ok"] is False
        assert ver["verdicts"][0]["verdict"] in ("research_more",
                                                 "remove")
        # 验证结果持久化：relation 更新为 contradicts 且带 verifier 身份
        row = store._conn.execute(
            "SELECT relation, verifier_score, verifier_version FROM"
            " claim_evidence_v1 WHERE claim_id=?", (cid,)).fetchone()
        assert row["relation"] == "contradicts"
        assert row["verifier_version"]
        with pytest.raises(CognitionPolicyError):
            Synthesizer(store).synthesize(run_id, ctx=ctx)

    def test_different_subject_is_insufficient(self, env, store, ctx):
        """Claim 谈财务审批，span 谈年假 → insufficient，高重要性阻断。"""
        run_id = "rrun-" + uuid.uuid4().hex[:8]
        cid = _seed_claim(store, run_id,
                          text="财务审批限额是 999 元", importance="high")
        _bind(store, cid, env["spans"]["kb-leave"][0])
        ver = CitationVerifier(store).verify_run(run_id, ctx=ctx)
        assert ver["gate_ok"] is False
        row = store._conn.execute(
            "SELECT relation FROM claim_evidence_v1 WHERE claim_id=?",
            (cid,)).fetchone()
        assert row["relation"] in ("insufficient", "context")

    def test_matching_value_supports_and_passes(self, env, store, ctx):
        """Claim 数值/主体与 span 一致 → supports → gate 通过。"""
        run_id = "rrun-" + uuid.uuid4().hex[:8]
        cid = _seed_claim(store, run_id,
                          text="机票报销上限是 2000 元", importance="high")
        _bind(store, cid, env["spans"]["kb-travel"][0])
        ver = CitationVerifier(store).verify_run(run_id, ctx=ctx)
        assert ver["gate_ok"] is True
        row = store._conn.execute(
            "SELECT relation, verifier_score FROM claim_evidence_v1"
            " WHERE claim_id=?", (cid,)).fetchone()
        assert row["relation"] == "supports"
        assert row["verifier_score"] > 0

    def test_verdict_records_verifier_identity_and_hash(self, env, store,
                                                        ctx):
        run_id = "rrun-" + uuid.uuid4().hex[:8]
        cid = _seed_claim(store, run_id,
                          text="机票报销上限是 2000 元", importance="high")
        _bind(store, cid, env["spans"]["kb-travel"][0])
        ver = CitationVerifier(store).verify_run(run_id, ctx=ctx)
        v = ver["verdicts"][0]
        assert v.get("verifier_id"), "verdict 必须带 verifier 身份"
        assert v.get("verifier_version")
        assert v.get("input_hash"), "verdict 必须带输入 hash"
