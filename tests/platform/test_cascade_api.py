"""Task 14（VLM-014）：统一 cascade API（shadow 默认，7 端点）。

覆盖：
- 单文件/批量/URL/API/内部 Agent 共用同一 RecognitionTask（entry 区分）；
- 未登录拒绝一切 cascade 端点（401）；写端点需 CSRF；
- URL SSRF 防护（file://、内网/localhost 拒绝）；
- 任意 file path / model / prompt / graph 定义字段拒绝（422）；
- idempotency 生效（重放返回同一任务）；
- regions/trail/cancel；GET /api/v1/models/runtime；
- 旧 /api/v1/recognition/recognize 与 8091 口径不变（shadow 默认）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.platform.api.app import create_app
from src.platform.api.cascade import create_cascade_router
from src.platform.auth import AuthService, create_auth_router
from src.platform.data.store import PlatformStore

ADMIN_PW = "local-admin-pass-123"
ASSET = {"asset_id": "asset-1", "sha256": "a" * 64,
         "image_width": 640, "image_height": 480}


class FakeRecognition:
    def recognize(self, data: bytes, *, conf: float = 0.25) -> dict:
        return {"products": [], "count": 0}


class FakeMonitor:
    def live(self) -> dict:
        return {"ok": True}

    def overview(self) -> dict:
        return {"ok": True}


class FakeResidency:
    def models(self) -> list[dict[str, Any]]:
        return [{"model_id": "qwen3-vl:4b", "residency": "cold",
                 "state": "cold"}]


class FakeCascadeService:
    """fake CascadeService：同接口（submit/result/trail/billing），零真实模型。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def submit(self, asset_ref, *, tier, idempotency_key=None,
               queue_deadline_at=None) -> dict:
        self.calls.append({"asset": asset_ref, "tier": tier,
                           "idempotency_key": idempotency_key})
        return {"run_id": f"run-{len(self.calls)}", "status": "completed"}

    def result(self, run_id: str) -> dict:
        return {"decision": "accepted", "sku_id": "sku-001"}

    def trail(self, run_id: str) -> list[dict]:
        return [{"node": "quality", "decision": "pass"}]

    def billing(self, run_id: str) -> list[dict]:
        return []


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", ADMIN_PW)
    store = PlatformStore(tmp_path / "p.sqlite")
    auth = AuthService(store)
    svc = FakeCascadeService()
    router = create_cascade_router(
        store, svc, auth=auth, residency=FakeResidency())
    app = create_app(
        services=[], probe=lambda s: None,
        recognition_adapter=FakeRecognition(),
        monitor_adapter=FakeMonitor(),
        bundle=None, cascade_router=router)
    app.include_router(create_auth_router(auth))  # 登录端点（测试环境）
    client = TestClient(app)
    yield {"client": client, "store": store, "svc": svc}
    store.close()


