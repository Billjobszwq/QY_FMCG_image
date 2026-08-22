"""M4（G3）：Repository/Resolver/Service 的解析优先级、ACL 与 CAS 测试。"""
from __future__ import annotations

import base64
import threading
from pathlib import Path

import pytest

from src.platform.data.store import PlatformStore
from src.platform.models.contracts import (
    BindingDraft,
    Capability,
    CasConflictError,
    CatalogManualEntry,
    ConnectionDraft,
    StateMachineError,
    SubjectKind,
)
from src.platform.models.providers.base import (
    ProbeResult,
    ProviderAuthFailed,
    ProviderModel,
)
from src.platform.models.secrets import EncryptedSQLiteSecretStore
from src.platform.models.service import ModelManagementServices

KEK = bytes(range(32))
API_KEY = b"sk-live-test-key-for-m4"


class FakeAdapter:
    kind = "openai_compatible"

    def __init__(self, *, fail_auth: bool = False):
        self.fail_auth = fail_auth

    def list_models(self):
        if self.fail_auth:
            raise ProviderAuthFailed("bad key")
        return [ProviderModel(model_id="fake-embed"),
                ProviderModel(model_id="fake-chat")]

    def probe(self, model_id, capability):
        if self.fail_auth:
            raise ProviderAuthFailed("bad key")
        dim = 8 if capability == "embedding" else None
        return ProbeResult(ok=True, capability=capability,
                           model_id=model_id, dimension=dim)

    def embed(self, request):
        raise AssertionError("M4 不做真实调用")

    def chat(self, request):
        raise AssertionError("M4 不做真实调用")


@pytest.fixture()
def services(tmp_path: Path):
    store = PlatformStore(tmp_path / "p.sqlite")
    state = {"fail_auth": False}

    def factory(row, get_secret):
        return FakeAdapter(fail_auth=state["fail_auth"])

    from src.platform.models.endpoint_policy import EndpointPolicy
    svc = ModelManagementServices(
        store,
        secret_store=EncryptedSQLiteSecretStore(store, kek=KEK),
        adapter_factory=factory,
        endpoint_policy=EndpointPolicy(
            resolver=lambda host, port: ["93.184.216.34"]))
    svc._test_state = state  # type: ignore[attr-defined]
    yield svc
    store.close()


def _draft_local(**over) -> ConnectionDraft:
    base = {
        "name": "local-omlx", "location": "local",
        "adapter_kind": "openai_compatible",
        "api_flavor": "chat_completions",
        "base_url": "http://127.0.0.1:8455/v1",
        "timeout_ms": 30000, "max_retries": 1,
    }
    base.update(over)
    return ConnectionDraft.model_validate(base)


def _activate_connection(svc, *, connection_id="local-omlx",
                         checker="checker-human", maker="maker-admin",
                         draft=None) -> int:
    draft = draft or _draft_local()
    row = svc.create_connection_draft(tenant_id="local", draft=draft,
                                      actor=maker,
                                      connection_id=connection_id)
    r = svc.test_connection(tenant_id="local",
                            connection_id=row.connection_id,
                            version=row.version, actor=maker)
    assert r["status"] == "ready"
    sub = svc.submit_connection(tenant_id="local",
                                connection_id=row.connection_id,
                                version=row.version, actor=maker)
    approval = svc.policy.get_approval(sub["approval_id"])
    svc.policy.decide_approval(approval["approval_id"], actor=checker,
                               decision="approved")
    out = svc.approve_connection(tenant_id="local",
                                 connection_id=row.connection_id,
                                 version=row.version, approver=checker,
                                 approval_id=sub["approval_id"])
    assert out["status"] == "active"
    return row.version


def _catalog_ready(svc, *, connection_id="local-omlx", version=1,
                   model_id="fake-embed", capability="embedding",
                   dimension=8) -> None:
    entry = CatalogManualEntry.model_validate({
        "model_id": model_id, "capabilities": [capability],
        "embedding_dimension": dimension,
        "normalization_version": "v1"})
    cat = svc.register_manual(tenant_id="local",
                              connection_id=connection_id,
                              version=version, entry=entry,
                              actor="maker-admin")
    result = svc.probe_model(tenant_id="local", catalog_id=cat.catalog_id,
                             actor="maker-admin")
    assert result["probe_status"] == "ready"


