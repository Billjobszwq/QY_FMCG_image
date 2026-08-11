"""ABOSV2 Phase F 红测试：位置与外勤纵向切片（Gate G7）。

要求（任务书 §十/位置与外勤）：
1. 地理编码候选 + 置信度；低置信度地址不自动派发（人工确认门）；
2. VRP 路线：约束（max_km/多项目硬隔离）、未分配原因、成本可解释；
3. 围栏到店：半径+精度校验；门头必拍；可选自拍；
   人脸比对默认不自动触发；
4. 完成链路：任务 → 路线 → 到店 → 证据 → 差旅费；
5. 地图提供者无瓦片时诚实 blocked。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.composition.build import build_production_bundle
from src.platform.field_ops import (FieldOpsError, FieldOpsService,
                                    MapProviderAdapter)


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "v2-admin-pw")
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        probe=lambda spec: None)
    svc = FieldOpsService(bundle.store)
    return {"store": bundle.store, "svc": svc}


def _base_setup(env, cust="cust-a"):
    svc = env["svc"]
    emp = svc.add_employee(customer_id=cust, name="外勤甲",
                           skills=["survey"], vehicle="ebike")
    return emp


class TestGeocodeAndDispatchGate:
    def test_low_confidence_address_cannot_auto_dispatch(self, env):
        svc = env["svc"]
        emp = _base_setup(env)
        a = svc.add_address(customer_id="cust-a", raw="上海某路 1 号")
        assert a["status"] == "pending"
        assert a["confidence"] < 0.8
        assert len(a["candidates"]) >= 2
        t = svc.create_task(customer_id="cust-a",
                            address_id=a["address_id"],
                            project_id="pj-a", actor="admin")
        plan = svc.plan_route(customer_id="cust-a",
                              task_ids=[t["task_id"]], actor="admin")
        # 未确认地址：不分配并给出原因
        assert plan["stops"] == []
        assert any("未人工确认" in u["reason"]
                   for u in plan["unassigned"])
        with pytest.raises(FieldOpsError):
            svc.dispatch_task(t["task_id"], employee_id=emp["employee_id"],
                              plan_id=plan["plan_id"], actor="admin")
        # 人工确认后进入路线并可派发
        svc.verify_address(a["address_id"], chosen_index=0, actor="admin")
        plan2 = svc.plan_route(customer_id="cust-a",
                               task_ids=[t["task_id"]], actor="admin")
        assert len(plan2["stops"]) == 1
        d = svc.dispatch_task(t["task_id"],
                              employee_id=emp["employee_id"],
                              plan_id=plan2["plan_id"], actor="admin")
        assert d["status"] == "dispatched"

    def test_map_provider_honestly_blocked(self, env):
        ok, reason = MapProviderAdapter().available()
        assert ok is False and reason


class TestRouteConstraints:
    def test_multi_project_hard_isolation_and_max_km(self, env):
        svc = env["svc"]
        a1 = svc.add_address(customer_id="cust-a", raw="A 店 [geo]")
        a2 = svc.add_address(customer_id="cust-a", raw="B 店 [geo]")
        for a in (a1, a2):
            svc.verify_address(a["address_id"], chosen_index=0,
                               actor="admin")
        t1 = svc.create_task(customer_id="cust-a",
                             address_id=a1["address_id"],
                             project_id="pj-1", actor="admin")
        t2 = svc.create_task(customer_id="cust-a",
                             address_id=a2["address_id"],
                             project_id="pj-2", actor="admin")
        # 跨项目未允许合并 → 硬隔离，未分配原因留痕
        plan = svc.plan_route(customer_id="cust-a",
                              task_ids=[t1["task_id"], t2["task_id"]],
                              actor="admin")
        assert plan["stops"] == []
        assert any("硬隔离" in u["reason"] for u in plan["unassigned"])
        # 显式允许合并 → 成单路线，成本可解释
        plan2 = svc.plan_route(
            customer_id="cust-a",
            task_ids=[t1["task_id"], t2["task_id"]],
            constraints={"merge_projects": True,
                         "travel_unit_price": 3.0},
            actor="admin")
        assert len(plan2["stops"]) == 2
        assert plan2["cost"]["total_km"] > 0
        assert plan2["cost"]["total"] == round(
            plan2["cost"]["total_km"] * 3.0, 2)
        # max_km 约束：超出的任务未分配并有原因
        plan3 = svc.plan_route(
            customer_id="cust-a",
            task_ids=[t1["task_id"], t2["task_id"]],
            constraints={"merge_projects": True, "max_km": 0.01},
            actor="admin")
        assert any("最大里程" in u["reason"] for u in plan3["unassigned"])


class TestVisitFlow:
    def _dispatched(self, env):
        svc = env["svc"]
        emp = _base_setup(env)
        a = svc.add_address(customer_id="cust-a", raw="旗舰店 [geo]")
        svc.verify_address(a["address_id"], chosen_index=0, actor="admin")
        t = svc.create_task(customer_id="cust-a",
                            address_id=a["address_id"],
                            project_id="pj-a", survey_id="svy-c481",
                            actor="admin")
        plan = svc.plan_route(customer_id="cust-a",
                              task_ids=[t["task_id"]],
                              constraints={"travel_unit_price": 2.5},
                              actor="admin")
        svc.dispatch_task(t["task_id"], employee_id=emp["employee_id"],
                          plan_id=plan["plan_id"], actor="admin")
        chosen = svc.get_address(a["address_id"])["chosen"]
        fence = svc.create_fence(customer_id="cust-a", name="旗舰店围栏",
                                 lat=chosen["lat"], lng=chosen["lng"],
                                 radius_m=150)
        return svc, t, fence, emp, plan

    def test_arrive_requires_fence_and_accuracy(self, env):
        svc, t, fence, emp, _ = self._dispatched(env)
        # 围栏外 → 拒绝
        with pytest.raises(FieldOpsError):
            svc.arrive(task_id=t["task_id"], fence_id=fence["fence_id"],
                       lat=fence["lat"] + 0.05, lng=fence["lng"],
                       accuracy=5, employee_id=emp["employee_id"])
        # 精度不足 → 拒绝
        with pytest.raises(FieldOpsError):
            svc.arrive(task_id=t["task_id"], fence_id=fence["fence_id"],
                       lat=fence["lat"], lng=fence["lng"],
                       accuracy=200, employee_id=emp["employee_id"])
        arrived = svc.arrive(task_id=t["task_id"],
                             fence_id=fence["fence_id"],
                             lat=fence["lat"] + 0.0002,
                             lng=fence["lng"] + 0.0002,
                             accuracy=8, employee_id=emp["employee_id"])
        assert arrived["status"] == "arrived"

    def test_storefront_required_and_travel_cost(self, env):
        svc, t, fence, emp, plan = self._dispatched(env)
        svc.arrive(task_id=t["task_id"], fence_id=fence["fence_id"],
                   lat=fence["lat"], lng=fence["lng"], accuracy=8,
                   employee_id=emp["employee_id"])
        # 门头必拍：缺证据不得完成
        with pytest.raises(FieldOpsError):
            svc.complete_task(t["task_id"], actor="admin")
        # 自拍默认关闭（人脸比对默认不自动触发）
        with pytest.raises(FieldOpsError):
            svc.add_evidence(task_id=t["task_id"], kind="selfie",
                             actor="admin")
        svc.add_evidence(task_id=t["task_id"], kind="storefront",
                         media_ref="cas:sha-demo",
                         location={"lat": fence["lat"],
                                   "lng": fence["lng"]},
                         actor="admin")
        out = svc.complete_task(t["task_id"], actor="admin")
        assert out["task"]["status"] == "completed"
        cost = out["travel_cost"]
        stop = next(s for s in plan["stops"] if s["task_id"] == t["task_id"])
        assert cost["km"] == stop["leg_km"]
        assert cost["amount"] == round(cost["km"] * 2.5, 2)
        assert cost["km"] > 0
