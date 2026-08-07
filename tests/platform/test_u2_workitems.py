"""U2-1 红测试：统一 WorkItem API + 角色首页数据。

手册 §4：首页必须显示我的待办、活动任务、阻断原因、下一步、负责人
和系统异常；默认业务语言。聚合真实来源：人工审核队列
（.review_queue/review_queue_diag_v1.json，250 条 pending 必须真实
接入）、训练 run、Job、标注批次与系统健康。

当前平台无 /api/v1/workitems 端点，本测试必须 RED。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (
    build_jobs_router, build_production_bundle, build_training_router)
from src.platform.api.app import create_app
from src.platform.api.health import ServiceSpec, ServiceStatus


def _fake_probe(spec: ServiceSpec) -> ServiceStatus:
    return ServiceStatus(name=spec.name, status="healthy", latency_ms=1,
                         detail="fake")


def _make_review_queue(tmp_path: Path, n_pending: int = 3) -> Path:
    rq = tmp_path / "review_queue" / "review_queue_diag_v1.json"
    rq.parent.mkdir(parents=True, exist_ok=True)
    items = [
        {"photo_id": f"p{i:03d}", "image": f"img_{i}.jpg",
         "status": "pending", "review_mode": "double" if i < 2 else "blind",
         "priority": 10 - i}
        for i in range(n_pending)
    ]
    rq.write_text(json.dumps(
        {"queue_version": "rq_v1", "protocol": "diagnostic_v1",
         "status": "open", "items": items}, ensure_ascii=False),
        encoding="utf-8")
    return rq


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    from tests.platform.test_m5_training_gov import (
        FakeLS, FakeMonitor, FakeRecognition)

    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "u2-admin-pw")
    rq = _make_review_queue(tmp_path)
    monkeypatch.setenv("PLATFORM_REVIEW_QUEUE", str(rq))
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
    # 运行状态唯一事实源 = DB：真实种子 3 条 pending 审核任务
    # （JSON env 仍在，但不得再作为运行状态来源）
    for i in range(3):
        bundle.store.add_review_task(
            task_id=f"rt_u2_p{i:03d}", claim_token=f"tok_u2_p{i:03d}",
            photo_id=f"p{i:03d}", sha256=f"sha_u2_{i:03d}",
            review_mode=("double_review" if i < 2 else "blind_manual"),
            requires_second_review=True,
            queue_version="rq_v1", protocol="diagnostic_v1")
    return TestClient(app), bundle


class TestWorkItemsAPI:
    def test_endpoint_exists_and_aggregates_real_sources(self, client):
        """真实审核队列 pending 必须出现，不得伪造完成。"""
        client, _ = client
        r = client.get("/api/v1/workitems")
        assert r.status_code == 200, r.text
        d = r.json()
        kinds = {w["kind"] for w in d["items"]}
        assert "human_review" in kinds
        reviews = [w for w in d["items"] if w["kind"] == "human_review"]
        assert len(reviews) == 3
        assert all(w["status"] == "pending" for w in reviews)

    def test_summary_counts_business_language(self, client):
        """summary 使用业务语言计数：待办/活动/阻断。"""
        client, _ = client
        d = client.get("/api/v1/workitems").json()
        s = d["summary"]
        assert s["pending_review"] == 3
        assert "todos" in s and "blocked" in s
        assert isinstance(s["next_steps"], list) and s["next_steps"]

    def test_blocked_reason_reflects_training_authorization(self, client):
        """training_authorized=false 必须作为阻断原因出现。"""
        client, _ = client
        d = client.get("/api/v1/workitems").json()
        blocked = " ".join(d["summary"]["blocked"])
        assert "授权" in blocked

    def test_training_run_appears_as_workitem(self, client, tmp_path):
        """dry-run 产生的训练计划进入任务中心（需登录创建）。"""
        client, _ = client
        # 登录 admin
        r = client.post("/api/v1/auth/login",
                        json={"username": "admin", "password": "u2-admin-pw"})
        csrf = r.json()["csrf_token"]
        h = {"X-CSRF-Token": csrf}
        # 经 builder 注册一个真实快照（最小可训练集）
        root = tmp_path / "photos"
        root.mkdir()
        entries = []
        for i, (split, store) in enumerate(
                [("train", "门店A"), ("train", "门店A"), ("val", "门店B")]):
            img = root / f"photo_{i}.jpg"
            import random
            from PIL import Image
            rnd = random.Random(1000 + i)
            im = Image.new("RGB", (32, 32))
            im.putdata(
                [(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
                 for _ in range(32 * 32)])
            im.save(img)
            lab = root / f"photo_{i}.txt"
            lab.write_text("0 0.5 0.5 0.2 0.2\n")
            entries.append({
                "path": str(img), "label_path": str(lab),
                "photo_id": f"ph{i:03d}", "store": store,
                "session": f"{store}@s1", "split": split,
                "review_status": "human_final", "quality_status": "accepted"})
        r = client.post("/api/v1/training/snapshots/build",
                        json={"name": "u2_pilot", "version": "v1",
                              "entries": entries}, headers=h)
        assert r.status_code == 200, r.text
        snap_id = r.json()["snapshot"]["snapshot_id"]
        r = client.post("/api/v1/training/runs/dry-run",
                        json={"snapshot_id": snap_id}, headers=h)
        assert r.status_code == 200, r.text
        d = client.get("/api/v1/workitems").json()
        kinds = {w["kind"] for w in d["items"]}
        assert "training" in kinds

    def test_failed_job_surfaces_as_anomaly(self, client):
        """failed job 进入系统异常（阻断）列表。"""
        client, bundle = client
        r = client.post("/api/v1/auth/login",
                        json={"username": "admin", "password": "u2-admin-pw"})
        csrf = r.json()["csrf_token"]
        r = client.post("/api/v1/jobs",
                        json={"kind": "platform.echo", "payload": {"x": 1}},
                        headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200, r.text
        job_id = r.json()["job"]["job_id"]
        # 模拟失败（store 层状态机已由 M6 测试覆盖）
        bundle.store.set_job_status(job_id, "failed", error="boom")
        d = client.get("/api/v1/workitems").json()
        assert any("失败" in b for b in d["summary"]["blocked"])
        assert any(w["kind"] == "job" and w["status"] == "failed"
                   for w in d["items"])
