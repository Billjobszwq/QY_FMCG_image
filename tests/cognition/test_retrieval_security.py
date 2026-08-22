"""Task 8（G6）红测试：检索安全（ACL-first，fail-closed）。

要求（02 §1/§8.2、05 Task 8）：
- 跨 tenant/customer/project、过期、revoked、draft、test scope 均零命中；
- 不泄露 count/facet（候选为空即无信息）；
- 缺上下文 fail-closed；
- 权限标签不相交零命中。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.platform.cognition.context import CognitiveContext
from src.platform.cognition.contracts import CognitiveQueryRequest
from src.platform.cognition.errors import CognitionValidationError
from src.platform.cognition.index.catalog import IndexCatalog
from src.platform.cognition.index.gateway import CognitiveQueryGateway
from src.platform.cognition.knowledge.service import (
    APPROVAL_KIND_PUBLISH as APPROVAL_KIND_KB,
    KnowledgeService,
)

from .helpers import approve
from src.platform.cognition.sources.service import SourceService
from src.platform.data.store import PlatformStore

AS_OF = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)

BODY = "# 报销制度\n\n机票经济舱上限 2000 元。\n"


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _ctx(**kw) -> CognitiveContext:
    base = dict(principal_id="alice", tenant_id="local", customer_id="",
                project_id="", test_run_id="", data_scope="operational",
                action="cognition.knowledge.search",
                permission_tags=("public",), purpose="acl-test",
                correlation_id="corr-1", parent_run_id=None, as_of=AS_OF)
    base.update(kw)
    return CognitiveContext(**base)


def _publish_doc(store, ctx, tmp_path, kid: str, **draft_kw) -> None:
    sources = SourceService(store, cas_root=tmp_path / "cas")
    kb = KnowledgeService(store)
    res = sources.ingest(ctx, source_type="file",
                         original_uri=f"{kid}.md",
                         media_type="text/markdown",
                         content=BODY.encode("utf-8"),
                         permission_tags=draft_kw.get(
                             "permission_tags", ("public",)),
                         trust_tier="authoritative")
    base = dict(knowledge_id=kid, knowledge_type="policy", title="报销制度",
                body=BODY, summary="报销", owner="finance",
                effective_from="2026-01-01T00:00:00+00:00",
                effective_to=None, permission_tags=("public",),
                source_span_ids=[c["chunk_id"] for c in res["chunks"]])
    base.update(draft_kw)
    kb.draft(ctx, **base)
    ap = approve(store, kind=APPROVAL_KIND_KB,
                 subject_ref=f"{kid}@v1", requested_by="alice",
                 decider="human-bill")
    kb.publish(ctx, kid, 1, approver="human-bill", approval_id=ap)


@pytest.fixture()
def indexed(store, tmp_path):
    """索引一个平台级 public 文档，返回 gateway。"""
    ctx = _ctx()
    _publish_doc(store, ctx, tmp_path, "kb-pub")
    snap = SourceService(store, cas_root=tmp_path / "cas")\
        .build_corpus_snapshot(ctx)
    catalog = IndexCatalog(store, index_root=tmp_path / "index")
    b = catalog.build(ctx, target_kind="knowledge",
                      corpus_snapshot_id=snap["corpus_snapshot_id"])
    catalog.activate(ctx, target_kind="knowledge",
                     index_snapshot_id=b["index_snapshot_id"])
    return CognitiveQueryGateway(store, catalog=catalog)


def _req(q="机票经济舱"):
    return CognitiveQueryRequest(query=q, target_kinds=("knowledge",),
                                 mode="lookup", top_k=8)


class TestContextGate:
    def test_missing_context_fails_closed(self, indexed):
        with pytest.raises(CognitionValidationError):
            indexed.search(_req(), None)


class TestTenantCustomerIsolation:
    def test_cross_customer_zero_hits_no_leak(self, store, tmp_path):
        ctx_a = _ctx(customer_id="cust-a")
        _publish_doc(store, ctx_a, tmp_path, "kb-a")
        snap = SourceService(store, cas_root=tmp_path / "cas")\
            .build_corpus_snapshot(ctx_a)
        catalog = IndexCatalog(store, index_root=tmp_path / "index")
        b = catalog.build(ctx_a, target_kind="knowledge",
                          corpus_snapshot_id=snap["corpus_snapshot_id"])
        catalog.activate(ctx_a, target_kind="knowledge",
                         index_snapshot_id=b["index_snapshot_id"])
        gw = CognitiveQueryGateway(store, catalog=catalog)
        r = gw.search(_req(), _ctx(customer_id="cust-b"))
        assert not r.candidates
        # 不泄露计数/facet：结果里没有任何可计数的残留字段
        d = r.to_dict()
        assert "total_count" not in d and "facets" not in d

    def test_same_customer_and_platform_wide_visible(self, store,
                                                     tmp_path):
        ctx_a = _ctx(customer_id="cust-a")
        _publish_doc(store, ctx_a, tmp_path, "kb-a")
        # 平台级（customer=''）文档：同租户所有客户可见
        _publish_doc(store, _ctx(), tmp_path, "kb-plat")
        snap = SourceService(store, cas_root=tmp_path / "cas")\
            .build_corpus_snapshot(ctx_a)
        catalog = IndexCatalog(store, index_root=tmp_path / "index")
        b = catalog.build(ctx_a, target_kind="knowledge",
                          corpus_snapshot_id=snap["corpus_snapshot_id"])
        catalog.activate(ctx_a, target_kind="knowledge",
                         index_snapshot_id=b["index_snapshot_id"])
        gw = CognitiveQueryGateway(store, catalog=catalog)
        r = gw.search(_req(), ctx_a)
        ids = {c.target_id for c in r.candidates}
        assert {"kb-a", "kb-plat"} <= ids
        # 平台级上下文（customer=''）只看到平台级文档
        r2 = gw.search(_req(), _ctx(customer_id=""))
        ids2 = {c.target_id for c in r2.candidates}
        assert ids2 == {"kb-plat"}

    def test_cross_tenant_zero_hits(self, store, tmp_path):
        _publish_doc(store, _ctx(), tmp_path, "kb-pub2")
        snap = SourceService(store, cas_root=tmp_path / "cas")\
            .build_corpus_snapshot(_ctx())
        catalog = IndexCatalog(store, index_root=tmp_path / "index")
        b = catalog.build(_ctx(), target_kind="knowledge",
                          corpus_snapshot_id=snap["corpus_snapshot_id"])
        catalog.activate(_ctx(), target_kind="knowledge",
                         index_snapshot_id=b["index_snapshot_id"])
        gw = CognitiveQueryGateway(store, catalog=catalog)
        r = gw.search(_req(), _ctx(tenant_id="other-tenant"))
        assert not r.candidates


class TestLifecycleFiltering:
    def test_expired_zero_hits(self, store, tmp_path):
        ctx = _ctx()
        _publish_doc(store, ctx, tmp_path, "kb-exp",
                     effective_to="2026-06-01T00:00:00+00:00")
        snap = SourceService(store, cas_root=tmp_path / "cas")\
            .build_corpus_snapshot(ctx)
        catalog = IndexCatalog(store, index_root=tmp_path / "index")
        b = catalog.build(ctx, target_kind="knowledge",
                          corpus_snapshot_id=snap["corpus_snapshot_id"])
        catalog.activate(ctx, target_kind="knowledge",
                         index_snapshot_id=b["index_snapshot_id"])
        gw = CognitiveQueryGateway(store, catalog=catalog)
        assert not gw.search(_req(), ctx).candidates

    def test_revoked_zero_hits(self, store, tmp_path):
        ctx = _ctx()
        _publish_doc(store, ctx, tmp_path, "kb-rev")
        ap = approve(store, kind="cognition.knowledge.revoke",
                     subject_ref="kb-rev@v1", requested_by="silent",
                     decider="human-bill")
        KnowledgeService(store).revoke(ctx, "kb-rev", 1,
                                       actor="human-bill",
                                       approval_id=ap)
        snap = SourceService(store, cas_root=tmp_path / "cas")\
            .build_corpus_snapshot(ctx)
        catalog = IndexCatalog(store, index_root=tmp_path / "index")
        b = catalog.build(ctx, target_kind="knowledge",
                          corpus_snapshot_id=snap["corpus_snapshot_id"])
        catalog.activate(ctx, target_kind="knowledge",
                         index_snapshot_id=b["index_snapshot_id"])
        gw = CognitiveQueryGateway(store, catalog=catalog)
        assert not gw.search(_req(), ctx).candidates

    def test_draft_never_searchable(self, store, tmp_path):
        ctx = _ctx()
        sources = SourceService(store, cas_root=tmp_path / "cas")
        kb = KnowledgeService(store)
        res = sources.ingest(ctx, source_type="file",
                             original_uri="d.md",
                             media_type="text/markdown",
                             content=BODY.encode("utf-8"),
                             permission_tags=("public",),
                             trust_tier="authoritative")
        kb.draft(ctx, knowledge_id="kb-draft", knowledge_type="policy",
                 title="报销制度", body=BODY, summary="报销",
                 owner="finance",
                 effective_from="2026-01-01T00:00:00+00:00",
                 effective_to=None, permission_tags=("public",),
                 source_span_ids=[c["chunk_id"] for c in res["chunks"]])
        snap = sources.build_corpus_snapshot(ctx)
        catalog = IndexCatalog(store, index_root=tmp_path / "index")
        b = catalog.build(ctx, target_kind="knowledge",
                          corpus_snapshot_id=snap["corpus_snapshot_id"])
        catalog.activate(ctx, target_kind="knowledge",
                         index_snapshot_id=b["index_snapshot_id"])
        gw = CognitiveQueryGateway(store, catalog=catalog)
        assert not gw.search(_req(), ctx).candidates


class TestScopeAndPermission:
    def test_uat_fixture_invisible_to_operational(self, store, tmp_path):
        # fixture 文档（uat_fixture + test_run）
        from src.platform.scope import ExecutionContext
        fx_ctx = _ctx(data_scope="uat_fixture", test_run_id="tr-x",
                      customer_id="cust-a")
        # 直接以 fixture scope 造知识（跳过 ScopeResolver 注册校验：
        # CognitiveContext 已强制 fixture 携带 test_run_id）
        _publish_doc(store, fx_ctx, tmp_path, "kb-fx")
        snap = SourceService(store, cas_root=tmp_path / "cas")\
            .build_corpus_snapshot(fx_ctx)
        catalog = IndexCatalog(store, index_root=tmp_path / "index")
        b = catalog.build(fx_ctx, target_kind="knowledge",
                          corpus_snapshot_id=snap["corpus_snapshot_id"])
        catalog.activate(fx_ctx, target_kind="knowledge",
                         index_snapshot_id=b["index_snapshot_id"])
        gw = CognitiveQueryGateway(store, catalog=catalog)
        # operational 查询不可见 fixture 内容
        r = gw.search(_req(), _ctx(customer_id="cust-a"))
        assert not r.candidates
        # fixture 查询可见自己 scope 的内容
        r2 = gw.search(_req(), fx_ctx)
        assert {c.target_id for c in r2.candidates} == {"kb-fx"}

    def test_permission_tags_disjoint_zero_hits(self, store, tmp_path):
        ctx = _ctx(permission_tags=("hr-confidential",))
        _publish_doc(store, ctx, tmp_path, "kb-secret",
                     permission_tags=("hr-confidential",))
        snap = SourceService(store, cas_root=tmp_path / "cas")\
            .build_corpus_snapshot(ctx)
        catalog = IndexCatalog(store, index_root=tmp_path / "index")
        b = catalog.build(ctx, target_kind="knowledge",
                          corpus_snapshot_id=snap["corpus_snapshot_id"])
        catalog.activate(ctx, target_kind="knowledge",
                         index_snapshot_id=b["index_snapshot_id"])
        gw = CognitiveQueryGateway(store, catalog=catalog)
        # 权限标签不相交 → 零命中
        r = gw.search(_req(), _ctx(permission_tags=("public",)))
        assert not r.candidates
        # 相交 → 可见
        r2 = gw.search(_req(), ctx)
        assert {c.target_id for c in r2.candidates} == {"kb-secret"}


class TestReviewRegressions:
    """Phase-3 评审高危发现回归（评审 #G6-1 跨 project、#G6-2 陈旧索引）。"""

    def _publish_and_index(self, store, tmp_path, ctx, kid):
        _publish_doc(store, ctx, tmp_path, kid)
        snap = SourceService(store, cas_root=tmp_path / "cas")\
            .build_corpus_snapshot(ctx)
        catalog = IndexCatalog(store, index_root=tmp_path / "index")
        b = catalog.build(ctx, target_kind="knowledge",
                          corpus_snapshot_id=snap["corpus_snapshot_id"])
        catalog.activate(ctx, target_kind="knowledge",
                         index_snapshot_id=b["index_snapshot_id"])
        return CognitiveQueryGateway(store, catalog=catalog)

    def test_cross_project_zero_hits(self, store, tmp_path):
        """proj-a 的项目级知识，proj-b 上下文零命中（评审 #G6-1）。"""
        ctx_a = _ctx(project_id="proj-a")
        gw = self._publish_and_index(store, tmp_path, ctx_a, "kb-proj-a")
        # 同项目可见
        r_same = gw.search(_req(), _ctx(project_id="proj-a"))
        assert {c.target_id for c in r_same.candidates} == {"kb-proj-a"}
        # 跨项目零命中
        r_cross = gw.search(_req(), _ctx(project_id="proj-b"))
        assert not r_cross.candidates
        # 平台级（project=''）上下文也不得见项目级内容
        r_plat = gw.search(_req(), _ctx())
        assert not r_plat.candidates

    def test_revoked_after_build_not_searchable(self, store, tmp_path):
        """build+activate 后 revoke：不重建索引也不得再命中
        （陈旧索引 status 以 DB 当前状态复核，评审 #G6-2）。"""
        ctx = _ctx()
        _publish_doc(store, ctx, tmp_path, "kb-revoke-late")
        snap = SourceService(store, cas_root=tmp_path / "cas")\
            .build_corpus_snapshot(ctx)
        catalog = IndexCatalog(store, index_root=tmp_path / "index")
        b = catalog.build(ctx, target_kind="knowledge",
                          corpus_snapshot_id=snap["corpus_snapshot_id"])
        catalog.activate(ctx, target_kind="knowledge",
                         index_snapshot_id=b["index_snapshot_id"])
        gw = CognitiveQueryGateway(store, catalog=catalog)
        assert gw.search(_req(), ctx).candidates  # 撤销前可见
        # 走撤销（human approval）
        ap = approve(store, kind="cognition.knowledge.revoke",
                     subject_ref="kb-revoke-late@v1",
                     requested_by="silent", decider="human-bill")
        KnowledgeService(store).revoke(ctx, "kb-revoke-late", 1,
                                       actor="human-bill", approval_id=ap)
        # 不重建索引：陈旧 artifact 仍以 DB 当前状态复核 → 零命中
        assert not gw.search(_req(), ctx).candidates

    def test_superseded_old_version_not_returned(self, store, tmp_path):
        """发布 v2 使 v1 superseded：检索只返回 v2（评审 #G6-2）。"""
        ctx = _ctx()
        sources = SourceService(store, cas_root=tmp_path / "cas")
        kb = KnowledgeService(store)
        # v1：摄取并发布
        res1 = sources.ingest(ctx, source_type="file",
                              original_uri="ver.md",
                              media_type="text/markdown",
                              content=BODY.encode("utf-8"),
                              permission_tags=("public",),
                              trust_tier="authoritative")
        kb.draft(ctx, knowledge_id="kb-ver", knowledge_type="policy",
                 title="报销制度", body=BODY, summary="报销",
                 owner="finance",
                 effective_from="2026-01-01T00:00:00+00:00",
                 effective_to=None, permission_tags=("public",),
                 source_span_ids=[c["chunk_id"] for c in res1["chunks"]])
        ap1 = approve(store, kind=APPROVAL_KIND_KB,
                      subject_ref="kb-ver@v1", requested_by="alice",
                      decider="human-bill")
        kb.publish(ctx, "kb-ver", 1, approver="human-bill",
                   approval_id=ap1)
        snap = sources.build_corpus_snapshot(ctx)
        catalog = IndexCatalog(store, index_root=tmp_path / "index")
        b = catalog.build(ctx, target_kind="knowledge",
                          corpus_snapshot_id=snap["corpus_snapshot_id"])
        catalog.activate(ctx, target_kind="knowledge",
                         index_snapshot_id=b["index_snapshot_id"])
        gw = CognitiveQueryGateway(store, catalog=catalog)
        assert {c.version for c in gw.search(_req(), ctx).candidates
                } == {"1"}
        # v2：摄取新内容并发布 → v1 superseded
        body2 = BODY.replace("2000 元", "3000 元")
        res2 = sources.ingest(ctx, source_type="file",
                              original_uri="ver.md",
                              media_type="text/markdown",
                              content=body2.encode("utf-8"),
                              permission_tags=("public",),
                              trust_tier="authoritative")
        kb.draft(ctx, knowledge_id="kb-ver", knowledge_type="policy",
                 title="报销制度", body=body2, summary="报销",
                 owner="finance",
                 effective_from="2026-01-01T00:00:00+00:00",
                 effective_to=None, permission_tags=("public",),
                 source_span_ids=[c["chunk_id"] for c in res2["chunks"]])
        ap2 = approve(store, kind=APPROVAL_KIND_KB,
                      subject_ref="kb-ver@v2", requested_by="alice",
                      decider="human-bill")
        kb.publish(ctx, "kb-ver", 2, approver="human-bill",
                   approval_id=ap2)
        # 旧索引含 v1 的 chunk；DB 复核后 v1（superseded）不得返回
        versions = {c.version for c in gw.search(_req(), ctx).candidates}
        assert "1" not in versions

    def test_trace_does_not_leak_global_counts(self, store, tmp_path):
        """retrieval_trace 不得泄露全局语料计数（评审 #G6-6）。"""
        ctx_a = _ctx(tenant_id="tenant-a")
        self._publish_and_index(store, tmp_path, ctx_a, "kb-leak")
        r = CognitiveQueryGateway(
            store, catalog=IndexCatalog(store,
                                        index_root=tmp_path / "index")
            ).search(_req(), _ctx(tenant_id="tenant-evil"))
        d = r.to_dict()
        trace = d.get("retrieval_trace", {})
        assert "knowledge_units_total" not in trace
        assert "knowledge_units_allowed" not in trace
        assert not r.candidates
