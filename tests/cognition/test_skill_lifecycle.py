"""Task 7（G5）测试：Skill 独立生命周期（治理强化后）。

要求（05 计划 Task 7 + 评审修复）：
- publish 必须 input/output schema、execution ref、risk、eval，且必须有
  governance approval 账本中的人类批准（maker≠checker）；
- 生命周期 draft→validated→published→degraded/revoked（CAS）；
- Skill RAG 命中不等于允许执行（can_execute 独立判定）；
- permission_tags fail-closed（评审 #6）；
- agent_asset_v1(kind='skill') 只读兼容投影。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.platform.cognition.context import CognitiveContext
from src.platform.cognition.errors import (
    CognitionConflictError,
    CognitionValidationError,
)
from src.platform.cognition.skills.service import (
    APPROVAL_KIND_PUBLISH,
    APPROVAL_KIND_REVOKE,
    SkillService,
)
from src.platform.data.store import PlatformStore

from .helpers import approve

AS_OF = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)

INPUT_SCHEMA = {"type": "object",
                "properties": {"address": {"type": "string"}},
                "required": ["address"]}
OUTPUT_SCHEMA = {"type": "object",
                 "properties": {"lat": {"type": "number"},
                                "lng": {"type": "number"}}}


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


@pytest.fixture()
def svc(store):
    return SkillService(store)


@pytest.fixture()
def ctx():
    return CognitiveContext(
        principal_id="alice", tenant_id="local", customer_id="",
        project_id="", test_run_id="", data_scope="operational",
        action="cognition.skills.search", permission_tags=("public",),
        purpose="skill-test", correlation_id="corr-1", parent_run_id=None,
        as_of=AS_OF)


def _draft(svc, ctx, skill_id: str = "skill-geocode", **kw):
    base = dict(skill_id=skill_id, name="地址地理编码",
                description="把 raw 地址解析为坐标",
                skill_type="curated", input_schema=INPUT_SCHEMA,
                output_schema=OUTPUT_SCHEMA,
                execution_ref="capability:geo.geocode",
                tool_scopes=["geo.read"], risk_level="low",
                applicable_scenarios=["地址补全"],
                forbidden_scenarios=["批量导出"],
                source_refs=["knowledge:kb-geo@v1"],
                evaluation_ref="eval:geocode-v1",
                permission_tags=("public",))
    base.update(kw)
    return svc.draft(ctx, **base)


def _publish(svc, ctx, store, skill_id: str, version: int = 1,
             approver: str = "human-bill") -> dict:
    ap = approve(store, kind=APPROVAL_KIND_PUBLISH,
                 subject_ref=f"{skill_id}@v{version}",
                 requested_by="alice", decider=approver)
    return svc.publish(ctx, skill_id, version, approver=approver,
                       approval_id=ap)


class TestSkillPublishGate:
    def test_publish_requires_schemas(self, svc, ctx, store):
        _draft(svc, ctx, input_schema={})
        svc.validate(ctx, "skill-geocode", 1, actor="curator")
        ap = approve(store, kind=APPROVAL_KIND_PUBLISH,
                     subject_ref="skill-geocode@v1")
        with pytest.raises(CognitionValidationError):
            svc.publish(ctx, "skill-geocode", 1, approver="human-bill",
                        approval_id=ap)

    def test_publish_requires_execution_ref(self, svc, ctx, store):
        _draft(svc, ctx, execution_ref="")
        svc.validate(ctx, "skill-geocode", 1, actor="curator")
        ap = approve(store, kind=APPROVAL_KIND_PUBLISH,
                     subject_ref="skill-geocode@v1")
        with pytest.raises(CognitionValidationError):
            svc.publish(ctx, "skill-geocode", 1, approver="human-bill",
                        approval_id=ap)

    def test_publish_requires_evaluation_ref(self, svc, ctx, store):
        _draft(svc, ctx, evaluation_ref="")
        svc.validate(ctx, "skill-geocode", 1, actor="curator")
        ap = approve(store, kind=APPROVAL_KIND_PUBLISH,
                     subject_ref="skill-geocode@v1")
        with pytest.raises(CognitionValidationError):
            svc.publish(ctx, "skill-geocode", 1, approver="human-bill",
                        approval_id=ap)

    def test_publish_requires_risk_and_approver(self, svc, ctx, store):
        _draft(svc, ctx, risk_level="")
        svc.validate(ctx, "skill-geocode", 1, actor="curator")
        ap = approve(store, kind=APPROVAL_KIND_PUBLISH,
                     subject_ref="skill-geocode@v1")
        with pytest.raises(CognitionValidationError):
            svc.publish(ctx, "skill-geocode", 1, approver="human-bill",
                        approval_id=ap)
        _draft(svc, ctx, skill_id="skill-2")
        svc.validate(ctx, "skill-2", 1, actor="curator")
        ap2 = approve(store, kind=APPROVAL_KIND_PUBLISH,
                      subject_ref="skill-2@v1")
        with pytest.raises(CognitionValidationError):
            svc.publish(ctx, "skill-2", 1, approver="",
                        approval_id=ap2)

    def test_publish_requires_approval_ledger(self, svc, ctx, store):
        _draft(svc, ctx)
        svc.validate(ctx, "skill-geocode", 1, actor="curator")
        with pytest.raises(Exception):
            svc.publish(ctx, "skill-geocode", 1, approver="human-bill",
                        approval_id="")

    def test_maker_cannot_self_approve(self, svc, ctx, store):
        from src.platform.governance.policy_service import PolicyService
        _draft(svc, ctx)  # created_by=alice
        svc.validate(ctx, "skill-geocode", 1, actor="curator")
        p = PolicyService(store)
        ap = p.request_generic_approval(
            kind=APPROVAL_KIND_PUBLISH,
            subject_ref="skill-geocode@v1", requested_by="alice")
        with pytest.raises(Exception):
            p.decide_approval(ap["approval_id"], actor="alice",
                              decision="approved")

    def test_must_pass_validated_before_publish(self, svc, ctx, store):
        _draft(svc, ctx)
        ap = approve(store, kind=APPROVAL_KIND_PUBLISH,
                     subject_ref="skill-geocode@v1")
        with pytest.raises(CognitionConflictError):
            svc.publish(ctx, "skill-geocode", 1, approver="human-bill",
                        approval_id=ap)


class TestPermissionTagsFailClosed:
    def test_draft_requires_permission_tags(self, svc, ctx):
        with pytest.raises(CognitionValidationError):
            _draft(svc, ctx, permission_tags=())
        with pytest.raises(CognitionValidationError):
            _draft(svc, ctx, permission_tags=[""])


class TestLifecycle:
    def test_full_lifecycle(self, svc, ctx, store):
        _draft(svc, ctx)
        v = svc.validate(ctx, "skill-geocode", 1, actor="curator")
        assert v["status"] == "validated"
        p = _publish(svc, ctx, store, "skill-geocode", 1)
        assert p["status"] == "published"
        d = svc.degrade(ctx, "skill-geocode", 1, actor="silent_agent",
                        reason="评测退化")
        assert d["status"] == "degraded"
        ap = approve(store, kind=APPROVAL_KIND_REVOKE,
                     subject_ref="skill-geocode@v1", decider="human-bill")
        r = svc.revoke(ctx, "skill-geocode", 1, actor="human-bill",
                       approval_id=ap)
        assert r["status"] == "revoked"

    def test_invalid_transition_rejected(self, svc, ctx, store):
        _draft(svc, ctx)
        svc.validate(ctx, "skill-geocode", 1, actor="curator")
        with pytest.raises(CognitionConflictError):
            svc.degrade(ctx, "skill-geocode", 1, actor="x", reason="y")

    def test_double_publish_cas_rejected(self, svc, ctx, store):
        _draft(svc, ctx)
        svc.validate(ctx, "skill-geocode", 1, actor="curator")
        _publish(svc, ctx, store, "skill-geocode", 1)
        ap = approve(store, kind=APPROVAL_KIND_PUBLISH,
                     subject_ref="skill-geocode@v1", decider="human-2")
        with pytest.raises(CognitionConflictError):
            svc.publish(ctx, "skill-geocode", 1, approver="human-2",
                        approval_id=ap)


class TestExecutionSeparateFromRetrieval:
    def test_rag_hit_does_not_imply_executable(self, svc, ctx, store):
        _draft(svc, ctx)
        hits = svc.search(ctx, query="地理编码")
        assert any(h["skill_id"] == "skill-geocode" for h in hits)
        assert svc.can_execute(ctx, "skill-geocode")["allowed"] is False
        svc.validate(ctx, "skill-geocode", 1, actor="curator")
        assert svc.can_execute(ctx, "skill-geocode")["allowed"] is False
        _publish(svc, ctx, store, "skill-geocode", 1)
        assert svc.can_execute(ctx, "skill-geocode")["allowed"] is True
        svc.degrade(ctx, "skill-geocode", 1, actor="silent_agent",
                    reason="退化")
        assert svc.can_execute(ctx, "skill-geocode")["allowed"] is False

    def test_high_risk_skill_requires_human_gate(self, svc, ctx, store):
        _draft(svc, ctx, skill_id="skill-fin", name="财务结算",
               risk_level="high",
               execution_ref="capability:finance.settle")
        svc.validate(ctx, "skill-fin", 1, actor="curator")
        _publish(svc, ctx, store, "skill-fin", 1)
        decision = svc.can_execute(ctx, "skill-fin")
        assert decision["allowed"] is False
        assert decision["requires_human_gate"] is True


class TestLegacyProjection:
    def test_agent_asset_skill_projection_read_only(self, svc, ctx, store):
        store._conn.execute(
            "INSERT INTO agent_asset_v1 (asset_id, version, kind, name,"
            " content, meta_json, status, customer_id, created_by,"
            " created_at, updated_at) VALUES ('sk-1',1,'skill','旧技能',"
            " '步骤…','{}','published','','tester',"
            " '2026-08-01T00:00:00Z','2026-08-01T00:00:00Z')")
        store._conn.commit()
        rows = svc.legacy_projection(ctx)
        assert len(rows) == 1
        assert rows[0]["asset_id"] == "sk-1"
        assert rows[0]["_origin"] == "agent_asset_v1"
        assert svc.can_execute(ctx, "sk-1")["allowed"] is False
