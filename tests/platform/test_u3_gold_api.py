"""U3-6 API 红测试：金标准入口必须走服务端 session/CSRF，
reviewer 取登录身份；人工未完成只能 waiting_human。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (
    build_jobs_router, build_production_bundle, build_training_router)
from src.platform.api.app import create_app
from src.platform.api.health import ServiceSpec, ServiceStatus

ADMIN_PW = "u36-admin-pw"


def _fake_probe(spec: ServiceSpec) -> ServiceStatus:
    return ServiceStatus(name=spec.name, status="healthy", latency_ms=1,
                         detail="fake")


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    from tests.platform.test_m5_training_gov import (
        FakeLS, FakeMonitor, FakeRecognition)

    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", ADMIN_PW)
    monkeypatch.setenv("PLATFORM_DATASETS_ROOT", str(tmp_path / ".datasets"))
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=FakeRecognition(), monitor_adapter=FakeMonitor(),
        label_studio_adapter=FakeLS(), probe=_fake_probe)
    _worker, jobs_router = build_jobs_router(bundle)
    app = create_app(services=(), probe=_fake_probe, bundle=bundle,
                     training_router=build_training_router(bundle, _worker),
                     jobs_router=jobs_router,
                     web_dist=tmp_path / "none")
    # 一条指向仓库内真实文件的 directory 台账行（可入本地金标准）
    bundle.store.register_inventory_asset(
        source_id="photoQ", source_type="directory",
        source_uri="conftest.py", photo_id="conftest.py",
        sha256="d" * 64)
    return TestClient(app), bundle


def _login(client: TestClient) -> dict:
    r = client.post("/api/v1/auth/login",
                    json={"username": "admin", "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


class TestGoldApiGuards:
    def test_build_without_login_rejected(self, client):
        client, _ = client
        r = client.post("/api/v1/quality/gold/build", json={"size": 5})
        assert r.status_code == 401

    def test_verdict_without_login_rejected(self, client):
        client, _ = client
        r = client.post("/api/v1/quality/gold/verdict",
                        json={"sha256": "d" * 64, "verdict": "pass"})
        assert r.status_code == 401

    def test_verdict_forged_header_not_trusted(self, client):
        client, bundle = client
        r = client.post("/api/v1/quality/gold/verdict",
                        json={"sha256": "d" * 64, "verdict": "pass"},
                        headers={"X-Actor": "forged"})
        assert r.status_code == 401


class TestGoldApiFlow:
    def test_build_status_verdict_confusion(self, client):
        client, bundle = client
        h = _login(client)
        # 建队：只有本地真实文件入队
        r = client.post("/api/v1/quality/gold/build", json={"size": 5},
                        headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["added"] == 1
        # 状态：人工未完成必须 waiting_human
        st = client.get("/api/v1/quality/gold/status").json()
        assert st["waiting_human"] == 1 and st["done"] == 0
        assert st["items"][0]["status"] == "waiting_human"
        # 人工结论：reviewer 强制取服务端 session 身份
        r = client.post("/api/v1/quality/gold/verdict",
                        json={"sha256": "d" * 64, "verdict": "fail"},
                        headers=h)
        assert r.status_code == 200, r.text
        v = bundle.store.find_human_verdict("d" * 64)
        assert v is not None and v["reviewer"] == "admin"
        st = client.get("/api/v1/quality/gold/status").json()
        assert st["done"] == 1 and st["waiting_human"] == 0
        m = client.get("/api/v1/quality/gold/confusion").json()
        assert m["pairs"] == 1

    def test_verdict_invalid_value_rejected(self, client):
        client, _ = client
        h = _login(client)
        client.post("/api/v1/quality/gold/build", json={"size": 5},
                    headers=h)
        r = client.post("/api/v1/quality/gold/verdict",
                        json={"sha256": "d" * 64, "verdict": "maybe"},
                        headers=h)
        assert r.status_code == 422