def _bind_active(svc, *, binding_id="cognition-embedding-default",
                 customer_id="", project_id="",
                 subject_kind=SubjectKind.system_capability,
                 subject_id="embedding", capability=Capability.embedding,
                 model_id="fake-embed", connection_version=1,
                 checker="checker-human", maker="maker-admin",
                 connection_id="local-omlx") -> int:
    draft = BindingDraft.model_validate({
        "customer_id": customer_id, "project_id": project_id,
        "subject_kind": subject_kind.value, "subject_id": subject_id,
        "capability": capability.value, "connection_id": connection_id,
        "connection_version": connection_version, "model_id": model_id})
    row = svc.create_binding_draft(tenant_id="local", draft=draft,
                                   actor=maker, binding_id=binding_id)
    svc.validate_binding(tenant_id="local", binding_id=row.binding_id,
                         version=row.version, actor=maker)
    sub = svc.submit_binding(tenant_id="local", binding_id=row.binding_id,
                             version=row.version, actor=maker)
    svc.policy.decide_approval(sub["approval_id"], actor=checker,
                               decision="approved")
    svc.activate_binding(tenant_id="local", binding_id=row.binding_id,
                         version=row.version, approver=checker,
                         approval_id=sub["approval_id"])
    return row.version


def _resolve(svc, *, subject_id="research-rag",
             subject_kind=SubjectKind.module,
             capability=Capability.embedding, customer_id="",
             project_id="", tenant_id="local"):
    from src.platform.models.contracts import ResolveRequest
    return svc.resolver.resolve(ResolveRequest.model_validate({
        "principal_id": "svc-test", "tenant_id": tenant_id,
        "customer_id": customer_id, "project_id": project_id,
        "subject_kind": subject_kind.value, "subject_id": subject_id,
        "capability": capability.value,
        "as_of": "2027-01-01T00:00:00+00:00"}))


class TestConnectionLifecycle:
    def test_full_lifecycle_to_active(self, services):
        version = _activate_connection(services)
        row = services.repo.get_connection(
            tenant_id="local", connection_id="local-omlx", version=version)
        assert row.status == "active"

    def test_test_failure_returns_draft_and_keeps_active(self, services):
        v1 = _activate_connection(services)
        # v2 测试失败：fake provider 认证失败 → 回 draft；active v1 不变
        services._test_state["fail_auth"] = True
        row = services.create_connection_draft(
            tenant_id="local", draft=_draft_local(), actor="maker-admin",
            connection_id="local-omlx")
        assert row.version == v1 + 1
        result = services.test_connection(
            tenant_id="local", connection_id="local-omlx",
            version=row.version, actor="maker-admin")
        assert result["ok"] is False
        assert result["detail"] == "MODEL_AUTH_FAILED"
        v2 = services.repo.get_connection(
            tenant_id="local", connection_id="local-omlx",
            version=row.version)
        assert v2.status == "draft", "测试失败必须回 draft"
        v1_row = services.repo.get_connection(
            tenant_id="local", connection_id="local-omlx", version=v1)
        assert v1_row.status == "active", "active 版本不得被测试影响"

    def test_concurrent_activate_single_winner(self, services):
        """两个并发 approve 只有一个获胜（CAS 单赢家）。"""
        draft = _draft_local()
        row = services.create_connection_draft(
            tenant_id="local", draft=draft, actor="maker-admin",
            connection_id="race-conn")
        services.test_connection(tenant_id="local",
                                 connection_id="race-conn",
                                 version=1, actor="maker-admin")
        sub = services.submit_connection(tenant_id="local",
                                         connection_id="race-conn",
                                         version=1, actor="maker-admin")
        services.policy.decide_approval(sub["approval_id"],
                                        actor="checker-human",
                                        decision="approved")
        results, errors = [], []

        def attempt():
            try:
                results.append(services.approve_connection(
                    tenant_id="local", connection_id="race-conn",
                    version=1, approver="checker-human",
                    approval_id=sub["approval_id"]))
            except CasConflictError as e:
                errors.append(e)

        t1 = threading.Thread(target=attempt)
        t2 = threading.Thread(target=attempt)
        t1.start(); t2.start(); t1.join(); t2.join()
        assert len(results) == 1, f"单赢家违反: {len(results)} 成功"
        assert len(errors) == 1

    def test_disable_blocks_resolve(self, services):
        _activate_connection(services)
        _catalog_ready(services)
        _bind_active(services)
        assert _resolve(services) is not None
        row = services.repo.get_connection(
            tenant_id="local", connection_id="local-omlx", version=1)
        services.disable_connection(tenant_id="local",
                                    connection_id="local-omlx",
                                    version=1, actor="checker-human")
        assert _resolve(services) is None, "disabled 连接不得被解析"


