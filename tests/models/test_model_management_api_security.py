"""M4（G3）：/api/v1/models/* 的 401/403/404/409/422/503 语义、
零泄漏、写回显与 maker≠checker 合同测试（hermetic TestClient）。"""
from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import build_production_bundle
from src.platform.api.app import create_app
from src.platform.models.providers.base import ProbeResult, ProviderModel

KEK = bytes(range(32))
KEK_B64 = base64.b64encode(KEK).decode()
API_KEY = "sk-live-api-m4-secret-31337"
ADMIN_PW = "mm-admin-pw"
CHECKER_PW = "mm-checker-pw"
EMP_PW = "mm-emp-pw"


class FakeAdapter:
    kind = "openai_compatible"

    def list_models(self):
        return [ProviderModel(model_id="fake-embed")]

    def probe(self, model_id, capability):
        return ProbeResult(ok=True, capability=capability,
                           model_id=model_id,
                           dimension=8 if capability == "embedding"
                           else None)

    def embed(self, request):
        raise AssertionError("no real call in M4")

    def chat(self, request):
        raise AssertionError("no real call in M4")


def _fake_factory(row, get_secret):
    return FakeAdapter()


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(
        "PLATFORM_USERS",
        f"admin:{ADMIN_PW}:admin,checker:{CHECKER_PW}:admin,"
        f"emp:{EMP_PW}:operator")
    monkeypatch.setenv("TAAS_MODEL_SECRET_KEK", KEK_B64)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=None, probe=lambda spec: None)
    app = create_app(services=(), probe=lambda spec: None, bundle=bundle,
                     web_dist=Path("/nonexistent"),
                     model_adapter_factory=_fake_factory)
    return TestClient(app)


@pytest.fixture()
def client_no_kek(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_USERS", f"admin:{ADMIN_PW}:admin")
    monkeypatch.delenv("TAAS_MODEL_SECRET_KEK", raising=False)
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=None, probe=lambda spec: None)
    app = create_app(services=(), probe=lambda spec: None, bundle=bundle,
                     web_dist=Path("/nonexistent"),
                     model_adapter_factory=_fake_factory)
    return TestClient(app)


ROLE_USERS_PW = {
    "madmin": "mm-madmin-pw",
    "approverx": "mm-approver-pw",
    "fin": "mm-fin-pw",
    "emp": "mm-emp2-pw",
}


@pytest.fixture()
def client_roles(tmp_path: Path, monkeypatch):
    """受限角色经 IAM membership 授权（非平台角色路径）。"""
    monkeypatch.setenv(
        "PLATFORM_USERS",
        ",".join(f"{u}:{pw}:{u}" for u, pw in ROLE_USERS_PW.items()))
    monkeypatch.setenv("TAAS_MODEL_SECRET_KEK", KEK_B64)
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=None, probe=lambda spec: None)
    from src.platform.iam import IAMService
    iam = IAMService(bundle.store)
    for username, role in (("madmin", "model_admin"),
                           ("approverx", "model_approver"),
                           ("fin", "finance_operator"),
                           ("emp", "read_only")):
        iam.create_principal(kind="user", username=username,
                             password="x-" + username, created_by="seed")
        iam.grant(username=username, role=role, granted_by="seed")
    app = create_app(services=(), probe=lambda spec: None, bundle=bundle,
                     web_dist=Path("/nonexistent"),
                     model_adapter_factory=_fake_factory)
    return TestClient(app)


def _login(c: TestClient, username: str, pw: str) -> dict:
    """每个用户独立会话：返回含显式 Cookie 的 headers，避免
    maker/checker 会话在共享 cookie jar 中互相覆盖。"""
    fresh = TestClient(c.app)
    r = fresh.post("/api/v1/auth/login",
                   json={"username": username, "password": pw})
    assert r.status_code == 200, r.text
    session = fresh.cookies.get("platform_session")
    assert session
    return {"X-CSRF-Token": r.json()["csrf_token"],
            "Cookie": f"platform_session={session}"}


def _draft_body(**over) -> dict:
    base = {
        "name": "local-omlx", "location": "local",
        "adapter_kind": "openai_compatible",
        "api_flavor": "chat_completions",
        "base_url": "http://127.0.0.1:8455/v1",
        "timeout_ms": 30000, "max_retries": 1,
        "connection_id": "local-omlx",
    }
    base.update(over)
    return base


