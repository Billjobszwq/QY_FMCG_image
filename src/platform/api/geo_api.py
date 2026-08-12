"""ABOSV2 Phase F：位置与外勤 API（geo.read/geo scope + 客户隔离）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..auth import AuthService, require_principal
from ..field_ops import FieldOpsError, FieldOpsService
from ..iam import IAMService
from ..scope import (ScopeViolation, assert_test_run_for_api,
                     bind_fixture_scope)


def _assert_test_run(store, test_run_id: str) -> None:
    """SI3：test_run 前置校验（fail-closed → 409，指令四.5/6）。"""
    try:
        assert_test_run_for_api(store, test_run_id)
    except ScopeViolation as e:
        raise HTTPException(409, str(e))


class AddressBody(BaseModel):
    customer_id: str
    raw: str
    test_run_id: str = ""


class VerifyBody(BaseModel):
    chosen_index: int = 0


class ManualCoordsBody(BaseModel):
    lat: float
    lng: float
    coord_system: str = "wgs84"
    source: str = "manual"


class AdjustPlanBody(BaseModel):
    ordered_task_ids: list[str] = []


class EmployeeBody(BaseModel):
    customer_id: str
    name: str
    skills: list = []
    vehicle: str = ""
    test_run_id: str = ""


class TaskBody(BaseModel):
    customer_id: str
    address_id: str
    project_id: str = ""
    kind: str = "visit"
    survey_id: str = ""
    require_storefront: bool = True
    selfie_required: bool = False
    test_run_id: str = ""


class PlanBody(BaseModel):
    customer_id: str
    task_ids: list[str] = []
    constraints: dict = {}
    test_run_id: str = ""


class DispatchBody(BaseModel):
    employee_id: str
    plan_id: str


class FenceBody(BaseModel):
    customer_id: str
    name: str
    lat: float
    lng: float
    radius_m: float


class ArriveBody(BaseModel):
    fence_id: str
    lat: float
    lng: float
    accuracy: float
    employee_id: str


class EvidenceBody(BaseModel):
    kind: str
    media_ref: str = ""
    location: dict = {}


def _platform(iam: IAMService, actor: str, session_role: str) -> bool:
    if session_role == "admin":
        return True
    roles = set(iam.roles_of(actor))
    return "platform_admin" in roles or "owner" in roles


def _guard(iam: IAMService, actor: str, session_role: str,
           customer_id: str = "") -> None:
    if _platform(iam, actor, session_role):
        return
    if not iam.authorize(actor, "geo.read", customer_id=customer_id):
        raise HTTPException(
            403, f"无权访问外勤数据（customer={customer_id or '未指定'}）")


def create_geo_router(store: Any, svc: FieldOpsService, iam: IAMService,
                      auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["geo"])

    def _wrap(fn):
        def wrap(*a, **kw):
            try:
                return fn(*a, **kw)
            except FieldOpsError as e:
                raise HTTPException(409, str(e))
        return wrap

    @router.get("/api/v1/geo/map-provider")
    def map_provider() -> dict:
        ok, reason = svc.map_provider.available()
        return {"available": ok, "reason": reason,
                "fallback": "坐标列表与围栏数值展示"}

    @router.post("/api/v1/geo/addresses")
    def add_address(body: AddressBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], body.customer_id)
        _assert_test_run(store, body.test_run_id)
        addr = _wrap(svc.add_address)(
            customer_id=body.customer_id, raw=body.raw, actor=p["actor"])
        if body.test_run_id:
            bind_fixture_scope(store, "geo_address_v1",
                               addr["address_id"], body.test_run_id)
        return {"address": addr}

    @router.get("/api/v1/geo/addresses")
    def addresses(request: Request, customer_id: str) -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], customer_id)
        rows = svc.list_addresses(customer_id=customer_id)
        return {"count": len(rows), "addresses": rows}

    @router.post("/api/v1/geo/addresses/{address_id}/verify")
    def verify(address_id: str, body: VerifyBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        return {"address": _wrap(svc.verify_address)(
            address_id, chosen_index=body.chosen_index, actor=p["actor"])}

    # ---- ABOSV3 T7：Provider SPI / 手工坐标 / 地图数据 / 预设 / 调版 ----

    @router.get("/api/v1/geo/providers")
    def providers() -> dict:
        """地理编码/瓦片/求解器状态与配置指引（无 Key 诚实降级）。"""
        gok, greason = svc.provider_geocoder.available()
        mok, mreason = svc.map_provider.available()
        sok, sreason = svc.solver.available()
        return {"geocoder": {"available": gok, "reason": greason},
                "map": {"available": mok, "reason": mreason,
                        "tiles_url": svc.map_provider.tiles_url},
                "solver": {"name": svc.solver.name, "available": sok,
                           "reason": sreason}}

    @router.post("/api/v1/geo/addresses/{address_id}/geocode")
    def geocode(address_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        return _wrap(svc.geocode_with_provider)(address_id,
                                                actor=p["actor"])

    @router.post("/api/v1/geo/addresses/{address_id}/manual-coords")
    def manual_coords(address_id: str, body: ManualCoordsBody,
                      request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        return {"address": _wrap(svc.set_manual_coords)(
            address_id, lat=body.lat, lng=body.lng,
            coord_system=body.coord_system, source=body.source,
            actor=p["actor"])}

    @router.get("/api/v1/geo/route-presets")
    def route_presets(request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        rows = store._conn.execute(
            "SELECT * FROM route_constraint_preset_v1"
            " ORDER BY created_at DESC LIMIT 200").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            import json as _json
            d["constraints"] = _json.loads(d["constraints_json"])
            out.append(d)
        return {"count": len(out), "presets": out}

    @router.post("/api/v1/geo/plans/{plan_id}/adjust")
    def adjust_plan(plan_id: str, body: AdjustPlanBody,
                    request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        return {"plan": _wrap(svc.adjust_plan)(
            plan_id, ordered_task_ids=body.ordered_task_ids,
            actor=p["actor"])}

    @router.get("/api/v1/geo/map-data")
    def map_data(request: Request, customer_id: str) -> dict:
        """地图图层数据：点位/围栏/路线/未分配任务（真实事实）。"""
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], customer_id)
        addrs = svc.list_addresses(customer_id=customer_id)
        points = [{"id": a["address_id"], "raw": a["raw"],
                   "status": a["status"],
                   "lat": (a["chosen"] or {}).get("lat"),
                   "lng": (a["chosen"] or {}).get("lng")}
                  for a in addrs]
        fences = [{"fence_id": f["fence_id"], "name": f["name"],
                   "lat": f["lat"], "lng": f["lng"],
                   "radius_m": f["radius_m"]} for f in
                  svc.list_fences(customer_id=customer_id)]
        tasks = svc.list_tasks(customer_id=customer_id)
        unassigned = [t["task_id"] for t in tasks
                      if t["status"] in ("draft", "planned")]
        plans = []
        for pl in svc.list_plans(customer_id=customer_id):
            plans.append({"plan_id": pl["plan_id"],
                          "version": pl["version"],
                          "status": pl["status"],
                          "stops": pl["stops"], "cost": pl["cost"],
                          "solver": pl["constraints"].get("solver")})
        return {"points": points, "fences": fences,
                "unassigned_tasks": unassigned, "plans": plans,
                "map": {"available": svc.map_provider.available()[0],
                        "tiles_url": svc.map_provider.tiles_url,
                        "reason": svc.map_provider.available()[1]}}

    @router.post("/api/v1/geo/employees")
    def add_employee(body: EmployeeBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], body.customer_id)
        _assert_test_run(store, body.test_run_id)
        emp = _wrap(svc.add_employee)(
            customer_id=body.customer_id, name=body.name,
            skills=body.skills, vehicle=body.vehicle)
        if body.test_run_id:
            bind_fixture_scope(store, "geo_employee_v1",
                               emp["employee_id"], body.test_run_id)
        return {"employee": emp}

    @router.get("/api/v1/geo/employees")
    def employees(request: Request, customer_id: str) -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], customer_id)
        rows = svc.list_employees(customer_id=customer_id)
        return {"count": len(rows), "employees": rows}

    @router.post("/api/v1/geo/tasks")
    def create_task(body: TaskBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], body.customer_id)
        _assert_test_run(store, body.test_run_id)
        task = _wrap(svc.create_task)(
            customer_id=body.customer_id, address_id=body.address_id,
            project_id=body.project_id, kind=body.kind,
            survey_id=body.survey_id,
            require_storefront=body.require_storefront,
            selfie_required=body.selfie_required, actor=p["actor"])
        if body.test_run_id:
            bind_fixture_scope(store, "field_task_v1",
                               task["task_id"], body.test_run_id)
        return {"task": task}

    @router.get("/api/v1/geo/tasks")
    def tasks(request: Request, customer_id: str) -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], customer_id)
        rows = svc.list_tasks(customer_id=customer_id)
        return {"count": len(rows), "tasks": rows}

    @router.post("/api/v1/geo/plans")
    def plan(body: PlanBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], body.customer_id)
        _assert_test_run(store, body.test_run_id)
        out = _wrap(svc.plan_route)(
            customer_id=body.customer_id, task_ids=body.task_ids,
            constraints=body.constraints, actor=p["actor"])
        if body.test_run_id and out.get("plan_id"):
            bind_fixture_scope(store, "route_plan_v1",
                               out["plan_id"], body.test_run_id)
        return {"plan": out}

    @router.get("/api/v1/geo/plans")
    def plans(request: Request, customer_id: str) -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], customer_id)
        rows = svc.list_plans(customer_id=customer_id)
        return {"count": len(rows), "plans": rows}

    @router.post("/api/v1/geo/tasks/{task_id}/dispatch")
    def dispatch(task_id: str, body: DispatchBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        return {"task": _wrap(svc.dispatch_task)(
            task_id, employee_id=body.employee_id, plan_id=body.plan_id,
            actor=p["actor"])}

    @router.post("/api/v1/geo/fences")
    def fence(body: FenceBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], body.customer_id)
        return {"fence": _wrap(svc.create_fence)(
            customer_id=body.customer_id, name=body.name, lat=body.lat,
            lng=body.lng, radius_m=body.radius_m)}

    @router.get("/api/v1/geo/fences")
    def fences(request: Request, customer_id: str) -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], customer_id)
        rows = svc.list_fences(customer_id=customer_id)
        return {"count": len(rows), "fences": rows}

    @router.post("/api/v1/geo/tasks/{task_id}/arrive")
    def arrive(task_id: str, body: ArriveBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        return {"task": _wrap(svc.arrive)(
            task_id=task_id, fence_id=body.fence_id, lat=body.lat,
            lng=body.lng, accuracy=body.accuracy,
            employee_id=body.employee_id)}

    @router.post("/api/v1/geo/tasks/{task_id}/evidence")
    def evidence(task_id: str, body: EvidenceBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        return {"evidence": _wrap(svc.add_evidence)(
            task_id=task_id, kind=body.kind, media_ref=body.media_ref,
            location=body.location, actor=p["actor"])}

    @router.post("/api/v1/geo/tasks/{task_id}/complete")
    def complete(task_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        return _wrap(svc.complete_task)(task_id, actor=p["actor"])

    return router
