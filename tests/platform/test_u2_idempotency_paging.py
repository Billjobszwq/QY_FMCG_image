"""U2-5 红测试：写操作幂等键 + 列表分页筛选（UMT-109）。

手册 §3.1 UMT-109 验收口径：
- 写操作要求 idempotency_key，重复请求返回同一任务（不重复创建）；
- 列表支持分页和按状态/时间/数据集筛选。

当前实现：识别任务端点无幂等键、列表只有 limit 无分页/筛选；
workitems 无分页筛选；重复 enqueue 直接 403 而非返回同一 Job。
本测试必须 RED。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import build_production_bundle, build_training_router
from src.platform.api.app import create_app
from src.platform.api.health import ServiceSpec, ServiceStatus


def _fake_probe(spec: ServiceSpec) -> ServiceStatus:
    return ServiceStatus(name=spec.name, status="healthy", latency_ms=1,
                         detail="fake")


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    from tests.platform.test_m5_training_gov import (
        FakeLS, FakeMonitor, FakeRecognition)

    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "u25-admin-pw")
    fake_rec = FakeRecognition()
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=fake_rec, monitor_adapter=FakeMonitor(),
        label_studio_adapter=FakeLS(), probe=_fake_probe)
    app = create_app(services=(), probe=_fake_probe, bundle=bundle,
                     recognition_adapter=fake_rec,
                     training_router=build_training_router(bundle),
                     web_dist=tmp_path / "none")
    return TestClient(app), bundle


def _login(client: TestClient) -> dict:
    r = client.post("/api/v1/auth/login",
                    json={"username": "admin", "password": "u25-admin-pw"})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def _upload(client: TestClient, h: dict, name: str = "a.jpg",
            idem: str | None = None) -> TestClient:
    headers = dict(h)
    if idem is not None:
        headers["Idempotency-Key"] = idem
    return client.post(
        "/api/v1/recognition/tasks/upload",
        files=[("files", (name, b"\xff\xd8fake-jpeg", "image/jpeg"))],
        headers=headers)


class TestRecognitionIdempotency:
    def test_upload_repeat_with_same_key_returns_same_task(self, client):
        """同一 Idempotency-Key 重复上传：返回同一任务，不新建。"""
        client, _ = client
        h = _login(client)
        r1 = _upload(client, h, idem="k-upload-1")
        r2 = _upload(client, h, idem="k-upload-1")
        assert r1.status_code == 200 and r2.status_code == 200, r2.text
        assert r1.json()["task"]["task_id"] == r2.json()["task"]["task_id"]
        lst = client.get("/api/v1/recognition/tasks").json()
        assert lst["count"] == 1, "重复请求不得创建第二个任务"

    def test_url_repeat_with_same_key_returns_same_task(self, client,
                                                        monkeypatch):
        client, _ = client
        h = _login(client)
        import src.platform.api.recognition_tasks as rt
        monkeypatch.setattr(rt, "fetch_url_bytes",
                            lambda url, timeout=10.0: b"\xff\xd8fake")
        body = {"url": "http://x/a.jpg"}
        h1 = {**h, "Idempotency-Key": "k-url-1"}
        r1 = client.post("/api/v1/recognition/tasks/url", json=body,
                         headers=h1)
        r2 = client.post("/api/v1/recognition/tasks/url", json=body,
                         headers=h1)
        assert r1.status_code == 200 and r2.status_code == 200, r2.text
        assert r1.json()["task"]["task_id"] == r2.json()["task"]["task_id"]
        lst = client.get("/api/v1/recognition/tasks").json()
        assert lst["count"] == 1

    def test_different_keys_create_distinct_tasks(self, client):
        client, _ = client
        h = _login(client)
        r1 = _upload(client, h, idem="k-a")
        r2 = _upload(client, h, idem="k-b")
        assert r1.json()["task"]["task_id"] != r2.json()["task"]["task_id"]


class TestRecognitionListPaging:
    def _seed(self, client, h):
        # 2 个 completed（正常图）+ 1 个 failed（空文件）
        _upload(client, h, name="a.jpg", idem="s1")
        _upload(client, h, name="b.jpg", idem="s2")
        client.post("/api/v1/recognition/tasks/upload",
                    files=[("files", ("empty.jpg", b"", "image/jpeg"))],
                    headers={**h, "Idempotency-Key": "s3"})

    def test_paging_limit_offset(self, client):
        client, _ = client
        h = _login(client)
        self._seed(client, h)
        p1 = client.get("/api/v1/recognition/tasks?limit=2&offset=0").json()
        p2 = client.get("/api/v1/recognition/tasks?limit=2&offset=2").json()
        assert len(p1["tasks"]) == 2 and len(p2["tasks"]) == 1
        assert p1["count"] == 3, "count 必须返回全量总数"
        ids1 = {t["task_id"] for t in p1["tasks"]}
        ids2 = {t["task_id"] for t in p2["tasks"]}
        assert not (ids1 & ids2), "分页之间不得重叠"

    def test_filter_by_status(self, client):
        client, _ = client
        h = _login(client)
        self._seed(client, h)
        d = client.get("/api/v1/recognition/tasks?status=failed").json()
        assert d["count"] == 1
        assert d["tasks"][0]["status"] == "failed"
        d2 = client.get("/api/v1/recognition/tasks?status=completed").json()
        assert d2["count"] == 2


class TestWorkItemsPaging:
    def test_workitems_paging_and_kind_filter(self, client, tmp_path,
                                              monkeypatch):
        client, bundle = client
        rq = tmp_path / "rq.json"
        rq.write_text(json.dumps({
            "protocol": "diagnostic_v1",
            "items": [{"photo_id": f"p{i}", "status": "pending"}
                      for i in range(5)]}, ensure_ascii=False),
            encoding="utf-8")
        monkeypatch.setenv("PLATFORM_REVIEW_QUEUE", str(rq))
        full = client.get("/api/v1/workitems").json()
        assert full["count"] >= 5
        p1 = client.get("/api/v1/workitems?limit=2&offset=0").json()
        assert len(p1["items"]) == 2 and p1["count"] == full["count"]
        p2 = client.get("/api/v1/workitems?limit=2&offset=2").json()
        assert len(p2["items"]) == 2
        ids1 = {w["id"] for w in p1["items"]}
        ids2 = {w["id"] for w in p2["items"]}
        assert not (ids1 & ids2)
        only = client.get("/api/v1/workitems?kind=human_review").json()
        assert only["count"] == 5
        assert all(w["kind"] == "human_review" for w in only["items"])


class TestEnqueueIdempotency:
    def test_repeat_enqueue_returns_same_job(self, tmp_path):
        """重复提交同一已批准计划：返回同一 Job，不得重复入队。"""
        from src.modules.training_gov.service import TrainingGovernanceService
        from src.platform.data.store import PlatformStore
        from tests.platform.test_umt007_job_semantics import (
            FakeWorker, MANIFEST_OK)

        s = PlatformStore(tmp_path / "p.sqlite")
        try:
            svc = TrainingGovernanceService(s)
            snap = svc.register_snapshot(
                "e2", "v1", "product", MANIFEST_OK,
                source_actor="a", source_conclusion="ok")
            run = svc.dry_run(snap["snapshot_id"], actor="op")
            worker = FakeWorker()
            svc.set_training_authorized(True, actor="adm", role="admin")
            svc.approve_plan(run["run_id"], actor="adm", role="admin",
                             worker=worker)
            out1 = svc.enqueue_training_job(
                run["run_id"], actor="adm", role="admin", worker=worker)
            out2 = svc.enqueue_training_job(
                run["run_id"], actor="adm", role="admin", worker=worker)
            assert out1["job_id"] == out2["job_id"]
            assert len(worker.submitted) == 1, "重复请求不得再次提交 Job"
        finally:
            s.close()