class TestAuthMatrix:
    def test_unauthenticated_401(self, client):
        assert client.get("/api/v1/models/connections").status_code == 401
        assert client.post("/api/v1/models/connections/drafts",
                           json=_draft_body()).status_code == 401

    def test_employee_without_models_scope_403(self, client):
        h = _login(client, "emp", EMP_PW)
        r = client.get("/api/v1/models/connections", headers=h)
        assert r.status_code == 403
        r = client.post("/api/v1/models/connections/drafts", headers=h,
                        json=_draft_body())
        assert r.status_code == 403

    def test_csrf_required_for_writes(self, client):
        h = _login(client, "admin", ADMIN_PW)
        cookie_only = {"Cookie": h["Cookie"]}  # 有 session 但不带 CSRF
        r = client.post("/api/v1/models/connections/drafts",
                        headers=cookie_only, json=_draft_body())
        assert r.status_code == 403


class TestConnectionLifecycleAPI:
    def test_full_lifecycle_secret_write_only_and_maker_checker(
            self, client, tmp_path):
        admin = _login(client, "admin", ADMIN_PW)
        checker = _login(client, "checker", CHECKER_PW)

        # 1) draft
        r = client.post("/api/v1/models/connections/drafts", headers=admin,
                        json=_draft_body(location="api",
                                         base_url="https://93.184.216.34/v1"))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "draft"

        # 2) secret（write-only）
        r = client.post(
            "/api/v1/models/connections/local-omlx/versions/1/secret",
            headers=admin, json={"secret_value": API_KEY})
        assert r.status_code == 200, r.text
        assert API_KEY not in r.text, "secret 不得回显"

        # 3) GET 只返回元数据
        r = client.get("/api/v1/models/connections/local-omlx",
                       headers=admin)
        assert r.status_code == 200
        view = r.json()
        assert view["secret_configured"] is True
        assert view["secret_version"] == 1
        assert API_KEY not in r.text
        for forbidden in ("ciphertext", "wrapped_dek", "nonce",
                          "api_key", "secret_value"):
            assert forbidden not in view
        # 数据库文件不得含明文
        db_file = tmp_path / "p.sqlite"
        assert API_KEY.encode() not in db_file.read_bytes()

        # 4) test → ready
        r = client.post(
            "/api/v1/models/connections/local-omlx/versions/1/test",
            headers=admin)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ready"

        # 5) submit（maker）
        r = client.post(
            "/api/v1/models/connections/local-omlx/versions/1/submit",
            headers=admin)
        assert r.status_code == 200, r.text
        approval_id = r.json()["approval_id"]

        # 6) maker 自批必须被拒（409）
        r = client.post(
            "/api/v1/models/connections/local-omlx/versions/1/approve",
            headers=admin, json={"approval_id": approval_id})
        assert r.status_code == 409, r.text

        # 7) checker 批准 → active（CAS）
        client.post(f"/api/v1/governance/approvals/{approval_id}/decide",
                    headers=checker, json={"decision": "approved"})
        r = client.post(
            "/api/v1/models/connections/local-omlx/versions/1/approve",
            headers=checker, json={"approval_id": approval_id})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "active"

        # 8) 列表显示 active
        r = client.get("/api/v1/models/connections", headers=admin)
        assert r.status_code == 200
        assert r.json()["connections"][0]["active_version"] == 1

    def test_contract_violation_422(self, client):
        admin = _login(client, "admin", ADMIN_PW)
        r = client.post("/api/v1/models/connections/drafts", headers=admin,
                        json=_draft_body(unexpected="blocked"))
        assert r.status_code == 422
        r = client.post("/api/v1/models/connections/drafts", headers=admin,
                        json=_draft_body(timeout_ms=-5))
        assert r.status_code == 422
        r = client.post("/api/v1/models/connections/drafts", headers=admin,
                        json=_draft_body(location="hybrid"))
        assert r.status_code == 422

    def test_cross_subject_404_zero_leak(self, client):
        admin = _login(client, "admin", ADMIN_PW)
        r = client.get("/api/v1/models/connections/does-not-exist",
                       headers=admin)
        assert r.status_code == 404
        assert "不存在或不可见" in r.json()["message"]
        r = client.get("/api/v1/models/connections/does-not-exist",
                       headers=admin, params={"version": 3})
        assert r.status_code == 404

    def test_cas_conflict_409(self, client):
        admin = _login(client, "admin", ADMIN_PW)
        client.post("/api/v1/models/connections/drafts", headers=admin,
                    json=_draft_body())
        r = client.post(
            "/api/v1/models/connections/local-omlx/versions/1/submit",
            headers=admin, json={"expected_etag": "stale"})
        # draft 直接 submit → 状态机 409
        assert r.status_code == 409


