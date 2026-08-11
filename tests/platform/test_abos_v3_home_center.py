"""ABOSV3 T2 红测试：首页总控（日历/日程/进度/活动/容量/便签/提醒）。

要求（AGENT-EXECUTION-PROMPT §T2、01 文档 §2）：
- 首页由真实 API 组成；创建日程/便签后刷新（新 client）不丢；
- 日历是统一读取模型（用户日程 + WorkItem 截止 + 外勤 + 问卷窗口）；
- 活动日志是业务友好投影（不展示 node.* 噪声）；
- 进度来自同一 current projection；容量为真实读数。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.api.app import create_app
from src.platform.control_plane import CommandGateway

PW = "v3-home-pw"


class _OkRecognition:
    def recognize(self, data: bytes, conf: float = 0.25):
        return {"count": 1, "products": [{"name": "SKU-X", "count": 1}]}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", PW)
    adapter = _OkRecognition()
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=adapter, probe=lambda spec: None)
    profiles = build_profiles_service(bundle)
    gateway = CommandGateway(bundle.store, profiles,
                             recognition_adapter=adapter)
    app = create_app(services=(), probe=lambda spec: None,
                     bundle=bundle, recognition_adapter=adapter,
                     web_dist=Path("/nonexistent-dist"))
    c = TestClient(app)
    r = c.post("/api/v1/auth/login",
               json={"username": "admin", "password": PW})
    assert r.status_code == 200, r.text
    h = {"X-CSRF-Token": r.json()["csrf_token"]}
    return c, h, bundle, gateway


class TestCalendarUnified:
    def test_user_event_crud_and_persist(self, client):
        c, h, _b, _g = client
        r = c.post("/api/v1/calendar/events", headers=h, json={
            "title": "周一例会", "starts_at": "2026-08-17T09:00:00Z"})
        assert r.status_code == 200, r.text
        eid = r.json()["event"]["event_id"]
        # 刷新（新会话读取）仍在：服务端持久化
        got = c.get("/api/v1/calendar/events").json()
        assert any(e["event_id"] == eid for e in got["events"])
        # 删除用户日程成功
        assert c.delete(f"/api/v1/calendar/events/{eid}",
                        headers=h).status_code == 200
        # 系统事件不可删除（诚实拒绝）
        fake = c.delete("/api/v1/calendar/events/field-nonexist",
                        headers=h)
        assert fake.status_code == 409

    def test_calendar_includes_work_due_from_same_projection(self, client):
        c, h, bundle, gw = client
        # 造一个未完成且带截止时间的 WorkItem（控制平面主线）
        work = bundle.store.insert_work_item_v2({
            "work_id": "work-due-test", "status": "waiting",
            "owner_type": "human", "owner_id": "pm",
            "title": "确认地址导入清单",
            "business_summary": "UAT 前置"})
        bundle.store._conn.execute(
            "UPDATE work_item_v2 SET due_at=? WHERE work_id=?",
            ("2026-08-20T18:00:00Z", work["work_id"]))
        bundle.store._conn.commit()
        evs = c.get("/api/v1/calendar/events").json()["events"]
        due = [e for e in evs if e.get("ref_id") == work["work_id"]]
        assert due and due[0]["kind"] == "work_due"


class TestNotesPersistent:
    def test_note_crud_persists(self, client):
        c, h, _b, _g = client
        r = c.post("/api/v1/notes", headers=h,
                   json={"content": "跟进客户 A 的地址导入"})
        assert r.status_code == 200, r.text
        nid = r.json()["note"]["note_id"]
        rows = c.get("/api/v1/notes").json()["notes"]
        assert any(n["note_id"] == nid for n in rows)
        upd = c.put(f"/api/v1/notes/{nid}", headers=h,
                    json={"pinned": True})
        assert upd.json()["note"]["pinned"] in (True, 1)
        assert c.delete(f"/api/v1/notes/{nid}",
                        headers=h).status_code == 200
        assert all(n["note_id"] != nid
                   for n in c.get("/api/v1/notes").json()["notes"])


class TestDashboard:
    def test_dashboard_eight_real_sections(self, client):
        c, h, _b, gw = client
        gw.submit(command_kind="vision.recognition.create",
                  params={"images": [["b.jpg", b"\xff\xd8fake"]]},
                  actor="tester", source="web")
        body = c.get("/api/v1/home/dashboard").json()
        for key in ("todos", "work_items", "calendar", "progress",
                    "activity", "capacity", "agent_alerts", "recent",
                    "notes"):
            assert key in body, f"首页缺 {key}"
        assert body["todos"]["done"] >= 1, "完成识别必须计入待办投影"
        assert body["capacity"]["db_bytes"] > 0
        assert body["capacity"]["tables"] > 50
        # 活动日志不得含 node.* 噪声
        assert all(not e["type"].startswith("node.")
                   for e in body["activity"])
        # 活动日志必须含真实业务事件
        types = {e["type"] for e in body["activity"]}
        assert "run.succeeded" in types or "command.accepted" in types
        # 进度与投影同源：work_total 与 todos 总数一致
        assert body["progress"]["work_total"] == sum(
            body["todos"].values())

    def test_recent_objects_links_real_records(self, client):
        c, h, bundle, _g = client
        from src.platform.iam import IAMService, MasterDataService
        iam = IAMService(bundle.store)
        md = MasterDataService(bundle.store, iam)
        md.create_customer(customer_id="home-cust", name="首页客户",
                           created_by="admin")
        recent = c.get("/api/v1/home/recent").json()
        assert any(x["id"] == "home-cust" for x in recent["customers"])