class TestResolverPriorityAndScope:
    def test_project_customer_tenant_priority(self, services):
        _activate_connection(services)
        _catalog_ready(services)
        # tenant 默认（模块级）
        _bind_active(services, binding_id="bind-tenant",
                     subject_kind=SubjectKind.module,
                     subject_id="research-rag", model_id="fake-embed")
        resolved = _resolve(services)
        assert resolved.binding_id == "bind-tenant"

        # customer 绑定优先于 tenant
        _bind_active(services, binding_id="bind-cust",
                     subject_kind=SubjectKind.module,
                     subject_id="research-rag", customer_id="c1")
        resolved = _resolve(services, customer_id="c1")
        assert resolved.binding_id == "bind-cust"
        resolved = _resolve(services, customer_id="c2")
        assert resolved.binding_id == "bind-tenant", "c2 不应命中 c1 绑定"

        # project 绑定优先于 customer
        _bind_active(services, binding_id="bind-proj",
                     subject_kind=SubjectKind.module,
                     subject_id="research-rag", customer_id="c1",
                     project_id="p1")
        resolved = _resolve(services, customer_id="c1", project_id="p1")
        assert resolved.binding_id == "bind-proj"
        resolved = _resolve(services, customer_id="c1", project_id="p2")
        assert resolved.binding_id == "bind-cust"

    def test_module_binding_beats_capability_default(self, services):
        _activate_connection(services)
        _catalog_ready(services)
        _bind_active(services, binding_id="cap-default",
                     subject_kind=SubjectKind.system_capability,
                     subject_id="embedding")
        _bind_active(services, binding_id="module-bind",
                     subject_kind=SubjectKind.module,
                     subject_id="research-rag")
        resolved = _resolve(services)
        assert resolved.binding_id == "module-bind"
        # 其它模块落到 capability default
        resolved = _resolve(services, subject_id="kb-build")
        assert resolved.binding_id == "cap-default"

    def test_cross_tenant_zero_leak(self, services):
        _activate_connection(services)
        _catalog_ready(services)
        _bind_active(services)
        assert _resolve(services, tenant_id="other-tenant") is None

    def test_canary_scope_isolation(self, services):
        v1 = _activate_connection(services)
        _catalog_ready(services, version=v1)
        _bind_active(services, binding_id="bind-base",
                     subject_kind=SubjectKind.module,
                     subject_id="research-rag", customer_id="c1")
        # canary：同 scope 的新版本，明确 customer 范围
        draft = BindingDraft.model_validate({
            "customer_id": "c1", "project_id": "",
            "subject_kind": "module", "subject_id": "research-rag",
            "capability": "embedding", "connection_id": "local-omlx",
            "connection_version": v1, "model_id": "fake-embed"})
        row = services.create_binding_draft(
            tenant_id="local", draft=draft, actor="maker-admin",
            binding_id="bind-base")
        services.validate_binding(tenant_id="local",
                                  binding_id=row.binding_id,
                                  version=row.version, actor="maker-admin")
        sub = services.submit_binding(tenant_id="local",
                                      binding_id=row.binding_id,
                                      version=row.version,
                                      actor="maker-admin")
        services.policy.decide_approval(sub["approval_id"],
                                        actor="checker-human",
                                        decision="approved")
        out = services.activate_canary(
            tenant_id="local", binding_id=row.binding_id,
            version=row.version, approver="checker-human",
            approval_id=sub["approval_id"])
        assert out["status"] == "canary"
        # c1 命中 canary 新版本；其它客户仍是旧 active
        resolved = _resolve(services, customer_id="c1")
        assert resolved.binding_version == row.version
        assert resolved.binding_id == "bind-base"
        # 没有 active 的 c2：不命中 canary（canary 仅限 c1）
        assert _resolve(services, customer_id="c2") is None

    def test_empty_scope_canary_rejected(self, services):
        _activate_connection(services)
        _catalog_ready(services)
        draft = BindingDraft.model_validate({
            "subject_kind": "module", "subject_id": "research-rag",
            "capability": "embedding", "connection_id": "local-omlx",
            "connection_version": 1, "model_id": "fake-embed"})
        row = services.create_binding_draft(
            tenant_id="local", draft=draft, actor="maker-admin",
            binding_id="bind-canary-empty")
        services.validate_binding(tenant_id="local",
                                  binding_id=row.binding_id,
                                  version=row.version, actor="maker-admin")
        sub = services.submit_binding(tenant_id="local",
                                      binding_id=row.binding_id,
                                      version=row.version,
                                      actor="maker-admin")
        services.policy.decide_approval(sub["approval_id"],
                                        actor="checker-human",
                                        decision="approved")
        with pytest.raises(StateMachineError):
            services.activate_canary(
                tenant_id="local", binding_id=row.binding_id,
                version=row.version, approver="checker-human",
                approval_id=sub["approval_id"])

    def test_unprobed_model_cannot_bind(self, services):
        _activate_connection(services)
        entry = CatalogManualEntry.model_validate({
            "model_id": "fake-chat", "capabilities": ["chat"]})
        services.register_manual(tenant_id="local",
                                 connection_id="local-omlx", version=1,
                                 entry=entry, actor="maker-admin")
        draft = BindingDraft.model_validate({
            "subject_kind": "module", "subject_id": "supervisor",
            "capability": "chat", "connection_id": "local-omlx",
            "connection_version": 1, "model_id": "fake-chat"})
        row = services.create_binding_draft(
            tenant_id="local", draft=draft, actor="maker-admin",
            binding_id="bind-unprobed")
        with pytest.raises(StateMachineError):
            services.validate_binding(tenant_id="local",
                                      binding_id=row.binding_id,
                                      version=row.version,
                                      actor="maker-admin")

    def test_expected_etag_mismatch_raises_cas(self, services):
        _activate_connection(services)
        _catalog_ready(services)
        draft = BindingDraft.model_validate({
            "subject_kind": "module", "subject_id": "research-rag",
            "capability": "embedding", "connection_id": "local-omlx",
            "connection_version": 1, "model_id": "fake-embed"})
        row = services.create_binding_draft(
            tenant_id="local", draft=draft, actor="maker-admin",
            binding_id="bind-etag")
        with pytest.raises(CasConflictError):
            services.validate_binding(tenant_id="local",
                                      binding_id=row.binding_id,
                                      version=row.version,
                                      actor="maker-admin",
                                      expected_etag="stale-etag")

    def test_agent_definition_source_wins(self, services):
        _activate_connection(services)
        _catalog_ready(services)
        _bind_active(services)

        def lookup(req):
            return {"connection_id": "local-omlx",
                    "connection_version": 1,
                    "adapter_kind": "openai_compatible",
                    "location": "local", "model_id": "agent-model",
                    "model_revision": "", "embedding_dimension": None,
                    "normalization_version": None,
                    "binding_id": "", "binding_version": 0}

        from src.platform.models.resolver import ModelResolver
        resolver = ModelResolver(services.repo,
                                 agent_definition_lookup=lookup)
        from src.platform.models.contracts import ResolveRequest
        req = ResolveRequest.model_validate({
            "principal_id": "svc", "tenant_id": "local",
            "subject_kind": "module", "subject_id": "agent-x",
            "capability": "chat", "as_of": "2027-01-01T00:00:00+00:00"})
        resolved = resolver.resolve(req)
        assert resolved is not None
        assert resolved.source == "agent_definition"
        assert resolved.model_id == "agent-model"