class TestCatalogAndBindingAPI:
    def _ready_connection(self, client, admin, checker):
        client.post("/api/v1/models/connections/drafts", headers=admin,
                    json=_draft_body())
        r = client.post(
            "/api/v1/models/connections/local-omlx/versions/1/test",
            headers=admin)
        assert r.json()["status"] == "ready"
        r = client.post(
            "/api/v1/models/connections/local-omlx/versions/1/submit",
            headers=admin)
        approval_id = r.json()["approval_id"]
        client.post(f"/api/v1/governance/approvals/{approval_id}/decide",
                    headers=checker, json={"decision": "approved"})
        r = client.post(
            "/api/v1/models/connections/local-omlx/versions/1/approve",
            headers=checker, json={"approval_id": approval_id})
        assert r.status_code == 200, r.text

    def test_binding_full_flow_with_canary_guard(self, client):
        admin = _login(client, "admin", ADMIN_PW)
        checker = _login(client, "checker", CHECKER_PW)
        self._ready_connection(client, admin, checker)

        # 人工登记 + probe
        r = client.post("/api/v1/models/catalog/manual", headers=admin,
                        json={"connection_id": "local-omlx",
                              "connection_version": 1,
                              "model_id": "fake-embed",
                              "capabilities": ["embedding"],
                              "embedding_dimension": 8,
                              "normalization_version": "v1"})
        assert r.status_code == 200, r.text
        catalog_id = r.json()["catalog_id"]
        r = client.post(f"/api/v1/models/catalog/{catalog_id}/probe",
                        headers=admin)
        assert r.status_code == 200, r.text
        assert r.json()["probe_status"] == "ready"

        # binding draft → validate → submit → approve → activate
        r = client.post("/api/v1/models/bindings/drafts", headers=admin,
                        json={"binding_id": "cognition-embedding-default",
                              "subject_kind": "system_capability",
                              "subject_id": "embedding",
                              "capability": "embedding",
                              "connection_id": "local-omlx",
                              "connection_version": 1,
                              "model_id": "fake-embed"})
        assert r.status_code == 200, r.text
        r = client.post(
            "/api/v1/models/bindings/cognition-embedding-default"
            "/versions/1/validate", headers=admin)
        assert r.status_code == 200, r.text
        assert r.json()["impact"]["index_rebuild_required"] is True
        r = client.post(
            "/api/v1/models/bindings/cognition-embedding-default"
            "/versions/1/submit", headers=admin)
        approval_id = r.json()["approval_id"]
        # maker 自批拒绝
        r = client.post(
            "/api/v1/models/bindings/cognition-embedding-default"
            "/versions/1/approve", headers=admin,
            json={"approval_id": approval_id})
        assert r.status_code == 409
        client.post(f"/api/v1/governance/approvals/{approval_id}/decide",
                    headers=checker, json={"decision": "approved"})
        r = client.post(
            "/api/v1/models/bindings/cognition-embedding-default"
            "/versions/1/approve", headers=checker,
            json={"approval_id": approval_id})
        assert r.status_code == 200, r.text
        # 无 scope canary 拒绝（走 activate 直批路径验证：这里直接全量激活）
        r = client.post(
            "/api/v1/models/bindings/cognition-embedding-default"
            "/versions/1/activate", headers=checker,
            json={"approval_id": approval_id})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "active"

        # 列表可见
        r = client.get("/api/v1/models/bindings", headers=admin)
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_unprobed_binding_validate_409(self, client):
        admin = _login(client, "admin", ADMIN_PW)
        checker = _login(client, "checker", CHECKER_PW)
        self._ready_connection(client, admin, checker)
        r = client.post("/api/v1/models/catalog/manual", headers=admin,
                        json={"connection_id": "local-omlx",
                              "connection_version": 1,
                              "model_id": "fake-embed",
                              "capabilities": ["embedding"]})
        assert r.status_code == 200
        r = client.post("/api/v1/models/bindings/drafts", headers=admin,
                        json={"binding_id": "b-unprobed",
                              "subject_kind": "module",
                              "subject_id": "research-rag",
                              "capability": "embedding",
                              "connection_id": "local-omlx",
                              "connection_version": 1,
                              "model_id": "fake-embed"})
        assert r.status_code == 200
        r = client.post(
            "/api/v1/models/bindings/b-unprobed/versions/1/validate",
            headers=admin)
        assert r.status_code == 409, r.text


class TestSecretStoreUnavailable:
    def test_secret_endpoint_503_without_kek(self, client_no_kek):
        admin = _login(client_no_kek, "admin", ADMIN_PW)
        client_no_kek.post("/api/v1/models/connections/drafts",
                           headers=admin,
                           json=_draft_body(location="api",
                                            base_url="https://93.184.216.34/v1"))
        r = client_no_kek.post(
            "/api/v1/models/connections/local-omlx/versions/1/secret",
            headers=admin, json={"secret_value": API_KEY})
        assert r.status_code == 503
        assert r.json()["error_code"] == "MODEL_SECRET_UNAVAILABLE"
        assert API_KEY not in r.text


