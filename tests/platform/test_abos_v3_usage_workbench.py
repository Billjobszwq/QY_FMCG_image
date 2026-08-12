"""ABOSV3 T10 红测试：客户级 Usage 工作台。

- 按客户/单位汇总；行下钻带 run 状态与证据 bundle；
- 趋势按日；未归属计数；CSV 导出含表头与行；
- 非授权客户 403（finance.read 作用域）。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.api.app import create_app

PW = "v10-usage-pw"


class _OkRecognition:
    def recognize(self, data: bytes, conf: float = 0.25):
        return {"count": 0, "products": []}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", PW)
    adapter = _OkRecognition()
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=adapter, probe=lambda spec: None)
    build_profiles_service(bundle)
    # 造 usage 事实（含 run 关联）
    store = bundle.store
    store.insert_business_run({
        "run_id": "run-u1", "work_id": "work-u1",
        "trigger_type": "command", "correlation_id": "c1",
        "initiator_type": "human", "initiator_id": "bill",
        "status": "succeeded", "command_kind":
        "vision.recognition.create", "params": {},
        "customer_id": "u-cust", "project_id": "u-prj"})
    store._conn.execute(
        "UPDATE business_run_v1 SET evidence_bundle_id='ev-1'"
        " WHERE run_id='run-u1'")
    store._conn.commit()
    for i in range(3):
        store.insert_usage_event_v2(
            usage_id=f"u-{i}", unit="recognition_photo", quantity=1,
            run_id="run-u1", work_id="work-u1", node="recognition",
            capability="vision.recognition.create",
            profile_id="v4_best_standard", tier="standard",
            customer_id="u-cust", project_id="u-prj",
            source_evidence="recognition_task:t1")
    store.insert_usage_event_v2(
        usage_id="u-orphan", unit="agent_call", quantity=1,
        customer_id="")
    app = create_app(services=(), probe=lambda spec: None,
                     bundle=bundle, recognition_adapter=adapter,
                     web_dist=Path("/nonexistent-dist"))
    c = TestClient(app)
    r = c.post("/api/v1/auth/login",
               json={"username": "admin", "password": PW})
    h = {"X-CSRF-Token": r.json()["csrf_token"]}
    return c, h, bundle


class TestUsageWorkbench:
    def test_summary_and_drilldown(self, client):
        c, h, _b = client
        s = c.get("/api/v1/usage/summary",
                  params={"customer_id": "u-cust"}).json()
        units = {u["unit"] for u in s["by_unit"]}
        assert units == {"recognition_photo"}
        assert s["by_unit"][0]["total"] == 3
        assert s["unattributed"] >= 1
        assert s["by_date"]
        rows = c.get("/api/v1/usage/rows",
                     params={"customer_id": "u-cust"}).json()["rows"]
        assert len(rows) == 3
        r0 = rows[0]
        assert r0["run_status"] == "succeeded"
        assert r0["evidence_bundle_id"] == "ev-1"
        assert r0["profile_id"] == "v4_best_standard"

    def test_csv_export(self, client):
        c, h, _b = client
        r = c.get("/api/v1/usage/export.csv",
                  params={"customer_id": "u-cust"})
        assert r.status_code == 200
        text = r.content.decode("utf-8-sig")
        assert "usage_id" in text.splitlines()[0]
        assert "recognition_photo" in text

    def test_budgets(self, client):
        c, h, bundle = client
        from src.platform.iam import IAMService, MasterDataService
        md = MasterDataService(bundle.store, IAMService(bundle.store))
        md.create_customer(customer_id="u-cust", name="U",
                           created_by="admin")
        md.create_project(project_id="u-prj", customer_id="u-cust",
                          name="P", budget={"total": 1000},
                          created_by="admin")
        b = c.get("/api/v1/usage/budgets",
                  params={"customer_id": "u-cust"}).json()
        hit = next(x for x in b["budgets"]
                   if x["project_id"] == "u-prj")
        assert hit["budget_total"] == 1000
        assert hit["usage_events"] == 3

    def test_cross_customer_denied(self, client):
        c, h, bundle = client
        # 建一个只有 finance.read@other-cust 的用户
        from src.platform.iam import IAMService
        iam = IAMService(bundle.store)
        iam.create_principal(kind="user", username="finuser",
                             password="pw-fin-1", created_by="admin")
        iam.grant(username="finuser", role="finance_operator",
                  customer_id="other-cust", granted_by="admin")
        lg = c.post("/api/v1/auth/login",
                    json={"username": "finuser", "password": "pw-fin-1"})
        assert lg.status_code == 200
        r = c.get("/api/v1/usage/summary",
                  params={"customer_id": "u-cust"})
        assert r.status_code == 403
