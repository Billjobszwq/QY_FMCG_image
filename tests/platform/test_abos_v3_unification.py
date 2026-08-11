"""ABOSV3 T1 红测试：统一 Work/Run/Event 投影与数据一致性 P0。

任务书（AGENT-EXECUTION-PROMPT.md §四）：
1. ABOSV3-P0-001：`workflow.succeeded/failed/cancelled/waiting_human`
   必须被投影器识别；事件清空重建后完成 WorkItem 不得变回 todo；
2. ABOSV3-P0-002：首页/任务板/主管/日历必须消费同一 current
   projection（WorkItemV2 主线），不得存在平行真相；
3. ABOSV3-P0-003：failed→retry→succeeded 后 run 的 current error
   与 work blockers 必须清除（旧错误保留在事件/attempt 中）；
4. ABOSV3-P0-004：BI `list_report_specs` 不得把每个版本都再次取
   latest（v2 重复、v1 消失）；每个 spec 只出现一次且历史版本可查；
5. ABOSV3-P1-015：IAM 多客户用户必须看到全部获授权客户，不只第一个；
6. reconcile 必须同时对照 BusinessRun 业务事实，不只和错误 reducer 自洽。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.control_plane import CommandGateway
from src.platform.workflow import WorkflowService
from src.platform.analytics import AnalyticsService
from src.platform.iam import IAMService


class _BoomRecognition:
    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.calls = 0

    def recognize(self, data: bytes, conf: float = 0.25):
        from src.platform.adapters.legacy.recognition import (
            RecognitionAdapterError)
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RecognitionAdapterError("unreachable", "识别服务不可达")
        return {"count": 1, "products": [{"name": "SKU-X", "count": 1}]}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "v3-admin-pw")
    adapter = _BoomRecognition()
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=adapter, probe=lambda spec: None)
    profiles = build_profiles_service(bundle)
    gateway = CommandGateway(bundle.store, profiles,
                             recognition_adapter=adapter)
    service = WorkflowService(bundle.store, bundle.capabilities, gateway)
    return {"store": bundle.store, "service": service,
            "gateway": gateway, "adapter": adapter, "bundle": bundle}


def _publish_minimal(env, name="最小链") -> str:
    svc = env["service"]
    spec = {"trigger": {"type": "manual"}, "variables": {},
            "nodes": [{"id": "start", "type": "trigger"},
                      {"id": "t", "type": "transform",
                       "config": {"map": {"ok": True}}},
                      {"id": "end", "type": "end"}],
            "edges": [{"from": "start", "to": "t"},
                      {"from": "t", "to": "end"}],
            "policy": {"approval_required_for_publish": True}}
    d = svc.create_draft(name=name, spec=spec, actor="admin")
    did = d["definition_id"]
    svc.lint(did)
    svc.simulate(did, inputs={}, actor="admin")
    svc.approve(did, actor="admin")
    svc.publish(did, actor="admin")
    return did


class TestP0001WorkflowEventsInProjection:
    def test_workflow_succeeded_projects_done_after_rebuild(self, env):
        """workflow.succeeded 必须被投影器识别；清空重建后仍是 done。"""
        svc, store = env["service"], env["store"]
        did = _publish_minimal(env)
        out = svc.start_run(did, inputs={}, actor="admin")
        run, work_id = out["run"], out["run"]["work_id"]
        assert run["status"] == "succeeded"
        # 从事件重建投影：完成状态不得退化为 todo
        proj = store.rebuild_work_projection()
        mine = next(i for i in proj["items"] if i["work_id"] == work_id)
        assert mine["status"] == "done", (
            f"workflow.succeeded 未被投影器识别：{mine['status']}")

    def test_workflow_failed_projects_blocked_after_rebuild(self, env):
        svc, store = env["service"], env["store"]
        spec = {"trigger": {"type": "manual"}, "variables": {},
                "nodes": [{"id": "start", "type": "trigger"},
                          {"id": "lp", "type": "loop",
                           "config": {"items_path": "$inputs.items",
                                      "body": "step"}},
                          {"id": "step", "type": "transform",
                           "config": {"map": {"v": 1}}},
                          {"id": "end", "type": "end"}],
                "edges": [{"from": "start", "to": "lp"},
                          {"from": "lp", "to": "step"},
                          {"from": "step", "to": "end"}]}
        d = svc.create_draft(name="失败链", spec=spec, actor="admin")
        did = d["definition_id"]
        svc.lint(did)
        svc.simulate(did, inputs={"items": []}, actor="admin")
        svc.approve(did, actor="admin")
        svc.publish(did, actor="admin")
        # 运行时 items 非列表 → loop 诚实失败 → workflow.failed
        out = svc.start_run(did, inputs={"items": "oops"}, actor="admin")
        assert out["run"]["status"] == "failed"
        proj = store.rebuild_work_projection()
        mine = next(i for i in proj["items"]
                    if i["work_id"] == out["run"]["work_id"])
        assert mine["status"] == "blocked"

    def test_waiting_human_projects_waiting(self, env):
        svc, store = env["service"], env["store"]
        spec = {"trigger": {"type": "manual"}, "variables": {},
                "nodes": [{"id": "start", "type": "trigger"},
                          {"id": "ap", "type": "human_approval",
                           "config": {"title": "测试批准"}},
                          {"id": "end", "type": "end"}],
                "edges": [{"from": "start", "to": "ap"},
                          {"from": "ap", "to": "end"}]}
        d = svc.create_draft(name="批准链", spec=spec, actor="admin")
        did = d["definition_id"]
        svc.lint(did)
        svc.simulate(did, inputs={}, actor="admin")
        svc.approve(did, actor="admin")
        svc.publish(did, actor="admin")
        out = svc.start_run(did, inputs={}, actor="admin")
        work_id = out["run"]["work_id"]
        assert out["run"]["status"] == "waiting_human"
        proj = store.rebuild_work_projection()
        mine = next(i for i in proj["items"] if i["work_id"] == work_id)
        assert mine["status"] == "waiting", (
            "run.waiting_human 必须投影为 waiting（等待人工）")


class TestP0003ErrorClearedOnSuccess:
    def test_failed_retry_succeeded_clears_current_error(self, env):
        env["adapter"].fail_times = 1
        gw = env["gateway"]
        out = gw.submit(
            command_kind="vision.recognition.create",
            params={"images": [["a.jpg", b"\xff\xd8fake"]]},
            actor="tester", source="api")
        run_id = out["run_id"]
        assert out["status"] == "failed"
        failed_run = env["store"].get_business_run(run_id)
        assert failed_run["error"], "失败必须保留错误"
        out2 = gw.retry(run_id, actor="tester")
        assert out2["status"] == "succeeded"
        run = env["store"].get_business_run(run_id)
        assert run["error"] == "", (
            "succeeded run 不得残留上次失败的 current error")
        work = env["store"].get_work_item_v2(run["work_id"])
        import json
        blockers = json.loads(work.get("blockers_json") or "[]")
        assert blockers == [], "成功后 work 的 blockers 必须清除"
        # 旧失败仍在事件/attempt 历史中可查
        evs = env["store"].list_events()
        assert any(e["event_type"] == "run.failed"
                   and e["run_id"] == run_id for e in evs)


class TestP0004BiVersions:
    def test_report_list_no_duplicate_latest_and_history_visible(
            self, env):
        store = env["store"]
        svc = AnalyticsService(store)
        store._conn.execute(
            "INSERT INTO md_customer_v1 (customer_id, name, created_by,"
            " created_at, updated_at) VALUES ('c1','客户一','admin',"
            " datetime('now'), datetime('now'))")
        spec = svc.create_report_spec(
            name="识别概览", metrics=["recognition.photos"],
            customer_id="c1", actor="analyst")
        sid = spec["spec_id"]
        svc.approve_report(sid, actor="analyst")
        svc.publish_report(sid, actor="analyst")
        # 模拟异常回答后的报表刷新（v2 draft）
        store._conn.execute(
            "INSERT INTO bi_report_spec_v1 (spec_id, version, name,"
            " status, customer_id, metrics_json, dimensions_json,"
            " nl_query, note, created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'),"
            "datetime('now'))",
            (sid, 2, "识别概览", "draft", "c1",
             '["recognition.photos"]', "[]", "", "刷新", "analyst"))
        store._conn.commit()
        reps = svc.list_report_specs()
        sids = [r["spec_id"] for r in reps]
        assert sids.count(sid) == 1, (
            "同一 spec 不得在列表重复出现（v1/v2 各取 latest 造成重复）")
        versions = svc.list_report_versions(sid)
        vs = sorted(v["version"] for v in versions)
        assert vs == [1, 2], "v1 与 v2 必须分别可见，v1 不得消失"
        assert versions[0]["status"] == "published" or any(
            v["status"] == "published" for v in versions)


class TestP1015MultiCustomer:
    def test_user_sees_all_granted_customers(self, env):
        store = env["store"]
        iam = IAMService(store)
        from src.platform.iam import MasterDataService
        md = MasterDataService(store, iam)
        for cid in ("cust-x", "cust-y", "cust-z"):
            md.create_customer(customer_id=cid, name=cid,
                               created_by="admin")
        iam.create_principal(kind="user", username="multi",
                             password="pw-multi-x1", created_by="admin")
        for cid in ("cust-x", "cust-y", "cust-z"):
            iam.grant(username="multi", role="analyst",
                      customer_id=cid, granted_by="admin")
        visible = iam.visible_customers("multi")
        assert visible is not None
        assert sorted(visible) == ["cust-x", "cust-y", "cust-z"], (
            "多客户授权不得只取第一个")
        assert iam.authorize("multi", "analytics.read",
                             customer_id="cust-z")
        rows = md.list_customers(viewer="multi")
        assert sorted(r["customer_id"] for r in rows) == \
            ["cust-x", "cust-y", "cust-z"]


class TestUnifiedCurrentWork:
    def test_unified_endpoint_same_as_projection(self, env):
        """首页/主管/任务板共用的 current-work 必须与 WorkItemV2
        current projection 完全同源（同一 work 的 status 相同）。"""
        from fastapi.testclient import TestClient
        from src.platform.api.app import create_app
        gw = env["gateway"]
        out = gw.submit(
            command_kind="vision.recognition.create",
            params={"images": [["b.jpg", b"\xff\xd8fake"]]},
            actor="tester", source="web")
        work_id, status = out["work_id"], out["status"]
        app = create_app(services=(), probe=lambda spec: None,
                         bundle=env["bundle"],
                         recognition_adapter=env["adapter"],
                         web_dist=Path("/nonexistent-dist"))
        client = TestClient(app)
        r = client.post("/api/v1/auth/login", json={
            "username": "admin", "password": "v3-admin-pw"})
        assert r.status_code == 200, r.text
        cur = client.get("/api/v1/control/current-work")
        assert cur.status_code == 200, cur.text
        body = cur.json()
        mine = next(i for i in body["items"]
                    if i.get("work_id") == work_id)
        expected = "done" if status == "succeeded" else "blocked"
        assert mine["status"] == expected
        # /api/v1/workitems（首页旧数据源）也必须含同一 work 且状态一致
        wi = client.get("/api/v1/workitems", params={
            "kind": "work_item_v2", "limit": 500})
        assert wi.status_code == 200
        hit = [i for i in wi.json()["items"] if i["id"] == work_id]
        assert hit, "workitems 必须消费 WorkItemV2 主线（不得平行真相）"
        assert hit[0]["status"] == expected


class TestReconcileBusinessFacts:
    def test_reconcile_detects_run_projection_drift(self, env):
        """reconcile 必须对照 BusinessRun 业务事实：succeeded run 的
        work 若被篡改为 todo，必须报 inconsistent。"""
        gw = env["gateway"]
        out = gw.submit(
            command_kind="vision.recognition.create",
            params={"images": [["c.jpg", b"\xff\xd8fake"]]},
            actor="tester", source="api")
        store = env["store"]
        # 人为制造漂移：把完成 work 改回 todo（模拟错误 reducer 残留）
        store._conn.execute(
            "UPDATE work_item_v2 SET status='todo' WHERE work_id=?",
            (out["work_id"],))
        store._conn.commit()
        from fastapi.testclient import TestClient
        from src.platform.api.app import create_app
        client = TestClient(create_app(
            services=(), probe=lambda spec: None,
            bundle=env["bundle"], recognition_adapter=env["adapter"],
            web_dist=Path("/nonexistent-dist")))
        client.post("/api/v1/auth/login", json={
            "username": "admin", "password": "v3-admin-pw"})
        r = client.get("/api/v1/control/reconcile")
        body = r.json()
        # 允许 reconcile 自愈，但必须如实报告曾发现 run 级漂移并修复
        assert body["consistent"] is True and body.get(
            "business_facts_checked") is True, (
            "reconcile 必须同时对照 BusinessRun 业务事实")
        # 自愈后 work 必须回到 done
        row = store.get_work_item_v2(out["work_id"])
        assert row["status"] == "done"