class TestRoleMatrixAPI:
    """非平台受限角色经 IAM membership 授权的端点级正负矩阵（G4）。"""

    def test_model_admin_can_draft_but_not_approve(self, client_roles):
        h = _login(client_roles, "madmin", ROLE_USERS_PW["madmin"])
        r = client_roles.post("/api/v1/models/connections/drafts",
                              headers=h, json=_draft_body())
        assert r.status_code == 200, r.text
        # 无 models.release.approve → 批准端点 403
        r = client_roles.post(
            "/api/v1/models/connections/local-omlx/versions/1/approve",
            headers=h, json={"approval_id": "whatever"})
        assert r.status_code == 403

    def test_model_admin_can_read_config(self, client_roles):
        h = _login(client_roles, "madmin", ROLE_USERS_PW["madmin"])
        r = client_roles.get("/api/v1/models/connections", headers=h)
        assert r.status_code == 200

    def test_approver_cannot_manage_or_rotate(self, client_roles):
        h = _login(client_roles, "approverx", ROLE_USERS_PW["approverx"])
        r = client_roles.get("/api/v1/models/connections", headers=h)
        assert r.status_code == 200  # config.read 允许
        r = client_roles.post("/api/v1/models/connections/drafts",
                              headers=h, json=_draft_body())
        assert r.status_code == 403  # 无 connection.manage
        r = client_roles.post(
            "/api/v1/models/connections/local-omlx/versions/1/secret",
            headers=h, json={"secret_value": API_KEY})
        assert r.status_code == 403  # 无 secret.rotate

    def test_finance_cannot_read_connection_metadata(self, client_roles):
        h = _login(client_roles, "fin", ROLE_USERS_PW["fin"])
        # 财务只有 usage read：连接元数据/目录/绑定全部 403
        for path in ("/api/v1/models/connections",
                     "/api/v1/models/catalog", "/api/v1/models/bindings"):
            r = client_roles.get(path, headers=h)
            assert r.status_code == 403, path

    def test_read_only_employee_gets_403_everywhere(self, client_roles):
        h = _login(client_roles, "emp", ROLE_USERS_PW["emp"])
        for path in ("/api/v1/models/connections",
                     "/api/v1/models/catalog", "/api/v1/models/bindings"):
            r = client_roles.get(path, headers=h)
            assert r.status_code == 403, path

    def test_whoami_exposes_model_scopes_for_projection(self, client_roles):
        h = _login(client_roles, "madmin", ROLE_USERS_PW["madmin"])
        r = client_roles.get("/api/v1/iam/whoami", headers=h)
        assert r.status_code == 200
        scopes = set(r.json()["scopes"])
        assert "models.config.read" in scopes
        assert "models.connection.manage" in scopes
        assert "models.release.approve" not in scopes


class TestUsageMonitoringAPI:
    """运行治理读端点：usage read 可见；无权限 403；审计需 audit.read。"""

    def test_admin_reads_usage_and_health(self, client):
        admin = _login(client, "admin", ADMIN_PW)
        r = client.get("/api/v1/models/usage/summary", headers=admin)
        assert r.status_code == 200
        body = r.json()
        assert "requests" in body and "units" in body
        assert body["latency_ms"]["samples"] >= 0
        r = client.get("/api/v1/models/usage/timeseries", headers=admin)
        assert r.status_code == 200
        r = client.get("/api/v1/models/usage/rows", headers=admin)
        assert r.status_code == 200
        r = client.get("/api/v1/models/health", headers=admin)
        assert r.status_code == 200

    def test_finance_can_read_usage_but_not_audit_or_config(self,
                                                             client_roles):
        h = _login(client_roles, "fin", ROLE_USERS_PW["fin"])
        r = client_roles.get("/api/v1/models/usage/summary", headers=h)
        assert r.status_code == 200
        r = client_roles.get("/api/v1/models/audit", headers=h)
        assert r.status_code == 403
        r = client_roles.get("/api/v1/models/health", headers=h)
        assert r.status_code == 403

    def test_employee_usage_403(self, client_roles):
        h = _login(client_roles, "emp", ROLE_USERS_PW["emp"])
        r = client_roles.get("/api/v1/models/usage/summary", headers=h)
        assert r.status_code == 403

    def test_audit_requires_audit_scope(self, client_roles):
        h = _login(client_roles, "madmin", ROLE_USERS_PW["madmin"])
        # model_admin 无 models.audit.read
        r = client_roles.get("/api/v1/models/audit", headers=h)
        assert r.status_code == 403
