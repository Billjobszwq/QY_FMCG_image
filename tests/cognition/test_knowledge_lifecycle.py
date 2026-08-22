"""Task 7（G5）测试：Knowledge 独立生命周期（治理强化后）。

要求（05 计划 Task 7 + 评审修复）：
- publish 必须 owner / effective_from / **真实存在** 的 source spans /
  governance approval 账本中的人类批准（maker≠checker）；
- 过期（effective_to 已过）/撤销（revoked）默认不返回；
- 知识冲突生成 conflict report，不自动“最新者胜”；
- knowledge_document_v1 只读兼容投影。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.platform.cognition.context import CognitiveContext
from src.platform.cognition.errors import (
    CognitionValidationError,
)
from src.platform.cognition.knowledge.service import (
    APPROVAL_KIND_PUBLISH,
    APPROVAL_KIND_REVOKE,
    KnowledgeService,
)
from src.platform.data.store import PlatformStore
from src.platform.governance.policy_service import PolicyService

from .helpers import approve, mk_spans

AS_OF = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


@pytest.fixture()
def svc(store):
    return KnowledgeService(store)


@pytest.fixture()
def ctx():
    return CognitiveContext(
        principal_id="alice", tenant_id="local", customer_id="",
        project_id="", test_run_id="", data_scope="operational",
        action="cognition.knowledge.search", permission_tags=("public",),
        purpose="kb-test", correlation_id="corr-1", parent_run_id=None,
        as_of=AS_OF)


def _draft(svc, ctx, store, kid: str = "kb-travel", create_spans: bool = True,
           **kw):
    base = dict(knowledge_id=kid, knowledge_type="policy",
                title="差旅报销制度", body="高铁二等座全额报销。",
                summary="差旅报销规则", owner="finance",
                effective_from="2026-01-01T00:00:00+00:00",
                effective_to=None, permission_tags=("public",),
                source_span_ids=["sp-1", "sp-2"])
    base.update(kw)
    if create_spans:
        mk_spans(store, base["source_span_ids"])
    return svc.draft(ctx, **base)


def _publish(svc, ctx, store, kid: str, version: int = 1,
             approver: str = "human-bill") -> dict:
    ap = approve(store, kind=APPROVAL_KIND_PUBLISH,
                 subject_ref=f"{kid}@v{version}",
                 requested_by="alice", decider=approver)
    return svc.publish(ctx, kid, version, approver=approver,
                       approval_id=ap)


class TestPublishGate:
    def test_publish_requires_owner(self, svc, ctx, store):
        _draft(svc, ctx, store, owner="")
        ap = approve(store, kind=APPROVAL_KIND_PUBLISH,
                     subject_ref="kb-travel@v1")
        with pytest.raises(CognitionValidationError):
            svc.publish(ctx, "kb-travel", 1, approver="human-bill",
                        approval_id=ap)

    def test_publish_requires_effective_from(self, svc, ctx, store):
        _draft(svc, ctx, store, effective_from="")
        ap = approve(store, kind=APPROVAL_KIND_PUBLISH,
                     subject_ref="kb-travel@v1")
        with pytest.raises(CognitionValidationError):
            svc.publish(ctx, "kb-travel", 1, approver="human-bill",
                        approval_id=ap)

    def test_publish_requires_source_spans(self, svc, ctx, store):
        _draft(svc, ctx, store, source_span_ids=[])
        ap = approve(store, kind=APPROVAL_KIND_PUBLISH,
                     subject_ref="kb-travel@v1")
        with pytest.raises(CognitionValidationError):
            svc.publish(ctx, "kb-travel", 1, approver="human-bill",
                        approval_id=ap)

    def test_publish_rejects_fake_span_ids(self, svc, ctx, store):
        """span 必须真实存在于 evidence_span 表（评审 #16）。"""
        _draft(svc, ctx, store, source_span_ids=["span-does-not-exist"],
               create_spans=False)
        ap = approve(store, kind=APPROVAL_KIND_PUBLISH,
                     subject_ref="kb-travel@v1")
        with pytest.raises(CognitionValidationError):
            svc.publish(ctx, "kb-travel", 1, approver="human-bill",
                        approval_id=ap)

    def test_publish_requires_human_approver(self, svc, ctx, store):
        _draft(svc, ctx, store)
        ap = approve(store, kind=APPROVAL_KIND_PUBLISH,
                     subject_ref="kb-travel@v1")
        with pytest.raises(CognitionValidationError):
            svc.publish(ctx, "kb-travel", 1, approver="",
                        approval_id=ap)

    def test_publish_requires_approval_ledger(self, svc, ctx, store):
        _draft(svc, ctx, store)
        with pytest.raises(Exception):
            svc.publish(ctx, "kb-travel", 1, approver="human-bill",
                        approval_id="")
        with pytest.raises(Exception):
            svc.publish(ctx, "kb-travel", 1, approver="human-bill",
                        approval_id="apr-nonexistent")

    def test_maker_cannot_self_approve(self, svc, ctx, store):
        """起草人 alice 不得自批自发布（maker=checker，评审 #4/#12）。"""
        _draft(svc, ctx, store)  # created_by=alice
        p = PolicyService(store)
        ap = p.request_generic_approval(
            kind=APPROVAL_KIND_PUBLISH, subject_ref="kb-travel@v1",
            requested_by="alice")
        with pytest.raises(Exception):
            p.decide_approval(ap["approval_id"], actor="alice",
                              decision="approved")

    def test_approver_must_be_decider(self, svc, ctx, store):
        _draft(svc, ctx, store)
        ap = approve(store, kind=APPROVAL_KIND_PUBLISH,
                     subject_ref="kb-travel@v1", decider="human-bill")
        with pytest.raises(Exception):
            svc.publish(ctx, "kb-travel", 1, approver="someone-else",
                        approval_id=ap)

    def test_publish_success_marks_published(self, svc, ctx, store):
        _draft(svc, ctx, store)
        item = _publish(svc, ctx, store, "kb-travel")
        assert item["status"] == "published"
        assert item["approved_by"] == "human-bill"


