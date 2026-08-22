"""R2-05（R2-P1-04）：真实 Vector Provider 端口与不可混淆索引身份。

契约（round-2-hardening/01 §6）：
- provider 协议至少含 provider_id/model_name/model_revision/dimension/
  normalization_version/encode_documents/encode_queries/available；
- index_snapshot_id 覆盖 target kind、corpus、backend、provider/model/
  revision/dimension、normalization、analyzer、chunk policy、canonical
  parameters；相同 corpus 下不同 dense model/参数必须不同 snapshot；
  旧 lexical build 不得被 dense build 复用；
- build 与 query provider 不一致时 fail-closed/degraded（provider_mismatch），
  不得比较不同模型向量；
- OpenAI-compatible adapter：key 只来自环境配置，不进入日志/artifact/
  identity；hermetic 测试不联网，用注入的确定性 fake 验证协议。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.platform.cognition.context import CognitiveContext
from src.platform.cognition.contracts import CognitiveQueryRequest
from src.platform.cognition.index.catalog import IndexCatalog
from src.platform.cognition.index.gateway import CognitiveQueryGateway
from src.platform.cognition.index.vector import UnavailableVectorProvider
from src.platform.cognition.knowledge.service import (
    APPROVAL_KIND_PUBLISH as KB_PUB, KnowledgeService)
from src.platform.cognition.sources.service import SourceService
from src.platform.data.store import PlatformStore

from tests.cognition.helpers import approve

AS_OF = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
DOC = "# 差旅报销制度\n\n机票经济舱上限 2000 元。\n"


class FakeProvider:
    """确定性伪向量（仅验证协议/身份/融合；不作为语义质量证据）。"""

    def __init__(self, *, provider_id="fake", model_name="model-1",
                 model_revision="rev-1", dimension=8,
                 normalization_version="norm-1", seed=0):
        self.provider_id = provider_id
        self.model_name = model_name
        self.model_revision = model_revision
        self.dimension = dimension
        self.normalization_version = normalization_version
        self._seed = seed

    def available(self):
        return True

    def _encode(self, texts):
        out = []
        for t in texts:
            vec = [0.0] * self.dimension
            h = hashlib.sha256(
                f"{self._seed}:{t}".encode("utf-8")).digest()
            for i in range(self.dimension):
                vec[i] = (h[i % len(h)] + i) % 7 - 3
            n = sum(v * v for v in vec) ** 0.5 or 1.0
            out.append([v / n for v in vec])
        return out

    def encode_documents(self, texts):
        return self._encode(texts)

    def encode_queries(self, texts):
        return self._encode(texts)


@pytest.fixture()
def store(tmp_path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


@pytest.fixture()
def ctx():
    return CognitiveContext(
        principal_id="alice", tenant_id="local", customer_id="",
        project_id="", test_run_id="", data_scope="operational",
        action="cognition.knowledge.search", permission_tags=("public",),
        purpose="vec-test", correlation_id="", parent_run_id=None,
        as_of=AS_OF)


@pytest.fixture()
def corpus(store, ctx, tmp_path):
    """一份已发布知识 + corpus snapshot。"""
    sources = SourceService(store, cas_root=tmp_path / "cas")
    kb = KnowledgeService(store)
    res = sources.ingest(ctx, source_type="file", original_uri="t.md",
                         media_type="text/markdown",
                         content=DOC.encode("utf-8"),
                         permission_tags=("public",),
                         trust_tier="authoritative")
    kb.draft(ctx, knowledge_id="kb-t", knowledge_type="policy",
             title="差旅报销制度", body=DOC, summary="差旅", owner="hr",
             effective_from="2026-01-01T00:00:00+00:00",
             effective_to=None, permission_tags=("public",),
             source_span_ids=[c["chunk_id"] for c in res["chunks"]])
    ap = approve(store, kind=KB_PUB, subject_ref="kb-t@v1",
                 requested_by="alice", decider="human-bill")
    kb.publish(ctx, "kb-t", 1, approver="human-bill", approval_id=ap)
    snap = sources.build_corpus_snapshot(ctx)
    return snap["corpus_snapshot_id"]


def _req(q="机票报销"):
    return CognitiveQueryRequest(query=q, target_kinds=("knowledge",),
                                 mode="lookup", top_k=5)


class TestIndexIdentity:
    def test_identity_varies_by_provider_model_dimension_params(
            self, store, ctx, corpus, tmp_path):
        cat = IndexCatalog(store, index_root=tmp_path / "idx")
        ids = set()
        # 1) lexical（无 provider）
        b0 = cat.build(ctx, target_kind="knowledge",
                       corpus_snapshot_id=corpus)
        ids.add(b0["index_snapshot_id"])
        # 2) provider-a / model-1 / dim8
        b1 = cat.build(ctx, target_kind="knowledge",
                       corpus_snapshot_id=corpus,
                       vector_provider=FakeProvider())
        ids.add(b1["index_snapshot_id"])
        # 3) provider-a / model-2
        b2 = cat.build(ctx, target_kind="knowledge",
                       corpus_snapshot_id=corpus,
                       vector_provider=FakeProvider(model_name="model-2"))
        ids.add(b2["index_snapshot_id"])
        # 4) provider-a / model-1 / dim16
        b3 = cat.build(ctx, target_kind="knowledge",
                       corpus_snapshot_id=corpus,
                       vector_provider=FakeProvider(dimension=16))
        ids.add(b3["index_snapshot_id"])
        # 5) provider-a / model-1 / dim8 / 不同 canonical parameters
        b4 = cat.build(ctx, target_kind="knowledge",
                       corpus_snapshot_id=corpus,
                       vector_provider=FakeProvider(),
                       parameters={"fusion_k": 99})
        ids.add(b4["index_snapshot_id"])
        assert len(ids) == 5, f"索引身份可混淆: {ids}"

    def test_same_provider_build_is_idempotent(self, store, ctx, corpus,
                                               tmp_path):
        cat = IndexCatalog(store, index_root=tmp_path / "idx")
        b1 = cat.build(ctx, target_kind="knowledge",
                       corpus_snapshot_id=corpus,
                       vector_provider=FakeProvider())
        b2 = cat.build(ctx, target_kind="knowledge",
                       corpus_snapshot_id=corpus,
                       vector_provider=FakeProvider())
        assert b1["index_snapshot_id"] == b2["index_snapshot_id"]
        assert cat.count_builds("knowledge") == 1

    def test_lexical_build_not_reused_for_dense(self, store, ctx, corpus,
                                                tmp_path):
        cat = IndexCatalog(store, index_root=tmp_path / "idx")
        lex = cat.build(ctx, target_kind="knowledge",
                        corpus_snapshot_id=corpus)
        dense = cat.build(ctx, target_kind="knowledge",
                          corpus_snapshot_id=corpus,
                          vector_provider=FakeProvider())
        assert dense["index_snapshot_id"] != lex["index_snapshot_id"]
        # lexical artifact 无向量；dense artifact 有向量且记录 provider 身份
        la = cat.load_artifact(lex)
        da = cat.load_artifact(dense)
        assert not la.get("vectors")
        assert da.get("vectors")
        ident = da.get("vector_identity") or {}
        assert ident.get("provider_id") == "fake"
        assert ident.get("model_name") == "model-1"
        assert ident.get("dimension") == 8

    def test_build_records_provider_identity_and_vector_count(
            self, store, ctx, corpus, tmp_path):
        cat = IndexCatalog(store, index_root=tmp_path / "idx")
        b = cat.build(ctx, target_kind="knowledge",
                      corpus_snapshot_id=corpus,
                      vector_provider=FakeProvider())
        assert "fake/model-1@rev-1" in (b["embedding_model"] or "")
        assert b["quality_report"].get("vector_count", 0) >= 1


class TestProviderMismatchFailClosed:
    def _build_activate(self, store, ctx, corpus, tmp_path, provider):
        cat = IndexCatalog(store, index_root=tmp_path / "idx")
        b = cat.build(ctx, target_kind="knowledge",
                      corpus_snapshot_id=corpus,
                      vector_provider=provider)
        cat.activate(ctx, target_kind="knowledge",
                     index_snapshot_id=b["index_snapshot_id"])
        return cat

    def test_query_with_different_model_degrades_no_cosine(
            self, store, ctx, corpus, tmp_path):
        cat = self._build_activate(store, ctx, corpus, tmp_path,
                                   FakeProvider(model_name="model-1"))
        gw = CognitiveQueryGateway(
            store, catalog=cat,
            vector_provider=FakeProvider(model_name="model-2"))
        r = gw.search(_req(), ctx)
        assert r.candidates, "lexical leg 仍应返回"
        assert r.degraded is True
        assert "provider_mismatch" in str(r.retrieval_trace)
        assert r.candidates[0].score_breakdown.get("dense") is None

    def test_query_with_different_dimension_degrades(
            self, store, ctx, corpus, tmp_path):
        cat = self._build_activate(store, ctx, corpus, tmp_path,
                                   FakeProvider(dimension=8))
        gw = CognitiveQueryGateway(store, catalog=cat,
                                   vector_provider=FakeProvider(
                                       dimension=16))
        r = gw.search(_req(), ctx)
        assert r.degraded is True
        assert r.candidates[0].score_breakdown.get("dense") is None

    def test_matching_provider_hybrid_not_degraded(self, store, ctx,
                                                   corpus, tmp_path):
        cat = self._build_activate(store, ctx, corpus, tmp_path,
                                   FakeProvider())
        gw = CognitiveQueryGateway(store, catalog=cat,
                                   vector_provider=FakeProvider())
        r = gw.search(_req(), ctx)
        assert r.degraded is False
        assert r.candidates[0].score_breakdown.get("dense") is not None

    def test_unavailable_provider_degrades(self, store, ctx, corpus,
                                           tmp_path):
        cat = self._build_activate(store, ctx, corpus, tmp_path,
                                   FakeProvider())
        gw = CognitiveQueryGateway(store, catalog=cat,
                                   vector_provider=(
                                       UnavailableVectorProvider()))
        r = gw.search(_req(), ctx)
        assert r.degraded is True


class TestOpenAICompatibleAdapter:
    def test_unconfigured_is_unavailable(self):
        from src.platform.cognition.index.providers import (
            OpenAICompatibleVectorProvider)
        p = OpenAICompatibleVectorProvider(endpoint="", model_name="",
                                           api_key="", dimension=0)
        assert p.available() is False

    def test_identity_does_not_leak_key(self):
        from src.platform.cognition.index.providers import (
            OpenAICompatibleVectorProvider)
        secret = "sk-super-secret-123"
        p = OpenAICompatibleVectorProvider(
            endpoint="http://127.0.0.1:1/v1", model_name="text-embed-3",
            api_key=secret, dimension=8, model_revision="r1")
        ident = p.identity()
        blob = repr(p) + str(ident)
        assert secret not in blob
        assert ident["provider_id"] == "openai-compatible"
        assert ident["model_name"] == "text-embed-3"
        assert ident["model_revision"] == "r1"
        assert ident["dimension"] == 8

    def test_provider_from_env_default_unavailable(self, monkeypatch):
        from src.platform.cognition.index.providers import (
            provider_from_env)
        for k in ("TAAS_EMBEDDING_PROVIDER", "TAAS_EMBEDDING_BASE_URL",
                  "TAAS_EMBEDDING_MODEL", "TAAS_EMBEDDING_API_KEY",
                  "TAAS_EMBEDDING_DIMENSION",
                  "TAAS_EMBEDDING_MODEL_REVISION",
                  "TAAS_EMBEDDING_NORMALIZATION"):
            monkeypatch.delenv(k, raising=False)
        p = provider_from_env()
        assert p.available() is False

    def test_provider_from_env_openai_config(self, monkeypatch):
        from src.platform.cognition.index.providers import (
            OpenAICompatibleVectorProvider, provider_from_env)
        monkeypatch.setenv("TAAS_EMBEDDING_PROVIDER", "openai-compatible")
        monkeypatch.setenv("TAAS_EMBEDDING_BASE_URL",
                           "http://127.0.0.1:1/v1")
        monkeypatch.setenv("TAAS_EMBEDDING_MODEL", "text-embed-3")
        monkeypatch.setenv("TAAS_EMBEDDING_API_KEY", "sk-x")
        monkeypatch.setenv("TAAS_EMBEDDING_DIMENSION", "8")
        p = provider_from_env()
        assert isinstance(p, OpenAICompatibleVectorProvider)
        assert p.identity()["model_name"] == "text-embed-3"
