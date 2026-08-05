"""U4-2 API 测试：审核闭环必须走服务端 session/CSRF；
actor 取登录身份；仲裁仅限 admin；final_box 只来自人工终态。
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

ADMIN_PW = "u42-admin-pw"
OP_PW = "u42-op-pw"


def _fake_probe(spec: ServiceSpec) -> ServiceStatus:
    return ServiceStatus(name=spec.name, status="healthy", latency_ms=1,
                         detail="fake")


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    from tests.platform.test_m5_training_gov import (
        FakeLS, FakeMonitor, FakeRecognition)

    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", ADMIN_PW)
    monkeypatch.setenv(
        "PLATFORM_USERS", f"admin:{ADMIN_PW}:admin,opi:{OP_PW}:operator")
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
    return TestClient(app), bundle


def _login(client: TestClient, username="admin", pw=ADMIN_PW) -> dict:
    r = client.post("/api/v1/auth/login",
                    json={"username": username, "password": pw})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def _seed_queue(bundle, tmp_path: Path, n_double=1, n_blind=1) -> None:
    from src.platform.annotate.review import import_review_queue

    items = [{"photo_id": f"d{i}", "sha256": f"{i:064d}",
              "review_mode": "double_review",
              "requires_second_review": True, "status": "pending"}
             for i in range(n_double)]
    items += [{"photo_id": f"b{i}", "sha256": f"b{i:063d}",
               "review_mode": "blind_review",
               "requires_second_review": False, "status": "pending"}
              for i in range(n_blind)]
    f = tmp_path / "rq.json"
    f.write_text(json.dumps({"queue_version": "rq_v1",
                             "protocol": "diagnostic_v1",
                             "items": items}), encoding="utf-8")
    import_review_queue(bundle.store, f, seed=20260804)


class TestReviewApiGuards:
    def test_claim_without_login_rejected(self, client, tmp_path):
        client, bundle = client
        _seed_queue(bundle, tmp_path)
        token = bundle.store.list_review_tasks()[0]["claim_token"]
        r = client.post("/api/v1/review/claim",
                        json={"claim_token": token})
        assert r.status_code == 401

    def test_submit_forged_header_not_trusted(self, client, tmp_path):
        client, bundle = client
        _seed_queue(bundle, tmp_path)
        t = bundle.store.list_review_tasks()[0]
        r = client.post("/api/v1/review/submit",
                        json={"task_id": t["task_id"],
                              "verdict": "accepted", "box": [1, 2, 3, 4]},
                        headers={"X-Actor": "forged"})
        assert r.status_code == 401

    def test_tasks_without_login_rejected(self, client, tmp_path):
        client, bundle = client
        _seed_queue(bundle, tmp_path)
        assert client.get("/api/v1/review/tasks").status_code == 401

    def test_arbitration_requires_admin(self, client, tmp_path):
        client, bundle = client
        _seed_queue(bundle, tmp_path, n_double=1, n_blind=0)
        t = bundle.store.list_review_tasks()[0]
        h_admin = _login(client)
        client.post("/api/v1/review/claim",
                    json={"claim_token": t["claim_token"]}, headers=h_admin)
        client.post("/api/v1/review/submit",
                    json={"task_id": t["task_id"], "verdict": "accepted",
                          "box": [1, 2, 3, 4]}, headers=h_admin)
        h_op = _login(client, "opi", OP_PW)
        # operator 提交第二审合法
        r = client.post("/api/v1/review/submit",
                        json={"task_id": t["task_id"],
                              "verdict": "accepted", "box": [5, 6, 7, 8]},
                        headers=h_op)
        assert r.status_code == 200, r.text
        # 但 operator 不得仲裁
        r = client.post("/api/v1/review/submit",
                        json={"task_id": t["task_id"],
                              "verdict": "adjudicated",
                              "box": [9, 9, 9, 9], "role": "arbiter"},
                        headers=h_op)
        assert r.status_code == 403


class TestReviewApiFlow:
    def test_blind_flow_finalize_and_status(self, client, tmp_path):
        client, bundle = client
        _seed_queue(bundle, tmp_path, n_double=1, n_blind=1)
        # 未登录可读只读 status
        st = client.get("/api/v1/review/status").json()
        assert st["n_tasks"] == 2
        assert st["status_distribution"].get("pending") == 2

        h = _login(client)
        tasks = client.get("/api/v1/review/tasks").json()["tasks"]
        blind = next(t for t in tasks if t["review_mode"] == "blind_review")
        # 链接认领
        r = client.post("/api/v1/review/claim",
                        json={"claim_token": blind["claim_token"]},
                        headers=h)
        assert r.json()["claimed"] is True
        # 单审即终态
        r = client.post("/api/v1/review/submit",
                        json={"task_id": blind["task_id"],
                              "verdict": "accepted",
                              "box": [1, 2, 3, 4]}, headers=h)
        assert r.json()["finalized"] is True
        fb = client.get(
            f"/api/v1/review/task/{blind['task_id']}/final-box",
            headers=h).json()
        assert fb["final_box"] == [1.0, 2.0, 3.0, 4.0]
        st = client.get("/api/v1/review/status").json()
        assert st["status_distribution"].get("finalized") == 1
        assert st["status_distribution"].get("pending") == 1
        # 管理员不可变导出
        r = client.post("/api/v1/review/export", headers=h)
        body = r.json()
        assert body["n_tasks"] == 2 and body["n_finalized"] == 1
        assert len(body["sha256"]) == 64
        data = json.loads(Path(body["path"]).read_text())
        assert data["n_finalized"] == 1