class TestEffectiveFiltering:
    def test_draft_not_returned(self, svc, ctx, store):
        _draft(svc, ctx, store)
        assert svc.effective(ctx) == []

    def test_published_returned(self, svc, ctx, store):
        _draft(svc, ctx, store)
        _publish(svc, ctx, store, "kb-travel")
        got = svc.effective(ctx)
        assert len(got) == 1 and got[0]["knowledge_id"] == "kb-travel"

    def test_expired_not_returned_by_default(self, svc, ctx, store):
        _draft(svc, ctx, store,
               effective_to="2026-06-01T00:00:00+00:00")
        _publish(svc, ctx, store, "kb-travel")
        assert svc.effective(ctx) == []  # as_of=2026-08-20 已过期
        hist = svc.effective(ctx, include_history=True)
        assert len(hist) == 1

    def test_not_yet_effective_not_returned(self, svc, ctx, store):
        _draft(svc, ctx, store,
               effective_from="2027-01-01T00:00:00+00:00")
        _publish(svc, ctx, store, "kb-travel")
        assert svc.effective(ctx) == []

    def test_revoked_not_returned(self, svc, ctx, store):
        _draft(svc, ctx, store)
        _publish(svc, ctx, store, "kb-travel")
        ap = approve(store, kind=APPROVAL_KIND_REVOKE,
                     subject_ref="kb-travel@v1", decider="human-bill")
        svc.revoke(ctx, "kb-travel", 1, actor="human-bill",
                   approval_id=ap)
        assert svc.effective(ctx) == []

    def test_revoke_requires_approval(self, svc, ctx, store):
        _draft(svc, ctx, store)
        _publish(svc, ctx, store, "kb-travel")
        with pytest.raises(Exception):
            svc.revoke(ctx, "kb-travel", 1, actor="human-bill",
                       approval_id="")


class TestSupersessionAndConflict:
    def test_new_published_version_supersedes_old(self, svc, ctx, store):
        _draft(svc, ctx, store)
        _publish(svc, ctx, store, "kb-travel", 1)
        _draft(svc, ctx, store, body="修订：机票上限 2500 元。")
        _publish(svc, ctx, store, "kb-travel", 2)
        eff = svc.effective(ctx)
        assert len(eff) == 1 and eff[0]["version"] == 2

    def test_cross_item_conflict_report_not_autowin(self, svc, ctx,
                                                     store):
        _draft(svc, ctx, store, kid="kb-a", title="报销制度",
               body="上限 2000", source_span_ids=["spa-1"])
        _publish(svc, ctx, store, "kb-a", 1)
        _draft(svc, ctx, store, kid="kb-b", title="报销制度",
               body="上限 3000", source_span_ids=["spb-1"])
        _publish(svc, ctx, store, "kb-b", 1)
        conflicts = svc.detect_conflicts(ctx, knowledge_type="policy")
        assert len(conflicts) >= 1
        ids = {c["knowledge_id"] for c in conflicts}
        assert {"kb-a", "kb-b"} <= ids
        assert len(svc.effective(ctx, knowledge_type="policy")) == 2


class TestLegacyProjection:
    def test_knowledge_document_v1_read_only_projection(self, svc, ctx,
                                                      store):
        store._conn.execute(
            "INSERT INTO knowledge_document_v1 (doc_id, kb_name,"
            " customer_id, title, source, version, expires_at, status,"
            " created_by, created_at) VALUES ('kd-1','巡检手册','','门店"
            " 陈列规范','docs/kb/x.md','v1',NULL,'draft','tester',"
            " '2026-08-01T00:00:00Z')")
        store._conn.commit()
        rows = svc.legacy_projection(ctx)
        assert len(rows) == 1
        assert rows[0]["doc_id"] == "kd-1"
        assert rows[0]["_origin"] == "knowledge_document_v1"
