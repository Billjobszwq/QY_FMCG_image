"""M5（G4）：模型管理 IAM 权限正负矩阵（02 §7）。

矩阵（fail-closed）：
- 普通员工（无 membership/无 models scope）：八个 models scope 全无；
- 模型管理员：可 draft/测试/轮换/提交（无批准权，是 maker）；
- 模型审批人：可批准，不可轮换 secret / 管理连接；
- 审计员：只读（audit/config/usage），不可管理；
- 财务：仅 usage read，不见 Connection Secret 元数据（无 config.read）；
- 平台管理员/租户所有者：全部；
- 同一主体同时持有 manage+approve 时，maker≠checker 仍强制。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.platform.data.store import PlatformStore
from src.platform.iam import IAMService

MODEL_SCOPES = (
    "models.use", "models.config.read", "models.connection.manage",
    "models.secret.rotate", "models.binding.manage",
    "models.release.approve", "models.usage.read", "models.audit.read",
)


@pytest.fixture()
def iam(tmp_path: Path):
    store = PlatformStore(tmp_path / "p.sqlite")
    service = IAMService(store)
    yield service
    store.close()


def _user(iam, username: str, role: str | None) -> str:
    iam.create_principal(kind="user", username=username,
                         password="pw-" + username,
                         created_by="seed")
    if role:
        iam.grant(username=username, role=role, granted_by="seed")
    return username


class TestRoleMatrix:
    def test_employee_has_no_model_scopes(self, iam):
        _user(iam, "emp", None)
        assert iam.scopes_of("emp") == []
        for scope in MODEL_SCOPES:
            assert not iam.authorize("emp", scope), scope

    def test_model_admin_can_manage_but_not_approve(self, iam):
        _user(iam, "madmin", "model_admin")
        for scope in ("models.use", "models.config.read",
                      "models.connection.manage", "models.secret.rotate",
                      "models.binding.manage", "models.usage.read"):
            assert iam.authorize("madmin", scope), scope
        assert not iam.authorize("madmin", "models.release.approve")
        assert not iam.authorize("madmin", "models.audit.read")

    def test_model_approver_can_approve_but_not_manage(self, iam):
        _user(iam, "approver", "model_approver")
        assert iam.authorize("approver", "models.release.approve")
        assert iam.authorize("approver", "models.config.read")
        for scope in ("models.connection.manage", "models.secret.rotate",
                      "models.binding.manage"):
            assert not iam.authorize("approver", scope), scope

    def test_auditor_read_only(self, iam):
        _user(iam, "audit", "auditor")
        assert iam.authorize("audit", "models.audit.read")
        assert iam.authorize("audit", "models.config.read")
        assert iam.authorize("audit", "models.usage.read")
        for scope in ("models.connection.manage", "models.secret.rotate",
                      "models.binding.manage", "models.release.approve"):
            assert not iam.authorize("audit", scope), scope

    def test_finance_only_usage_read(self, iam):
        _user(iam, "fin", "finance_operator")
        assert iam.authorize("fin", "models.usage.read")
        for scope in ("models.config.read", "models.connection.manage",
                      "models.secret.rotate", "models.binding.manage",
                      "models.release.approve", "models.audit.read"):
            assert not iam.authorize("fin", scope), scope

    def test_platform_admin_has_full_models_scopes(self, iam):
        _user(iam, "padmin", "platform_admin")
        for scope in MODEL_SCOPES:
            assert iam.authorize("padmin", scope), scope

    def test_owner_has_full_models_scopes(self, iam):
        _user(iam, "boss", "owner")
        for scope in MODEL_SCOPES:
            assert iam.authorize("boss", scope), scope

    def test_unknown_scope_fail_closed(self, iam):
        _user(iam, "madmin2", "model_admin")
        assert not iam.authorize("madmin2", "models.superpower")

    def test_scopes_visible_in_whoami_projection(self, iam):
        _user(iam, "madmin3", "model_admin")
        scopes = iam.scopes_of("madmin3")
        assert "models.config.read" in scopes
        assert "models.release.approve" not in scopes


class TestMakerCheckerEvenWithBothPowers:
    def test_same_principal_manage_and_approve_still_needs_two_actors(
            self, iam, tmp_path):
        """同一主体持有 manage+approve 时，自批仍被账本拒绝。"""
        from src.platform.governance.policy_service import (
            GovernanceError, GovernanceRoleError, PolicyService)
        from src.platform.models.service import ModelManagementServices
        from src.platform.models.secrets import EncryptedSQLiteSecretStore

        store2 = PlatformStore(tmp_path / "m.sqlite")
        svc = ModelManagementServices(
            store2, secret_store=EncryptedSQLiteSecretStore(
                store2, kek=bytes(range(32))))
        # 1) maker 自决：decide 层即拒绝
        a1 = svc.policy.request_generic_approval(
            kind="model.connection.activate",
            subject_ref="conn-x@v1", requested_by="dual-admin")
        with pytest.raises(GovernanceRoleError):
            svc.policy.decide_approval(a1["approval_id"],
                                       actor="dual-admin",
                                       decision="approved")
        # 2) 即便他人已批准，verify 仍拒绝把 maker 记为批准人
        # （decided_by 一致性与 maker≠checker 双层防御，均为治理错误）
        a2 = svc.policy.request_generic_approval(
            kind="model.connection.activate",
            subject_ref="conn-y@v1", requested_by="dual-admin")
        svc.policy.decide_approval(a2["approval_id"],
                                   actor="other-human",
                                   decision="approved")
        with pytest.raises(GovernanceError):
            svc.policy.verify_approved(
                a2["approval_id"],
                kind="model.connection.activate",
                subject_ref="conn-y@v1", approver="dual-admin")
        store2.close()
