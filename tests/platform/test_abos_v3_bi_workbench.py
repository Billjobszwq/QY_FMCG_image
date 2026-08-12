"""ABOSV3 T9 红测试：BI 受限公式 DSL、下钻、数据产品、Dashboard。

- 计算指标公式 AST 白名单：未注册指标/函数调用/字符串一律拒绝；
- 计算指标求值正确（含除零保护）；
- 指标下钻返回真实事实行（usage/survey/recognition）；
- 数据产品列表带血缘与真实行数；
- Dashboard CRUD 持久化。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.analytics import AnalyticsError, AnalyticsService
from src.platform.api.app import create_app

PW = "v9-bi-pw"


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
    app = create_app(services=(), probe=lambda spec: None,
                     bundle=bundle, recognition_adapter=adapter,
                     web_dist=Path("/nonexistent-dist"))
    c = TestClient(app)
    r = c.post("/api/v1/auth/login",
               json={"username": "admin", "password": PW})
    h = {"X-CSRF-Token": r.json()["csrf_token"]}
    return c, h, bundle


class TestFormulaDsl:
    def test_valid_formula_and_evaluation(self, client):
        c, h, bundle = client
        # 造 usage 事实
        bundle.store.insert_usage_event_v2(
            usage_id="u-1", unit="recognition_photo", quantity=4,
            customer_id="bi-cust")
        bundle.store.insert_usage_event_v2(
            usage_id="u-2", unit="model_compute_ms", quantity=100,
            customer_id="bi-cust")
        r = c.post("/api/v1/analytics/metrics/computed", headers=h,
                   json={"metric_id": "recognition.photo_per_run",
                         "name": "每运行照片数",
                         "formula":
                         "recognition.photos / (workflow.runs + 1)"})
        assert r.status_code == 200, r.text
        assert r.json()["refs"] == ["recognition.photos",
                                    "workflow.runs"]
        ev = c.get("/api/v1/analytics/metrics/"
                   "recognition.photo_per_run/evaluate",
                   params={"customer_id": "bi-cust"}).json()
        assert ev["value"] == pytest.approx(4.0)  # 4 / (0+1)

    def test_formula_fail_closed(self, client):
        c, h, _b = client
        # 未注册指标
        r = c.post("/api/v1/analytics/metrics/computed", headers=h,
                   json={"metric_id": "bad.ref", "name": "x",
                         "formula": "not_a.metric + 1"})
        assert r.status_code == 409
        # 函数调用（任意代码）
        r = c.post("/api/v1/analytics/metrics/computed", headers=h,
                   json={"metric_id": "bad.fn", "name": "x",
                         "formula": "__import__('os').system('ls')"})
        assert r.status_code == 409
        # 字符串常量
        r = c.post("/api/v1/analytics/metrics/computed", headers=h,
                   json={"metric_id": "bad.str", "name": "x",
                         "formula": "'select * from'"})
        assert r.status_code == 409

    def test_division_by_zero_protected(self, client):
        c, h, bundle = client
        svc = AnalyticsService(bundle.store)
        svc.create_computed_metric(
            metric_id="bad.div", name="除零",
            formula="recognition.photos / workflow.runs", actor="admin")
        with pytest.raises(AnalyticsError):
            svc.evaluate_metric("bad.div", customer_id="no-such")


class TestDrilldownAndProducts:
    def test_drilldown_real_rows(self, client):
        c, h, bundle = client
        bundle.store.insert_usage_event_v2(
            usage_id="u-d1", unit="recognition_photo", quantity=1,
            customer_id="bi-cust", run_id="run-x")
        d = c.get("/api/v1/analytics/metrics/recognition.photos/drilldown",
                  params={"customer_id": "bi-cust"}).json()
        assert d["entity"] == "usage_event"
        assert any(r["usage_id"] == "u-d1" for r in d["rows"])

    def test_data_products_lineage(self, client):
        c, h, _b = client
        d = c.get("/api/v1/analytics/data-products").json()
        assert d["count"] >= 6
        names = {p["product"] for p in d["products"]}
        assert "usage.event_v2" in names
        assert all("lineage" in p for p in d["products"])


class TestDashboardPersist:
    def test_dashboard_crud(self, client):
        c, h, _b = client
        r = c.post("/api/v1/analytics/dashboards", headers=h, json={
            "name": "UAT 运营看板", "customer_id": "bi-cust",
            "widgets": [{"type": "bar", "metric": "recognition.photos",
                         "x": 0, "y": 0, "w": 6, "h": 4}],
            "filters": {"customer_id": "bi-cust"}}).json()
        did = r["dashboard_id"]
        rows = c.get("/api/v1/analytics/dashboards").json()
        hit = next(d for d in rows["dashboards"]
                   if d["dashboard_id"] == did)
        assert hit["widgets"][0]["metric"] == "recognition.photos"
        u = c.put(f"/api/v1/analytics/dashboards/{did}", headers=h,
                  json={"name": "UAT 运营看板 v2",
                        "customer_id": "bi-cust",
                        "widgets": hit["widgets"] + [
                            {"type": "pie",
                             "metric": "survey.submitted"}],
                        "filters": {}})
        assert u.status_code == 200
        rows = c.get("/api/v1/analytics/dashboards").json()
        hit = next(d for d in rows["dashboards"]
                   if d["dashboard_id"] == did)
        assert hit["name"] == "UAT 运营看板 v2"
        assert len(hit["widgets"]) == 2
