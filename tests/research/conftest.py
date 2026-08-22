"""research 测试共享 fixture：发布三份知识 + 激活索引 + gateway/service。"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.platform.cognition.context import CognitiveContext
from src.platform.cognition.index.catalog import IndexCatalog
from src.platform.cognition.index.gateway import CognitiveQueryGateway
from src.platform.cognition.knowledge.service import (
    APPROVAL_KIND_PUBLISH as KB_PUB,
    KnowledgeService,
)
from src.platform.cognition.research.service import ResearchService
from src.platform.cognition.sources.service import SourceService
from src.platform.data.store import PlatformStore

from tests.cognition.helpers import approve

AS_OF = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)

# 语料：A/B 都谈“报销”（互为冲突来源），C 谈“年假”（独占主题）。
DOCS = {
    "kb-travel-a": ("policies/a.md",
                    "# 报销制度A\n\n机票报销上限 2000 元。\n"),
    "kb-travel-b": ("policies/b.md",
                    "# 报销制度B\n\n机票报销上限 3000 元。\n"),
    "kb-leave": ("policies/c.md", "# 年假制度\n\n入职满一年年假 5 天。\n"),
}


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


@pytest.fixture()
def rctx():
    return CognitiveContext(
        principal_id="alice", tenant_id="local", customer_id="",
        project_id="", test_run_id="", data_scope="operational",
        action="cognition.research.start", permission_tags=("public",),
        purpose="research-test", correlation_id="corr-r",
        parent_run_id=None, as_of=AS_OF)


@pytest.fixture()
def rsvc(store, rctx, tmp_path):
    sources = SourceService(store, cas_root=tmp_path / "cas")
    kb = KnowledgeService(store)
    for kid, (uri, text) in DOCS.items():
        res = sources.ingest(rctx, source_type="file", original_uri=uri,
                             media_type="text/markdown",
                             content=text.encode("utf-8"),
                             permission_tags=("public",),
                             trust_tier="authoritative")
        kb.draft(rctx, knowledge_id=kid, knowledge_type="policy",
                 title=kid, body=text, summary=kid, owner="hr",
                 effective_from="2026-01-01T00:00:00+00:00",
                 effective_to=None, permission_tags=("public",),
                 source_span_ids=[c["chunk_id"] for c in res["chunks"]])
        ap = approve(store, kind=KB_PUB, subject_ref=f"{kid}@v1",
                     requested_by="alice", decider="human-bill")
        kb.publish(rctx, kid, 1, approver="human-bill", approval_id=ap)
    snap = sources.build_corpus_snapshot(rctx)
    catalog = IndexCatalog(store, index_root=tmp_path / "index")
    build = catalog.build(rctx, target_kind="knowledge",
                          corpus_snapshot_id=snap["corpus_snapshot_id"])
    catalog.activate(rctx, target_kind="knowledge",
                     index_snapshot_id=build["index_snapshot_id"])
    gateway = CognitiveQueryGateway(store, catalog=catalog)
    return ResearchService(store, gateway=gateway)
