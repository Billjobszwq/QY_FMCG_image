"""ABOSV3 T7 红测试：地址/地理编码 Provider SPI/地图数据/路线调版。

- 无 Key 时 geocode 诚实 degraded + 配置指引，不写假坐标进 chosen；
- 手工/导入坐标可确认（source=manual/import，confidence=1）；
- 路线计划诚实标注求解器（启发式非最优）；
- 人工调整站点顺序生成新版本（旧版保留）；
- map-data 返回真实点位/围栏/路线/未分配任务；无瓦片时地图
  available=False 且其他数据仍可用。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.api.app import create_app
from src.platform.field_ops import FieldOpsService

PW = "v3-geo-pw"


class _OkRecognition:
    def recognize(self, data: bytes, conf: float = 0.25):
        return {"count": 0, "products": []}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", PW)
    monkeypatch.delenv("GEOCODER_PROVIDER", raising=False)
    monkeypatch.delenv("AMAP_API_KEY", raising=False)
    monkeypatch.delenv("MAP_TILES_URL", raising=False)
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


class TestGeocoderHonesty:
    def test_no_key_degraded_no_fake_coords(self, client):
        c, h, _b = client
        prov = c.get("/api/v1/geo/providers").json()
        assert prov["geocoder"]["available"] is False
        assert "GEOCODER_PROVIDER" in prov["geocoder"]["reason"]
        a = c.post("/api/v1/geo/addresses", headers=h, json={
            "customer_id": "geo-cust",
            "raw": "上海市浦东新区示例路 100 号"}).json()["address"]
        r = c.post(f"/api/v1/geo/addresses/{a['address_id']}/geocode",
                   headers=h).json()
        assert r["status"] == "degraded"
        assert "GEOCODER_PROVIDER" in r["reason"]
        # 未确认前 chosen 必须为空（不得写假坐标）
        after = c.get("/api/v1/geo/addresses",
                      params={"customer_id": "geo-cust"}).json()
        hit = next(x for x in after["addresses"]
                   if x["address_id"] == a["address_id"])
        assert hit["chosen"] in (None, {}, "")

    def test_manual_coords_confirm(self, client):
        c, h, _b = client
        a = c.post("/api/v1/geo/addresses", headers=h, json={
            "customer_id": "geo-cust", "raw": "手工坐标店"}
            ).json()["address"]
        r = c.post(f"/api/v1/geo/addresses/{a['address_id']}/manual-coords",
                   headers=h, json={"lat": 31.23, "lng": 121.47,
                                    "source": "import"})
        assert r.status_code == 200, r.text
        addr = r.json()["address"]
        assert addr["status"] == "verified"
        assert addr["chosen"]["lat"] == 31.23
        assert addr["chosen"]["source"] == "import"
        # 越界坐标拒绝
        bad = c.post(
            f"/api/v1/geo/addresses/{a['address_id']}/manual-coords",
            headers=h, json={"lat": 999, "lng": 121})
        assert bad.status_code == 409


class TestRouteHonestyAndVersions:
    def _setup_two_tasks(self, client):
        c, h, _b = client
        addrs = []
        for i, (lat, lng) in enumerate([(31.20, 121.40),
                                        (31.30, 121.50)]):
            a = c.post("/api/v1/geo/addresses", headers=h, json={
                "customer_id": "geo-cust", "raw": f"店{i}"}).json()["address"]
            c.post(f"/api/v1/geo/addresses/{a['address_id']}/manual-coords",
                   headers=h, json={"lat": lat, "lng": lng})
            addrs.append(a["address_id"])
        tids = []
        for aid in addrs:
            t = c.post("/api/v1/geo/tasks", headers=h, json={
                "customer_id": "geo-cust", "address_id": aid,
                "project_id": "prj-1"}).json()["task"]
            tids.append(t["task_id"])
        return tids

    def test_plan_marks_heuristic_and_adjust_new_version(self, client):
        c, h, _b = client
        tids = self._setup_two_tasks(client)
        plan = c.post("/api/v1/geo/plans", headers=h, json={
            "customer_id": "geo-cust", "task_ids": tids,
            "constraints": {"depot_lat": 31.0, "depot_lng": 121.0,
                            "travel_unit_price": 2.0}}).json()["plan"]
        # 诚实标注启发式（非 VRP 最优解）
        assert plan["constraints"]["solver"] == (
            "nearest_neighbor_heuristic")
        assert "启发式" in plan["constraints"]["solver_note"]
        assert len(plan["stops"]) == 2
        # 人工调整顺序 → 新版本（v2），旧版保留
        adj = c.post(f"/api/v1/geo/plans/{plan['plan_id']}/adjust",
                     headers=h, json={
                         "ordered_task_ids": list(reversed(tids))})
        assert adj.status_code == 200, adj.text
        p2 = adj.json()["plan"]
        assert p2["version"] == 2
        assert p2["stops"][0]["task_id"] == tids[-1]
        assert "adjusted_by" in p2["constraints"]

    def test_map_data_and_degraded_tiles(self, client):
        c, h, _b = client
        tids = self._setup_two_tasks(client)
        c.post("/api/v1/geo/plans", headers=h, json={
            "customer_id": "geo-cust", "task_ids": tids,
            "constraints": {"depot_lat": 31.0, "depot_lng": 121.0}})
        md = c.get("/api/v1/geo/map-data",
                   params={"customer_id": "geo-cust"}).json()
        assert len(md["points"]) >= 2
        assert any(p["lat"] == 31.2 for p in md["points"])
        assert len(md["plans"]) >= 1
        assert len(md["unassigned_tasks"]) >= 2
        # 无瓦片配置：地图诚实不可用，但数据仍返回
        assert md["map"]["available"] is False
        assert "MAP_TILES_URL" in md["map"]["reason"]

    def test_route_preset_from_import_center(self, client):
        c, h, bundle = client
        import json
        bundle.store._conn.execute(
            "INSERT INTO route_constraint_preset_v1 (preset_id,"
            " customer_id, name, constraints_json, created_by,"
            " created_at) VALUES (?,?,?,?,?,datetime('now'))",
            ("rcp-1", "geo-cust", "华东日常",
             json.dumps({"max_km_per_day": 120}), "admin"))
        bundle.store._conn.commit()
        rows = c.get("/api/v1/geo/route-presets").json()
        assert any(p["name"] == "华东日常" for p in rows["presets"])
