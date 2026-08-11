"""ABOSV2-P1-005 红测试：识别任务统一详情。

现场复现：识别任务页文案称“按 trace_id 可查证据”，但无 task_id/
trace/tier/错误/证据/用量入口，无可点击行。

要求（v2 审计 P1-005 / 04-UI-UX §4 统一任务详情）：
1. GET /api/v1/recognition/tasks/{task_id} 返回统一详情：
   task/work/run/trace、tier/profile、输入输出、错误、证据、usage、
   父子任务、下一动作；
2. 尚未接入的统一 Work/Run/Evidence/Usage 必须诚实标注（不得伪造
   数字），但字段结构必须存在，供 Phase B 贯通告警；
3. 失败任务必须显示错误与恢复动作。
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

    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "v2-admin-pw")
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
                    json={"username": "admin", "password": "v2-admin-pw"})
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def _upload(client: TestClient, h: dict,
            payload: bytes = b"\xff\xd8fake-jpeg") -> dict:
    r = client.post("/api/v1/recognition/tasks/upload",
                    files=[("files", ("a.jpg", payload, "image/jpeg"))],
                    headers=h)
    assert r.status_code == 200, r.text
    return r.json()


class TestRecognitionTaskDetail:
    def test_detail_endpoint_full_structure(self, client):
        client, _ = client
        h = _login(client)
        view = _upload(client, h)
        task_id = view["task"]["task_id"]
        r = client.get(f"/api/v1/recognition/tasks/{task_id}")
        assert r.status_code == 200, r.text
        d = r.json()
        # 统一详情壳：所有区块必须存在（缺失即断链）
        for key in ("task", "contract", "inputs", "outputs", "errors",
                    "timeline", "usage", "evidence", "relations",
                    "next_actions"):
            assert key in d, f"详情缺少区块 {key}"
        assert d["task"]["task_id"] == task_id
        c = d["contract"]
        assert c["recognition_profile_id"] == view["task"][
            "recognition_profile_id"]
        assert c["trace_id"] == view["task"]["trace_id"]
        assert c["service_tier"] and c["source"]
        assert isinstance(d["outputs"]["results"], list)
        assert d["timeline"], "时间线必须至少含创建/完成事件"

    def test_detail_unknown_task_404(self, client):
        client, _ = client
        r = client.get("/api/v1/recognition/tasks/does-not-exist")
        assert r.status_code == 404

    def test_failed_task_shows_error_and_recovery(self, client):
        client, _ = client
        h = _login(client)
        view = _upload(client, h, payload=b"")  # 空文件 → 错误
        task_id = view["task"]["task_id"]
        d = client.get(f"/api/v1/recognition/tasks/{task_id}").json()
        assert d["task"]["status"] == "failed"
        assert d["errors"], "失败任务必须显示错误明细"
        assert any("重试" in a or "retry" in a.lower()
                   for a in d["next_actions"]), "必须给出恢复动作"

    def test_unwired_sections_are_honest_not_faked(self, client):
        """统一 run/usage/证据未接入前必须诚实标注，不得伪造数字。"""
        client, _ = client
        h = _login(client)
        view = _upload(client, h)
        d = client.get(
            f"/api/v1/recognition/tasks/{view['task']['task_id']}").json()
        rel = d["relations"]
        assert "work_id" in rel and "run_id" in rel
        assert "note" in rel, "未接入区块必须说明原因，不得静默为空"
        assert "note" in d["usage"]