class TestSecretIntegration:
    def test_api_connection_secret_flow_write_only(self, services):
        draft = _draft_local(location="api",
                             base_url="https://api.example.com/v1")
        row = services.create_connection_draft(
            tenant_id="local", draft=draft, actor="maker-admin",
            connection_id="openai-prod")
        out = services.set_secret(tenant_id="local",
                                  connection_id="openai-prod",
                                  version=1, value=API_KEY,
                                  actor="maker-admin")
        assert out["secret_configured"] is True
        assert API_KEY.decode() not in str(out)
        # live DB 副本文件无明文
        blobs = services.store._path.read_bytes()
        assert API_KEY not in blobs

    def test_missing_kek_blocks_secret_operations(self, tmp_path):
        from src.platform.models.secrets import SecretStoreUnavailable
        from src.platform.models.endpoint_policy import EndpointPolicy
        store = PlatformStore(tmp_path / "p.sqlite")
        svc = ModelManagementServices(
            store, secret_store=EncryptedSQLiteSecretStore(store, kek=None),
            endpoint_policy=EndpointPolicy(
                resolver=lambda host, port: ["93.184.216.34"]))
        draft = _draft_local(location="api",
                             base_url="https://api.example.com/v1")
        row = svc.create_connection_draft(
            tenant_id="local", draft=draft, actor="maker-admin",
            connection_id="no-kek")
        with pytest.raises(SecretStoreUnavailable):
            svc.set_secret(tenant_id="local", connection_id="no-kek",
                           version=1, value=API_KEY, actor="maker-admin")
        store.close()
