"""Task 16（VLM-016）：统一 Web 管理界面 API/UI 合约测试。

合约分两层：
1. 静态 UI 合约——三个新页面必须使用业务语言（客户档位、当前阶段、
   为何升级、自动/待人工、剩余 SLA、成本、证据），技术字段（模型哈希、
   策略版本、risk、token）折叠显示；App.tsx/api.ts 必须挂载新路由与函数。
2. API 行为合约——cascade 端点保持 shadow 默认；models/runtime 空时
   诚实返回 count=0；packaging 裁决端点只允许人工终结、
   非终态校验 fail-closed、supersede 只追加。
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.modules.fmcg.cascade import packaging as pkg
from src.platform.auth import AuthService, create_auth_router
from src.platform.api.cascade import create_cascade_router
from src.platform.data.store import PlatformStore

WEB = Path(__file__).resolve().parents[2] / "web" / "src"
ADMIN_PW = "web-contract-pw"


# ---------------- fakes ----------------


class FakeCascadeService:
    def submit(self, asset, *, tier, idempotency_key=None):
        return {"run_id": "run-web-1", "status": "running"}

    def result(self, run_id):
        return {"decision": "accepted", "products": []}

    def trail(self, run_id):
        return [{"round": 1, "node": "risk_s1", "decision": "next",
                 "reason": "低风险直出", "detail": {"policy_version": "v1"}}]

    def billing(self, run_id):
        return [{"capability": "cap.detect.yolo11", "billed_cost": 2.0}]

    def sla_hours(self, tier):
        return 12.0 if tier in ("fast", "standard") else 48.0


class FakeResidency:
    def models(self):
        return []


class FakePackaging:
    """组合根注入形态：把域模块函数绑定到 store 上（不含平台反向 import）。"""

    def __init__(self, store):
        self.list_decisions = functools.partial(pkg.list_decisions, store)
        self.get_decision = functools.partial(pkg.get_decision, store)
        self.create_candidate = functools.partial(pkg.create_candidate, store)
        self.finalize_decision = functools.partial(pkg.finalize_decision, store)
        self.supersede = functools.partial(pkg.supersede, store)
        self.supersede_history = functools.partial(
            pkg.supersede_history, store)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", ADMIN_PW)
    store = PlatformStore(tmp_path / "p.sqlite")
    auth = AuthService(store)
    service = FakeCascadeService()
    router = create_cascade_router(
        store, service, auth=auth, residency=FakeResidency(),
        packaging=FakePackaging(store))
    app = FastAPI()
    app.include_router(create_auth_router(auth))
    app.include_router(router)
    return TestClient(app), store


def _login(c: TestClient) -> str:
    r = c.post("/api/v1/auth/login",
               json={"username": "admin", "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    return r.json()["csrf_token"]


# ---------------- 静态 UI 合约 ----------------


def _read(rel: str) -> str:
    p = WEB / rel
    assert p.exists(), f"缺少页面文件 {p}"
    return p.read_text(encoding="utf-8")


def test_cascade_tasks_page_business_language():
    src = _read("pages/CascadeTasks.tsx")
    for word in ("客户档位", "当前阶段", "为何升级", "待人工",
                 "剩余 SLA", "成本", "证据"):
        assert word in src, f"CascadeTasks 缺少业务语言：{word}"
    # 技术字段必须折叠显示
    assert "<details" in src, "技术字段必须用折叠（details）显示"
    for tech in ("模型哈希", "策略版本", "risk", "token"):
        assert tech in src, f"CascadeTasks 缺少折叠技术字段：{tech}"


def test_model_runtime_page_business_language():
    src = _read("pages/ModelRuntime.tsx")
    for word in ("hot", "warm", "cold", "队列", "内存", "冷启动", "错误"):
        assert word in src, f"ModelRuntime 缺少：{word}"


def test_new_packaging_page_business_language():
    src = _read("pages/NewPackaging.tsx")
    for word in ("候选", "沿用旧名", "采用新名", "新 SKU"):
        assert word in src, f"NewPackaging 缺少：{word}"


def test_app_routes_and_nav():
    src = _read("App.tsx")
    for route in ("/cascade", "/models-runtime", "/packaging"):
        assert f'"{route}"' in src, f"App.tsx 缺少路由 {route}"
    for label in ("级联任务", "模型驻留", "新包装"):
        assert label in src, f"App.tsx NAV 缺少 {label}"


def test_api_ts_functions():
    src = _read("api.ts")
    for fn in ("fetchCascadeTasks", "fetchCascadeTask", "fetchCascadeTrail",
               "fetchModelsRuntime", "fetchPackageDecisions",
               "finalizePackageDecision"):
        assert f"function {fn}" in src, f"api.ts 缺少 {fn}"


# ---------------- API 行为合约 ----------------


def test_models_runtime_empty_is_honest(client):
    c, _ = client
    csrf = _login(c)
    r = c.get("/api/v1/models/runtime", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    body = r.json()
    assert body == {"count": 0, "models": []}


def test_submit_stays_shadow(client):
    c, _ = client
    csrf = _login(c)
    r = c.post("/api/v1/cascade/tasks",
               headers={"X-CSRF-Token": csrf},
               json={"tier": "standard", "source": "api",
                     "asset": {"asset_id": "a1", "sha256": "s" * 64,
                               "image_width": 640, "image_height": 480}})
    assert r.status_code == 200, r.text
    assert r.json()["production_switch"] is False


def test_task_detail_includes_billing_and_sla(client):
    c, store = client
    csrf = _login(c)
    r = c.post("/api/v1/cascade/tasks",
               headers={"X-CSRF-Token": csrf},
               json={"tier": "deep", "source": "api",
                     "asset": {"asset_id": "a2", "sha256": "t" * 64,
                               "image_width": 640, "image_height": 480}})
    task_id = r.json()["task"]["task_id"]
    d = c.get(f"/api/v1/cascade/tasks/{task_id}",
              headers={"X-CSRF-Token": csrf}).json()
    assert "billing" in d, "任务详情必须带成本账本"
    assert "remaining_sla" in d, "任务详情必须带剩余 SLA（业务语言）"


# ---------------- packaging 裁决合约 ----------------


def _candidate(store) -> str:
    d = pkg.create_candidate(
        store, display_name="500ml 茉莉乌龙（新瓶型）",
        package_version_id="pv-001", created_by="qwen3-vl:4b",
        sku_id="sku-001")
    return d["decision_id"]


def test_packaging_requires_auth(client):
    c, _ = client
    assert c.get("/api/v1/packaging/decisions").status_code == 401


def test_packaging_list_empty(client):
    c, _ = client
    csrf = _login(c)
    r = c.get("/api/v1/packaging/decisions",
              headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_packaging_finalize_requires_csrf(client):
    c, store = client
    did = _candidate(store)
    r = c.post(f"/api/v1/packaging/decisions/{did}/finalize",
               json={"status": "same_sku_new_package",
                     "name_choice": "keep_old_name"})
    assert r.status_code in (401, 403)


def test_packaging_finalize_invalid_status_rejected(client):
    c, store = client
    csrf = _login(c)
    did = _candidate(store)
    r = c.post(f"/api/v1/packaging/decisions/{did}/finalize",
               headers={"X-CSRF-Token": csrf},
               json={"status": "candidate"})
    assert r.status_code == 400


def test_packaging_finalize_keep_old_name(client):
    c, store = client
    csrf = _login(c)
    did = _candidate(store)
    r = c.post(f"/api/v1/packaging/decisions/{did}/finalize",
               headers={"X-CSRF-Token": csrf},
               json={"status": "same_sku_new_package",
                     "name_choice": "keep_old_name"})
    assert r.status_code == 200, r.text
    d = r.json()["decision"]
    assert d["status"] == "same_sku_new_package"
    assert d["sku_id"] == "sku-001", "沿用旧名不得改变 sku_id"
    assert d["package_version_id"] != "pv-001", "新包装必须生成新 package_version"
    # 人工裁决来源进审计（决策行 source 保持创建来源 qwen）
    audits = [a for a in store.list_audit(subject_id=did)
              if a["action"] == "packaging.finalized"]
    assert audits, "finalize 必须写审计"
    detail = json.loads(audits[-1]["detail_json"])
    assert detail["source"] == "human", "API 裁决来源必须固定为 human"


def test_packaging_supersede_only_after_final(client):
    c, store = client
    csrf = _login(c)
    older = _candidate(store)
    newer = _candidate(store)
    r = c.post("/api/v1/packaging/supersede",
               headers={"X-CSRF-Token": csrf},
               json={"older_id": older, "newer_id": newer})
    assert r.status_code == 400, "未终结决定不得建立 supersede"
