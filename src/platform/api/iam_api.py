"""ABOSV2 Phase D：IAM 与主数据 API（账号/角色/授权/审计/批准矩阵 +
客户库/项目库/SKU 库 + 客户隔离概览）。

所有写操作要求登录+CSRF 与对应 scope（fail-closed）；列表按调用者
customer 作用域过滤；概览端点证明数据/任务/Usage 的客户隔离。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..auth import AuthService, require_principal
from ..iam import IAMError, IAMService, MasterDataError, MasterDataService


class PrincipalBody(BaseModel):
    kind: str = "user"
    username: str
    display_name: str = ""
    password: str = ""


class GrantBody(BaseModel):
    username: str
    role: str
    customer_id: str = ""
    project_id: str = ""


class CustomerBody(BaseModel):
    customer_id: str
    name: str
    is_test_fixture: bool = False
    retention_policy: str = ""


class ProjectBody(BaseModel):
    project_id: str
    customer_id: str
    name: str
    sku_scope: list = []
    budget: dict = {}


class SkuBody(BaseModel):
    sku_id: str
    canonical_name: str
    brand: str = ""
    category: str = ""
    volume: str = ""
    barcode: str = ""
    package_version: str = "v1"
    valid_from: str | None = None
    valid_to: str | None = None


class SupersedeBody(BaseModel):
    new_sku_id: str


class AliasBody(BaseModel):
    alias: str
    kind: str = "alias"
    customer_id: str = ""


class CheckBody(BaseModel):
    username: str
    scope: str
    customer_id: str = ""
    project_id: str = ""


class ApprovalCheckBody(BaseModel):
    action: str
    username: str | None = None


def _platform_actor(iam: IAMService, actor: str, session_role: str) -> bool:
    """平台角色：legacy admin session 或 IAM owner/platform_admin。"""
    if session_role == "admin":
        return True
    roles = set(iam.roles_of(actor))
    return "platform_admin" in roles or "owner" in roles


def _guard(iam: IAMService, actor: str, session_role: str, scope: str,
           customer_id: str = "") -> None:
    """fail-closed 授权守卫；legacy admin session 等同 platform_admin。"""
    if _platform_actor(iam, actor, session_role):
        return
    if not iam.authorize(actor, scope, customer_id=customer_id):
        raise HTTPException(
            403, f"权限不足：{actor} 缺少 {scope}"
                 + (f"（customer={customer_id}）" if customer_id else "")
                 + " 作用域")


def create_iam_router(store: Any, auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["iam"])
    iam = IAMService(store)
    master = MasterDataService(store, iam)

    # ---- 身份与授权 ----

    @router.get("/api/v1/iam/whoami")
    def whoami(request: Request) -> dict:
        p = require_principal(auth, request, csrf=False)
        actor = p["actor"]
        return {"actor": actor, "session_role": p["role"],
                "roles": iam.roles_of(actor),
                "scopes": iam.scopes_of(actor),
                "memberships": iam.memberships_of(actor),
                "visible_customer": iam.visible_customers(actor)}

    @router.post("/api/v1/iam/principals")
    def create_principal(body: PrincipalBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], "iam.manage")
        try:
            pr = iam.create_principal(
                kind=body.kind, username=body.username,
                display_name=body.display_name, password=body.password,
                created_by=p["actor"])
        except IAMError as e:
            raise HTTPException(409, str(e))
        return {"principal": {k: pr[k] for k in
                              ("principal_id", "kind", "username",
                               "display_name", "status")}}

    @router.get("/api/v1/iam/principals")
    def list_principals(request: Request) -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], "iam.read")
        rows = iam.list_principals()
        return {"count": len(rows), "principals": rows}

    @router.post("/api/v1/iam/grants")
    def grant(body: GrantBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], "iam.manage")
        try:
            return {"grant": iam.grant(
                username=body.username, role=body.role,
                customer_id=body.customer_id, project_id=body.project_id,
                granted_by=p["actor"])}
        except IAMError as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/iam/check")
    def check(body: CheckBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], "iam.read")
        return {"allowed": iam.authorize(
            body.username, body.scope, customer_id=body.customer_id,
            project_id=body.project_id)}

    @router.post("/api/v1/iam/approval-check")
    def approval_check(body: ApprovalCheckBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        username = body.username or p["actor"]
        return {"allowed": iam.check_approval(username, body.action),
                "action": body.action, "username": username}

    @router.get("/api/v1/iam/audit")
    def audit(request: Request, limit: int = 100) -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], "iam.read")
        rows = iam.list_audit(limit=limit)
        return {"count": len(rows), "events": rows}

    # ---- 主数据：客户库 / 项目库 / SKU 库 ----

    @router.post("/api/v1/master/customers")
    def create_customer(body: CustomerBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], "master.manage")
        try:
            return {"customer": master.create_customer(
                customer_id=body.customer_id, name=body.name,
                is_test_fixture=body.is_test_fixture,
                retention_policy=body.retention_policy,
                created_by=p["actor"])}
        except MasterDataError as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/master/customers")
    def list_customers(request: Request) -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], "master.read")
        rows = master.list_customers(
            viewer=None if _platform_actor(iam, p["actor"], p["role"])
            else p["actor"])
        return {"count": len(rows), "customers": rows}

    @router.get("/api/v1/master/customers/{customer_id}/overview")
    def customer_overview(customer_id: str, request: Request) -> dict:
        """G4 隔离证明端点：run/任务/Work/事件/Usage 按 customer 聚合；
        越权（其他客户作用域）fail-closed 403。"""
        p = require_principal(auth, request, csrf=False)
        if not _platform_actor(iam, p["actor"], p["role"]) and \
                not iam.authorize(p["actor"], "master.read",
                                  customer_id=customer_id):
            raise HTTPException(
                403, f"无权访问客户 {customer_id} 的数据（作用域隔离）")
        cust = master.get_customer(customer_id)
        if cust is None:
            raise HTTPException(404, f"customer 不存在: {customer_id}")
        overview = master.customer_overview(customer_id)
        overview["customer"] = cust
        iam.audit(p["actor"], "master.overview.readed",
                  f"customer:{customer_id}", {},
                  customer_id=customer_id)
        return overview

    @router.post("/api/v1/master/projects")
    def create_project(body: ProjectBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], "master.manage",
               customer_id=body.customer_id)
        try:
            return {"project": master.create_project(
                project_id=body.project_id, customer_id=body.customer_id,
                name=body.name, sku_scope=body.sku_scope,
                budget=body.budget, created_by=p["actor"])}
        except MasterDataError as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/master/projects")
    def list_projects(request: Request, customer_id: str) -> dict:
        p = require_principal(auth, request, csrf=False)
        if not _platform_actor(iam, p["actor"], p["role"]) and \
                not iam.authorize(p["actor"], "master.read",
                                  customer_id=customer_id):
            raise HTTPException(403, "无权访问该客户的项目（作用域隔离）")
        rows = master.list_projects(customer_id=customer_id)
        return {"count": len(rows), "projects": rows}

    @router.post("/api/v1/master/skus")
    def create_sku(body: SkuBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], "master.manage")
        try:
            return {"sku": master.create_sku(
                sku_id=body.sku_id, canonical_name=body.canonical_name,
                brand=body.brand, category=body.category,
                volume=body.volume, barcode=body.barcode,
                package_version=body.package_version,
                valid_from=body.valid_from, valid_to=body.valid_to,
                created_by=p["actor"])}
        except MasterDataError as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/master/skus")
    def list_skus(request: Request,
                  include_superseded: bool = False) -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], "master.read")
        rows = master.list_skus(include_superseded=include_superseded)
        for r in rows:
            r["aliases"] = master.aliases_of(r["sku_id"])
        return {"count": len(rows), "skus": rows}

    @router.post("/api/v1/master/skus/{sku_id}/supersede")
    def supersede_sku(sku_id: str, body: SupersedeBody,
                      request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], "master.manage")
        try:
            return {"sku": master.supersede_sku(
                old_sku_id=sku_id, new_sku_id=body.new_sku_id,
                actor=p["actor"])}
        except MasterDataError as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/master/skus/{sku_id}/aliases")
    def add_alias(sku_id: str, body: AliasBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], "master.manage")
        try:
            return {"alias": master.add_alias(
                sku_id=sku_id, alias=body.alias, kind=body.kind,
                customer_id=body.customer_id, actor=p["actor"])}
        except MasterDataError as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/master/skus/{sku_id}/display-name")
    def display_name(sku_id: str, request: Request,
                     customer_id: str = "") -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], "master.read")
        return {"sku_id": sku_id, "customer_id": customer_id,
                "display_name": master.display_name_for(
                    sku_id, customer_id)}

    return router