def _login(client: TestClient) -> str:
    r = client.post("/api/v1/auth/login",
                    json={"username": "admin", "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    return r.json()["csrf_token"]


# ---------- 未登录拒绝 ----------

def test_unauthenticated_rejected(env) -> None:
    c = env["client"]
    assert c.post("/api/v1/cascade/tasks",
                  json={"tier": "fast", "source": "api", "asset": ASSET}
                  ).status_code == 401
    assert c.get("/api/v1/cascade/tasks").status_code == 401
    assert c.get("/api/v1/cascade/tasks/x").status_code == 401
    assert c.get("/api/v1/cascade/tasks/x/regions").status_code == 401
    assert c.get("/api/v1/cascade/tasks/x/trail").status_code == 401
    assert c.post("/api/v1/cascade/tasks/x/cancel").status_code == 401
    assert c.get("/api/v1/models/runtime").status_code == 401


# ---------- 提交：tier/source/asset → RecognitionTask ----------

def test_submit_creates_recognition_task(env) -> None:
    c = env["client"]
    csrf = _login(c)
    r = c.post("/api/v1/cascade/tasks",
               json={"tier": "standard", "source": "api", "asset": ASSET},
               headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_id"] == "run-1"
    task = body["task"]
    assert task["entry"].startswith("cascade_api")
    assert env["svc"].calls[0]["tier"] == "standard"
    # 同一 RecognitionTask 台账（与单文件/批量/URL/Agent 共用）
    rows = env["store"].list_recognition_tasks()
    assert len(rows) == 1 and rows[0]["task_id"] == task["task_id"]


def test_submit_sources_share_same_task_table(env) -> None:
    """api 与 agent 内部入口共用同一 RecognitionTask（entry 区分）。"""
    c = env["client"]
    csrf = _login(c)
    for source in ("api", "agent"):
        r = c.post("/api/v1/cascade/tasks",
                   json={"tier": "fast", "source": source, "asset": ASSET},
                   headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        assert r.json()["task"]["entry"] == f"cascade_{source}"
    assert len(env["store"].list_recognition_tasks()) == 2


def test_invalid_tier_or_source_rejected(env) -> None:
    c = env["client"]
    csrf = _login(c)
    r = c.post("/api/v1/cascade/tasks",
               json={"tier": "vip", "source": "api", "asset": ASSET},
               headers={"X-CSRF-Token": csrf})
    assert r.status_code == 400
    r = c.post("/api/v1/cascade/tasks",
               json={"tier": "fast", "source": "ftp", "asset": ASSET},
               headers={"X-CSRF-Token": csrf})
    assert r.status_code == 400
    assert env["svc"].calls == []


# ---------- 安全：拒绝任意 file path / model / prompt / graph ----------

@pytest.mark.parametrize("extra", [
    {"file_path": "/etc/passwd"},
    {"model": "qwen3-vl:4b"},
    {"prompt": "请识别这张图"},
    {"graph": {"entry": "quality", "edges": []}},
])
def test_forbidden_fields_rejected(env, extra) -> None:
    c = env["client"]
    csrf = _login(c)
    body = {"tier": "fast", "source": "api", "asset": ASSET, **extra}
    r = c.post("/api/v1/cascade/tasks", json=body,
               headers={"X-CSRF-Token": csrf})
    assert r.status_code == 422, r.text
    assert env["svc"].calls == []


# ---------- URL 入口：SSRF 防护沿用现有规则 ----------

def test_url_ssrf_rejected(env) -> None:
    c = env["client"]
    csrf = _login(c)
    for bad in ("file:///etc/passwd", "http://127.0.0.1/x.jpg",
                "http://localhost/x.jpg", "http://192.168.1.10/x.jpg",
                "http://169.254.169.254/latest/meta-data"):
        r = c.post("/api/v1/cascade/tasks",
                   json={"tier": "fast", "source": "url", "url": bad},
                   headers={"X-CSRF-Token": csrf})
        assert r.status_code == 400, f"{bad} -> {r.status_code}"
    assert env["svc"].calls == []


# ---------- idempotency ----------

def test_idempotent_replay(env) -> None:
    c = env["client"]
    csrf = _login(c)
    body = {"tier": "fast", "source": "api", "asset": ASSET}
    h = {"X-CSRF-Token": csrf, "Idempotency-Key": "k-1"}
    r1 = c.post("/api/v1/cascade/tasks", json=body, headers=h)
    r2 = c.post("/api/v1/cascade/tasks", json=body, headers=h)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["task"]["task_id"] == r2.json()["task"]["task_id"]
    assert r2.json().get("idempotent_replay") is True
    assert len(env["svc"].calls) == 1  # 不重复执行级联


# ---------- 详情 / regions / trail / cancel ----------

def _submit(env, csrf) -> str:
    r = env["client"].post(
        "/api/v1/cascade/tasks",
        json={"tier": "fast", "source": "api", "asset": ASSET},
        headers={"X-CSRF-Token": csrf})
    return r.json()["task"]["task_id"]


def test_detail_and_trail(env) -> None:
    c = env["client"]
    csrf = _login(c)
    tid = _submit(env, csrf)
    d = c.get(f"/api/v1/cascade/tasks/{tid}")
    assert d.status_code == 200
    assert d.json()["result"]["sku_id"] == "sku-001"
    t = c.get(f"/api/v1/cascade/tasks/{tid}/trail")
    assert t.status_code == 200
    assert t.json()["trail"][0]["node"] == "quality"
    r = c.get(f"/api/v1/cascade/tasks/{tid}/regions")
    assert r.status_code == 200
    assert "regions" in r.json()


def test_detail_missing_404(env) -> None:
    c = env["client"]
    _login(c)
    assert c.get("/api/v1/cascade/tasks/nope").status_code == 404
    assert c.get("/api/v1/cascade/tasks/nope/trail").status_code == 404


def test_cancel_writes_audit(env) -> None:
    c = env["client"]
    csrf = _login(c)
    tid = _submit(env, csrf)
    r = c.post(f"/api/v1/cascade/tasks/{tid}/cancel",
               headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"
    audit = [a for a in env["store"].list_audit(subject_id=tid)
             if a["action"] == "cascade.task_cancelled"]
    assert len(audit) == 1


def test_cancel_without_csrf_rejected(env) -> None:
    c = env["client"]
    csrf = _login(c)
    tid = _submit(env, csrf)
    assert c.post(f"/api/v1/cascade/tasks/{tid}/cancel").status_code == 403


# ---------- models/runtime ----------

def test_models_runtime(env) -> None:
    c = env["client"]
    _login(c)
    r = c.get("/api/v1/models/runtime")
    assert r.status_code == 200
    models = r.json()["models"]
    assert models[0]["model_id"] == "qwen3-vl:4b"
    assert models[0]["residency"] == "cold"


# ---------- 旧 API 不变（shadow 默认） ----------

def test_legacy_recognize_unchanged(env) -> None:
    c = env["client"]
    r = c.post("/api/v1/recognition/recognize",
               files={"file": ("a.jpg", b"fake-jpeg-bytes")})
    assert r.status_code == 200
    body = r.json()
    assert body["capability"] and "products" in body
    assert env["svc"].calls == []  # 旧入口不触发新级联
