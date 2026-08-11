"""ABOSV2 Phase F：位置与外勤 API（geo.read/geo scope + 客户隔离）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..auth import AuthService, require_principal
from ..field_ops import FieldOpsError, FieldOpsService
from ..iam import IAMService


class AddressBody(BaseModel):
    customer_id: str
    raw: str


class VerifyBody(BaseModel):
    chosen_index: int = 0


class EmployeeBody(BaseModel):
    customer_id: str
    name: str
    skills: list = []
    vehicle: str = ""


class TaskBody(BaseModel):
    customer_id: str
    address_id: str
    project_id: str = ""
    kind: str = "visit"
    survey_id: str = ""
    require_storefront: bool = True
    selfie_required: bool = False


class PlanBody(BaseModel):
    customer_id: str
    task_ids: list[str] = []
    constraints: dict = {}


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
        return {"address": _wrap(svc.add_address)(
            customer_id=body.customer_id, raw=body.raw, actor=p["actor"])}

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

    @router.post("/api/v1/geo/employees")
    def add_employee(body: EmployeeBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], body.customer_id)
        return {"employee": _wrap(svc.add_employee)(
            customer_id=body.customer_id, name=body.name,
            skills=body.skills, vehicle=body.vehicle)}

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
        return {"task": _wrap(svc.create_task)(
            customer_id=body.customer_id, address_id=body.address_id,
            project_id=body.project_id, kind=body.kind,
            survey_id=body.survey_id,
            require_storefront=body.require_storefront,
            selfie_required=body.selfie_required, actor=p["actor"])}

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
        return {"plan": _wrap(svc.plan_route)(
            customer_id=body.customer_id, task_ids=body.task_ids,
            constraints=body.constraints, actor=p["actor"])}

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
