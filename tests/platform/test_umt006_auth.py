"""UMT-006 红测试：可信本机登录 session/CSRF/服务端 role。

手册 §3.1 UMT-006 验收口径：伪造 X-Role/X-Actor 头不能授权训练或
批准门；真实 admin session 可用且留审计；禁止客户端 header 自证身份。

当前实现信任 X-Role/X-Actor（training.py `_actor_role`），本测试必须 RED。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import build_production_bundle, build_training_router
from src.platform.api.app import create_app
from src.platform.api.health import ServiceSpec, ServiceStatus

ADMIN_PW = "local-admin-pass-123"


def _fake_probe(spec: ServiceSpec) -> ServiceStatus:
    return ServiceStatus(name=spec.name, status="healthy", latency_ms=1,
                         detail="fake")


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    from tests.platform.test_m5_training_gov import (
        FakeLS, FakeMonitor, FakeRecognition)

    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", ADMIN_PW)
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=FakeRecognition(), monitor_adapter=FakeMonitor(),
        label_studio_adapter=FakeLS(), probe=_fake_probe)
    app = create_app(services=(), probe=_fake_probe, bundle=bundle,
                     training_router=build_training_router(bundle),
                     web_dist=tmp_path / "none")
    return TestClient(app)


def _login(client: TestClient) -> str:
    r = client.post("/api/v1/auth/login",
                    json={"username": "admin", "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    return r.json()["csrf_token"]


class TestForgedHeadersRejected:
    def test_forged_x_role_cannot_authorize_training(self, client):
        """伪造 X-Role: admin 不得授权训练（UMT-006）。"""
        r = client.post("/api/v1/training/authorize", json={"value": True},
                        headers={"X-Role": "admin", "X-Actor": "mallory"})
        assert r.status_code == 401
        assert client.get("/api/v1/training/gates").json()[
            "training_authorized"] is False

    def test_forged_x_actor_not_recorded_in_audit(self, client):
        csrf = _login(client)
        r = client.post("/api/v1/training/authorize", json={"value": True},
                        headers={"X-CSRF-Token": csrf,
                                 "X-Actor": "mallory", "X-Role": "admin"})
        assert r.status_code == 200
        # 审计主体必须来自服务端 session，而非客户端 header
        assert r.json()["actor"] == "admin"


class TestLoginSession:
    def test_login_wrong_password_rejected(self, client):
        r = client.post("/api/v1/auth/login",
                        json={"username": "admin", "password": "wrong"})
        assert r.status_code == 401
        assert "platform_session" not in client.cookies

    def test_login_success_and_me(self, client):
        csrf = _login(client)
        assert csrf
        me = client.get("/api/v1/auth/me").json()
        assert me["actor"] == "admin" and me["role"] == "admin"

    def test_mutating_without_csrf_rejected(self, client):
        _login(client)
        r = client.post("/api/v1/training/authorize", json={"value": True})
        assert r.status_code == 403

    def test_session_authorize_then_logout_blocks(self, client):
        csrf = _login(client)
        r = client.post("/api/v1/training/authorize", json={"value": True},
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        client.post("/api/v1/auth/logout")
        me = client.get("/api/v1/auth/me")
        assert me.status_code == 401
