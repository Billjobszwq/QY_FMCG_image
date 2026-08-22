"""Task 8（G6）红测试：联邦混合检索（功能面）。

要求（05 计划 Task 8）：
- lexical baseline；index build manifest/hash/quality + active registry CAS；
- embedding provider 不可用 → degraded，不返回假向量；
- RRF 融合 + 文档多样性去重 + score trace；
- SKU .kb Domain Retriever 适配不写入企业 KB。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.platform.cognition.context import CognitiveContext
from src.platform.cognition.contracts import CognitiveQueryRequest
from src.platform.cognition.errors import CognitionIntegrityError
from src.platform.cognition.index.catalog import IndexCatalog
from src.platform.cognition.index.gateway import CognitiveQueryGateway
from src.platform.cognition.sources.service import SourceService
from src.platform.cognition.knowledge.service import (
    APPROVAL_KIND_PUBLISH as APPROVAL_KIND_KB,
    KnowledgeService,
)
from src.platform.cognition.index.vector import UnavailableVectorProvider

from .helpers import approve
from src.platform.data.store import PlatformStore

AS_OF = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)

DOC_TRAVEL = ("# 差旅报销制度\n\n## 限额\n\n高铁二等座全额报销；"
              "机票经济舱上限 2000 元。\n")
DOC_LEAVE = ("# 请假制度\n\n## 年假\n\n入职满一年享有 5 天年假。\n")


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


@pytest.fixture()
def ctx():
    return CognitiveContext(
        principal_id="alice", tenant_id="local", customer_id="",
        project_id="", test_run_id="", data_scope="operational",
        action="cognition.knowledge.search",
        permission_tags=("public",), purpose="retrieval-test",
        correlation_id="corr-1", parent_run_id=None, as_of=AS_OF)


@pytest.fixture()
def env(store, ctx, tmp_path):
    """摄取+发布两份制度文档，构建 lexical 索引并激活。"""
    sources = SourceService(store, cas_root=tmp_path / "cas")
    kb = KnowledgeService(store)
    for uri, text, kid, title in (
            ("policies/travel.md", DOC_TRAVEL, "kb-travel", "差旅报销制度"),
            ("policies/leave.md", DOC_LEAVE, "kb-leave", "请假制度")):
        res = sources.ingest(ctx, source_type="file", original_uri=uri,
                             media_type="text/markdown",
                             content=text.encode("utf-8"),
                             permission_tags=("public",),
                             trust_tier="authoritative")
        doc = res["document"]
        span_ids = [c["chunk_id"] for c in res["chunks"]]
        kb.draft(ctx, knowledge_id=kid, knowledge_type="policy",
                 title=title, body=text, summary=title, owner="hr",
                 effective_from="2026-01-01T00:00:00+00:00",
                 effective_to=None, permission_tags=("public",),
                 source_span_ids=span_ids)
        ap = approve(store, kind=APPROVAL_KIND_KB,
                     subject_ref=f"{kid}@v1", requested_by="alice",
                     decider="human-bill")
        kb.publish(ctx, kid, 1, approver="human-bill", approval_id=ap)
    snap = sources.build_corpus_snapshot(ctx)
    catalog = IndexCatalog(store, index_root=tmp_path / "index")
    build = catalog.build(ctx, target_kind="knowledge",
                          corpus_snapshot_id=snap["corpus_snapshot_id"])
    catalog.activate(ctx, target_kind="knowledge",
                     index_snapshot_id=build["index_snapshot_id"])
    gateway = CognitiveQueryGateway(store, catalog=catalog)
    return {"sources": sources, "kb": kb, "catalog": catalog,
            "gateway": gateway, "snapshot": snap, "build": build}


def _req(query: str, kinds=("knowledge",), mode="lookup"):
    return CognitiveQueryRequest(query=query, target_kinds=kinds,
                                 mode=mode, top_k=8)


class TestLexicalBaseline:
    def test_lookup_exact_term_hits_right_doc(self, env, ctx):
        r = env["gateway"].search(_req("机票经济舱上限"), ctx)
        assert r.candidates
        top = r.candidates[0]
        assert top.target_kind == "knowledge"
        assert top.target_id.startswith("kb-travel")
        assert top.score_breakdown.get("lexical", 0) > 0
        # 可定位证据：span 携带 chunk locator
        assert top.spans
        loc = top.spans[0].locator
        assert loc.get("chunk_id") and "char_start" in loc

    def test_query_for_leave_policy(self, env, ctx):
        r = env["gateway"].search(_req("年假"), ctx)
        assert r.candidates and r.candidates[0].target_id == "kb-leave"

    def test_no_hit_returns_empty_not_error(self, env, ctx):
        r = env["gateway"].search(_req("完全无关的查询词 xyzz"), ctx)
        assert not r.candidates
        assert r.degraded is False


class TestIndexBuildRegistry:
    def test_build_idempotent(self, env, ctx):
        b1 = env["build"]
        b2 = env["catalog"].build(ctx, target_kind="knowledge",
                                  corpus_snapshot_id=(
                                      env["snapshot"]["corpus_snapshot_id"]))
        assert b1["index_snapshot_id"] == b2["index_snapshot_id"]
        assert env["catalog"].count_builds(target_kind="knowledge") == 1

    def test_build_records_manifest_and_quality(self, env):
        b = env["build"]
        assert len(b["source_manifest_hash"]) == 64
        assert b["build_status"] == "ready"
        assert b["item_count"] > 0
        assert b["quality_report"]

    def test_activation_hash_mismatch_fails_closed(self, env, ctx):
        b = env["build"]
        with pytest.raises(CognitionIntegrityError):
            env["catalog"].activate(
                ctx, target_kind="knowledge",
                index_snapshot_id=b["index_snapshot_id"],
                expected_hash="f" * 64)

    def test_active_registry_returns_activated_build(self, env):
        active = env["catalog"].active("knowledge")
        assert active["index_snapshot_id"] == \
            env["build"]["index_snapshot_id"]

    def test_missing_active_fails_closed(self, store, tmp_path):
        catalog = IndexCatalog(store, index_root=tmp_path / "index2")
        assert catalog.active("skill") is None


class TestHybridFusion:
    class _FakeVector:
        """确定性伪向量 provider：按字符 hash 生成，仅用于测试融合。"""

        def available(self):
            return True

        def encode(self, texts):
            out = []
            for t in texts:
                vec = [0.0] * 8
                for i, ch in enumerate(t):
                    vec[ord(ch) % 8] += 1.0
                norm = sum(v * v for v in vec) ** 0.5 or 1.0
                out.append([v / norm for v in vec])
            return out

    def test_rrf_merges_lexical_and_dense_with_trace(self, store, ctx,
                                                     tmp_path):
        sources = SourceService(store, cas_root=tmp_path / "cas")
        kb = KnowledgeService(store)
        res = sources.ingest(ctx, source_type="file",
                             original_uri="t.md",
                             media_type="text/markdown",
                             content=DOC_TRAVEL.encode("utf-8"),
                             permission_tags=("public",),
                             trust_tier="authoritative")
        kb.draft(ctx, knowledge_id="kb-t", knowledge_type="policy",
                 title="差旅报销制度", body=DOC_TRAVEL, summary="差旅",
                 owner="hr", effective_from="2026-01-01T00:00:00+00:00",
                 effective_to=None, permission_tags=("public",),
                 source_span_ids=[c["chunk_id"] for c in res["chunks"]])
        ap = approve(store, kind=APPROVAL_KIND_KB,
                     subject_ref="kb-t@v1", requested_by="alice",
                     decider="human-bill")
        kb.publish(ctx, "kb-t", 1, approver="human-bill",
                   approval_id=ap)
        snap = sources.build_corpus_snapshot(ctx)
        catalog = IndexCatalog(store, index_root=tmp_path / "index")
        build = catalog.build(ctx, target_kind="knowledge",
                              corpus_snapshot_id=snap["corpus_snapshot_id"],
                              vector_provider=self._FakeVector())
        catalog.activate(ctx, target_kind="knowledge",
                         index_snapshot_id=build["index_snapshot_id"])
        gw = CognitiveQueryGateway(store, catalog=catalog,
                                   vector_provider=self._FakeVector())
        r = gw.search(_req("机票报销"), ctx)
        assert r.candidates
        sb = r.candidates[0].score_breakdown
        assert "lexical" in sb and "dense" in sb and "fusion" in sb
        assert r.degraded is False

    def test_vector_unavailable_degrades_honestly(self, env, ctx,
                                                     store):
        # 配置了 provider 但不可用：lexical 仍返回，显式 degraded，
        # 不造假向量（与 lexical-only 基线的 degraded=False 区分）
        gw = CognitiveQueryGateway(store, catalog=env["catalog"],
                                   vector_provider=(
                                       UnavailableVectorProvider()))
        r = gw.search(_req("机票经济舱上限"), ctx)
        assert r.candidates
        assert r.degraded is True
        assert r.candidates[0].score_breakdown.get("dense") is None


class TestDiversityDedup:
    def test_same_document_candidates_capped(self, store, ctx, tmp_path):
        long_doc = "# 手册\n\n" + "\n\n".join(
            f"## 第{i}节\n\n条款内容 编号 T-{i} 明细。" for i in range(8))
        sources = SourceService(store, cas_root=tmp_path / "cas")
        kb = KnowledgeService(store)
        res = sources.ingest(ctx, source_type="file",
                             original_uri="manual.md",
                             media_type="text/markdown",
                             content=long_doc.encode("utf-8"),
                             permission_tags=("public",),
                             trust_tier="authoritative")
        kb.draft(ctx, knowledge_id="kb-manual", knowledge_type="process",
                 title="手册", body=long_doc, summary="手册", owner="ops",
                 effective_from="2026-01-01T00:00:00+00:00",
                 effective_to=None, permission_tags=("public",),
                 source_span_ids=[c["chunk_id"] for c in res["chunks"]])
        ap = approve(store, kind=APPROVAL_KIND_KB,
                     subject_ref="kb-manual@v1", requested_by="alice",
                     decider="human-bill")
        kb.publish(ctx, "kb-manual", 1, approver="human-bill",
                   approval_id=ap)
        snap = sources.build_corpus_snapshot(ctx)
        catalog = IndexCatalog(store, index_root=tmp_path / "index")
        b = catalog.build(ctx, target_kind="knowledge",
                          corpus_snapshot_id=snap["corpus_snapshot_id"])
        catalog.activate(ctx, target_kind="knowledge",
                         index_snapshot_id=b["index_snapshot_id"])
        gw = CognitiveQueryGateway(store, catalog=catalog)
        r = gw.search(_req("条款内容 编号"), ctx, max_per_document=2)
        docs = [c.target_id for c in r.candidates]
        assert docs.count("kb-manual") <= 2


class TestSkuKbAdapterIsolation:
    def test_sku_kb_adapter_does_not_write_enterprise_kb(self, store, ctx):
        from src.platform.cognition.index.sku_kb import SkuKbDomainRetriever
        before = store._conn.execute(
            "SELECT count(*) c FROM knowledge_item_version").fetchone()["c"]
        adapter = SkuKbDomainRetriever(store, kb_dir=None)
        hits = adapter.search("sku 可乐", ctx)
        assert isinstance(hits, list)
        after = store._conn.execute(
            "SELECT count(*) c FROM knowledge_item_version").fetchone()["c"]
        assert before == after


class TestMultiKindLifecycleRetrieval:
    """各 source kind 使用各自 lifecycle filter：仅 published 可见。"""

    def _setup(self, store, ctx, tmp_path):
        from src.platform.cognition.skills.service import (
            APPROVAL_KIND_PUBLISH as SK_PUB, SkillService)
        from src.platform.cognition.memory.service import (
            APPROVAL_KIND_L2, MemoryLifecycleService)
        from .helpers import approve
        # skill：一个 draft（不可见）
        sk = SkillService(store)
        sk.draft(ctx, skill_id="sk-geo", name="地理编码",
                 description="地址解析为坐标", skill_type="curated",
                 input_schema={"type": "object"},
                 output_schema={"type": "object"},
                 execution_ref="capability:geo.geocode",
                 tool_scopes=["geo.read"], risk_level="low",
                 applicable_scenarios=["地址补全"],
                 forbidden_scenarios=[], source_refs=[],
                 evaluation_ref="eval:x", permission_tags=("public",))
        sk.validate(ctx, "sk-geo", 1, actor="curator")
        ap = approve(store, kind=SK_PUB, subject_ref="sk-geo@v1",
                     requested_by="alice", decider="human-bill")
        sk.publish(ctx, "sk-geo", 1, approver="human-bill",
                   approval_id=ap)
        # memory L2：一个 published episode
        mem = MemoryLifecycleService(store)
        e1 = mem.append_l1(ctx, task_id="t-1", run_id="r-1", node_id="n",
                           actor_id="agent", actor_kind="agent",
                           event_type="Finding", payload={"x": 1},
                           permission_tags=("public",))
        ep = mem.consolidate_l1_to_l2(
            ctx, actor_role="consolidator", actor="memory_consolidator",
            task_id="t-1", period_start="2026-08-01",
            period_end="2026-08-20", l1_ids=[e1],
            solution="差旅报销先提交申请", result="已报销")
        ap2 = approve(store, kind=APPROVAL_KIND_L2,
                      subject_ref=f"l2:{ep['episode_id']}",
                      requested_by="memory_consolidator",
                      decider="human-bill")
        mem.publish_l2(ep["episode_id"], approver="human-bill",
                       approval_id=ap2)
        return sk, mem, ep

    def test_skill_and_memory_published_only(self, store, ctx, tmp_path):
        from src.platform.cognition.contracts import (
            CognitiveQueryRequest)
        self._setup(store, ctx, tmp_path)
        gw = CognitiveQueryGateway(store, catalog=IndexCatalog(
            store, index_root=tmp_path / "idx"))
        r = gw.search(CognitiveQueryRequest(
            query="地理编码 地址", target_kinds=("skill",),
            mode="lookup", top_k=5), ctx)
        assert any(c.target_kind == "skill" and c.target_id == "sk-geo"
                   for c in r.candidates)
        r2 = gw.search(CognitiveQueryRequest(
            query="差旅报销 申请", target_kinds=("memory_l2",),
            mode="case_analysis", top_k=5), ctx)
        assert any(c.target_kind == "memory_l2" for c in r2.candidates)

    def test_draft_skill_not_retrievable(self, store, ctx, tmp_path):
        from src.platform.cognition.skills.service import SkillService
        from src.platform.cognition.contracts import (
            CognitiveQueryRequest)
        sk = SkillService(store)
        sk.draft(ctx, skill_id="sk-draft", name="草稿技能",
                 description="未发布", skill_type="curated",
                 input_schema={}, output_schema={},
                 execution_ref="", tool_scopes=[], risk_level="low",
                 applicable_scenarios=[], forbidden_scenarios=[],
                 source_refs=[], evaluation_ref="",
                 permission_tags=("public",))
        gw = CognitiveQueryGateway(store, catalog=IndexCatalog(
            store, index_root=tmp_path / "idx"))
        r = gw.search(CognitiveQueryRequest(
            query="草稿技能", target_kinds=("skill",), mode="lookup",
            top_k=5), ctx)
        assert not any(c.target_id == "sk-draft" for c in r.candidates)


class TestRerank:
    class _LenReranker:
        model_name = "len-rerank"

        def available(self):
            return True

        def rerank(self, query, items):
            # 以文本长度打分：验证 rerank 分进入 breakdown
            return [float(len(i["text"])) for i in items]

    def test_rerank_score_in_breakdown(self, env, ctx, store):
        gw = CognitiveQueryGateway(store, catalog=env["catalog"],
                                   reranker=self._LenReranker())
        r = gw.search(_req("机票经济舱上限"), ctx)
        assert r.candidates
        top = r.candidates[0]
        assert top.score_breakdown.get("rerank") is not None
