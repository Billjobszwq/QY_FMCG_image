"""U2-3 红测试：识别统一（单文件/批量/URL/API 共用 RecognitionTask）。

手册 §4：识别统一支持单文件、批量文件、URL、API 和 Agent；四入口
共用服务层与任务历史。当前平台只有单文件 bridge 且无任务历史，
本测试必须 RED。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service,
                                   build_training_router)
from src.platform.api.app import create_app
from src.platform.api.health import ServiceSpec, ServiceStatus


def _fake_probe(spec: ServiceSpec) -> ServiceStatus:
    return ServiceStatus(name=spec.name, status="healthy", latency_ms=1,
                         detail="fake")


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    from tests.platform.test_m5_training_gov import (
        FakeLS, FakeMonitor, FakeRecognition)

    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "u23-admin-pw")
    fake_rec = FakeRecognition()
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=fake_rec, monitor_adapter=FakeMonitor(),
        label_studio_adapter=FakeLS(), probe=_fake_probe)
    app = create_app(services=(), probe=_fake_probe, bundle=bundle,
                     recognition_adapter=fake_rec,
                     training_router=build_training_router(bundle),
                     profiles_service=build_profiles_service(bundle),
                     web_dist=tmp_path / "none")
    return TestClient(app), bundle


def _login(client: TestClient) -> dict:
    r = client.post("/api/v1/auth/login",
                    json={"username": "admin", "password": "u23-admin-pw"})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


class TestRecognitionTasks:
    def test_single_file_creates_task(self, client, tmp_path):
        client, _ = client
        h = _login(client)
        img = tmp_path / "a.jpg"
        img.write_bytes(b"\xff\xd8fake-jpeg")
        r = client.post("/api/v1/recognition/tasks/upload",
                        files=[("files", ("a.jpg", img.read_bytes(),
                                          "image/jpeg"))], headers=h)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["task"]["entry"] == "single_file"
        assert d["task"]["file_count"] == 1
        assert d["task"]["status"] == "completed"

    def test_batch_files_entry(self, client, tmp_path):
        client, _ = client
        h = _login(client)
        files = [
            ("files", (f"b{i}.jpg", b"\xff\xd8fake", "image/jpeg"))
            for i in range(3)
        ]
        r = client.post("/api/v1/recognition/tasks/upload",
                        files=files, headers=h)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["task"]["entry"] == "batch_file"
        assert d["task"]["file_count"] == 3
        assert len(d["results"]) == 3

    def test_url_entry(self, client, monkeypatch):
        client, _ = client
        h = _login(client)
        import src.platform.api.recognition_tasks as rt
        monkeypatch.setattr(rt, "fetch_url_bytes",
                            lambda url, timeout=10.0: b"\xff\xd8url-bytes")
        r = client.post("/api/v1/recognition/tasks/url",
                        json={"url": "http://example.com/x.jpg"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["task"]["entry"] == "url"

    def test_task_history_lists_all_entries(self, client, tmp_path):
        client, _ = client
        h = _login(client)
        img = tmp_path / "c.jpg"
        img.write_bytes(b"\xff\xd8c")
        client.post("/api/v1/recognition/tasks/upload",
                    files=[("files", ("c.jpg", img.read_bytes(),
                                      "image/jpeg"))], headers=h)
        r = client.get("/api/v1/recognition/tasks")
        assert r.status_code == 200
        d = r.json()
        assert d["count"] >= 1
        assert any(t["entry"] == "single_file" for t in d["tasks"])

    def test_upload_requires_login(self, client):
        client, _ = client
        r = client.post("/api/v1/recognition/tasks/upload",
                        files=[("files", ("d.jpg", b"\xff\xd8d",
                                          "image/jpeg"))])
        assert r.status_code == 401

    def test_shared_service_layer_same_shape_as_bridge(self, client, tmp_path):
        """任务入口与旧 bridge 共用服务层，products/count 口径一致。"""
        client, _ = client
        h = _login(client)
        img = tmp_path / "e.jpg"
        img.write_bytes(b"\xff\xd8e")
        bridge = client.post("/api/v1/recognition/recognize",
                             files={"file": ("e.jpg", img.read_bytes(),
                                             "image/jpeg")})
        assert bridge.status_code == 200, bridge.text
        task = client.post("/api/v1/recognition/tasks/upload",
                           files=[("files", ("e.jpg", img.read_bytes(),
                                             "image/jpeg"))], headers=h)
        b = bridge.json()
        t = task.json()["results"][0]
        assert t["count"] == b["count"]
        assert t["products"] == b["products"]
