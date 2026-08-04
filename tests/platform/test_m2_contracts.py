"""W6/M2：契约冻结（Asset/Evidence/Audit/Usage）+ IAM 最小模型 TDD。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.platform import contracts
from src.platform.iam import ACTION_MIN_ROLE, ROLES, can


# ---------- 契约冻结 ----------

def test_contract_version_frozen() -> None:
    assert contracts.CONTRACT_VERSION == "1.0.0"


def test_asset_ref_roundtrip() -> None:
    ref = contracts.AssetRef(asset_id="a1", sha256="0" * 64, kind="photo", size_bytes=123)
    data = ref.model_dump()
    assert contracts.AssetRef.model_validate(data) == ref


def test_asset_ref_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        contracts.AssetRef(
            asset_id="a1", sha256="0" * 64, kind="photo", size_bytes=1, sneaky="x"
        )


def test_asset_ref_rejects_negative_size() -> None:
    with pytest.raises(ValidationError):
        contracts.AssetRef(asset_id="a1", sha256="0" * 64, kind="photo", size_bytes=-1)


def test_evidence_manifest_structure() -> None:
    item = contracts.EvidenceItem(
        role="input_photo",
        asset=contracts.AssetRef(asset_id="a1", sha256="1" * 64, kind="photo", size_bytes=10),
    )
    m = contracts.EvidenceManifest(evidence_id="ev1", run_id="r1", kind="recognition", items=[item])
    data = m.model_dump()
    parsed = contracts.EvidenceManifest.model_validate(data)
    assert parsed.items[0].asset.sha256 == "1" * 64


def test_evidence_manifest_rejects_extra() -> None:
    with pytest.raises(ValidationError):
        contracts.EvidenceManifest(
            evidence_id="ev1", run_id="r1", kind="x", items=[], arbitrary=True
        )


def test_audit_record_defaults() -> None:
    rec = contracts.AuditRecord(
        ts="2026-08-01T00:00:00+00:00",
        actor="system",
        action="run.created",
        subject_type="run",
        subject_id="r1",
    )
    assert rec.detail == {}


def test_usage_record() -> None:
    rec = contracts.UsageRecord(
        ts="2026-08-01T00:00:00+00:00",
        capability="legacy.recognition.v2",
        run_id=None,
        quantity=1.0,
        unit="call",
    )
    assert rec.quantity == 1.0
    with pytest.raises(ValidationError):
        contracts.UsageRecord(
            ts="t", capability="c", run_id=None, quantity="not-a-number", unit="u"
        )


# ---------- IAM 最小模型 ----------

def test_roles_defined() -> None:
    assert set(ROLES) == {"viewer", "operator", "admin"}


def test_viewer_can_only_view() -> None:
    assert can("viewer", "view") is True
    assert can("viewer", "run.execute") is False
    assert can("viewer", "gate.approve") is False


def test_operator_cannot_approve_training_or_publish() -> None:
    assert can("operator", "run.execute") is True
    assert can("operator", "gate.approve") is True
    assert can("operator", "training.request") is True
    # 红线：训练审批与模型发布审批必须是独立的高权限动作
    assert can("operator", "training.approve") is False
    assert can("operator", "model.publish.approve") is False


def test_admin_can_approve_both_separately() -> None:
    assert can("admin", "training.approve") is True
    assert can("admin", "model.publish.approve") is True
    # 两个动作必须是不同的 action key（不得合并）
    assert "training.approve" in ACTION_MIN_ROLE
    assert "model.publish.approve" in ACTION_MIN_ROLE


def test_unknown_role_or_action_denied() -> None:
    assert can("ghost", "view") is False
    assert can("admin", "nonexistent.action") is False
