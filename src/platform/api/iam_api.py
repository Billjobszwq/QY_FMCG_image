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
from ..scope import (ScopeResolver, ScopeViolation,
                     bind_fixture_scope)


def _assert_test_run(store, test_run_id: str) -> None:
    """SI3：受信创建路径前置校验——test_run 必须在 registry 且
    current（fail-closed，指令四.5/6），先于对象创建。"""
    if not test_run_id:
        return
    try:
        ScopeResolver(store).assert_test_run_current(test_run_id)
    except ScopeViolation as e:
        raise HTTPException(409, str(e))


class PrincipalBody(BaseModel):
    kind: str = "user"
    username: str
    display_name: str = ""
    password: str = ""
    test_run_id: str = ""   # SI4：受信 UAT 路径（registry fail-closed）


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
    # SI2：显式携带 test_run_id 时结构性绑定 fixture（受信路径）
    test_run_id: str = ""


class ProjectBody(BaseModel):
    project_id: str
    customer_id: str
    name: str
    sku_scope: list = []
    budget: dict = {}
    test_run_id: str = ""


class SkuBody(BaseModel):
    sku_id: str
    canonical_name: str
    brand: str = ""
    category: str = ""
    volume: str = ""
    barcode: str = ""
    package_version: str = "v1"
    valid_from: str | None = None
    test_run_id: str = ""
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


class RoleBody(BaseModel):
    name: str
    description: str = ""
    scopes: list[str] = []


class MasterStatusBody(BaseModel):
    status: str  # active | inactive


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
        vis = iam.visible_customers(actor)
        roles = iam.roles_of(actor)
        scopes = iam.scopes_of(actor)
        # 平台角色（env admin / owner / platform_admin）的后端授权是
        # 全量的；投影必须如实反映，否则前端 fail-closed 会错误隐藏
        # 受限模块（如模型管理）。投影仅改善体验，后端仍独立鉴权。
        is_platform = (p.get("role") == "admin"
                       or "owner" in roles
                       or "platform_admin" in roles)
        if is_platform:
            from ..iam import SCOPES as _ALL_SCOPES
            scopes = sorted(set(scopes) | set(_ALL_SCOPES))
        return {"actor": actor, "session_role": p["role"],
                "roles": roles,
                "scopes": scopes,
                "memberships": iam.memberships_of(actor),
                # ABOSV3-P1-015：多客户授权全部返回（None=平台角色）
                "visible_customers": vis,
                # 兼容字段：旧前端消费，仅作显示
                "visible_customer": None if vis is None else (
                    vis[0] if vis else "")}

    @router.post("/api/v1/iam/principals")
    def create_principal(body: PrincipalBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], "iam.manage")
        try:
            pr = iam.create_principal(
                kind=body.kind, username=body.username,
                display_name=body.display_name, password=body.password,
                created_by=p["actor"], test_run_id=body.test_run_id)
        except ScopeViolation as e:
            raise HTTPException(409, str(e))
        except IAMError as e:
            raise HTTPException(409, str(e))
        return {"principal": {k: pr[k] for k in
                              ("principal_id", "kind", "username",
                               "display_name", "status")
                              if k in pr}}

    @router.get("/api/v1/iam/principals")
    def list_principals(request: Request,
                        include_fixture: bool = False) -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], "iam.read")
        rows = iam.list_principals(include_fixture=include_fixture)
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
            # SI3：创建与 scope 同一事务（禁止先 commit 再 bind，
            # 指令四.8）；测试客户必须绑定有效 test_run（指令三.7）。
            out = master.create_customer(
                customer_id=body.customer_id, name=body.name,
                is_test_fixture=body.is_test_fixture
                or bool(body.test_run_id),
                retention_policy=body.retention_policy,
                created_by=p["actor"],
                test_run_id=body.test_run_id or "")
            return {"customer": out}
        except MasterDataError as e:
            raise HTTPException(409, str(e))
        except ScopeViolation as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/master/customers")
    def list_customers(request: Request,
                       include_fixture: bool = False) -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], "master.read")
        rows = master.list_customers(
            viewer=None if _platform_actor(iam, p["actor"], p["role"])
            else p["actor"],
            include_fixture=include_fixture)
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
        _assert_test_run(store, body.test_run_id)
        # SI3：fixture 客户不得产生 operational 子对象（指令四.4）
        pc = master.get_customer(body.customer_id)
        if pc and (pc.get("is_test_fixture")
                   or pc.get("data_scope") in ("uat_fixture",
                                                "demo_fixture")) \
                and not body.test_run_id:
            raise HTTPException(
                409, "SCOPE_MISSING_TEST_RUN_ID: fixture 客户下创建"
                "项目必须携带 test_run_id")
        try:
            out = master.create_project(
                project_id=body.project_id, customer_id=body.customer_id,
                name=body.name, sku_scope=body.sku_scope,
                budget=body.budget, created_by=p["actor"])
            if body.test_run_id:
                bind_fixture_scope(store, "md_project_v1",
                                   body.project_id, body.test_run_id)
            return {"project": out}
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
        _assert_test_run(store, body.test_run_id)
        try:
            out = master.create_sku(
                sku_id=body.sku_id, canonical_name=body.canonical_name,
                brand=body.brand, category=body.category,
                volume=body.volume, barcode=body.barcode,
                package_version=body.package_version,
                valid_from=body.valid_from, valid_to=body.valid_to,
                created_by=p["actor"])
            if body.test_run_id:
                bind_fixture_scope(store, "md_sku_v1",
                                   body.sku_id, body.test_run_id)
            return {"sku": out}
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

    # ---- ABOSV3 T3：自定义角色 / 权限模拟器 / 停用 / 合并建议 ----

    @router.get("/api/v1/iam/roles")
    def list_roles(request: Request) -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], "iam.read")
        rows = store._conn.execute(
            "SELECT role_id, name, builtin, description FROM iam_role_v1"
            " ORDER BY builtin DESC, name").fetchall()
        out = []
        for r in rows:
            scopes = [b["scope"] for b in store._conn.execute(
                "SELECT b.scope FROM iam_role_permission_v1 rp"
                " JOIN iam_permission_bundle_v1 b"
                " ON b.bundle_id=rp.bundle_id WHERE rp.role_id=?",
                (r["role_id"],)).fetchall()]
            out.append({**dict(r), "builtin": bool(r["builtin"]),
                        "scopes": scopes})
        return {"count": len(out), "roles": out}

    @router.get("/api/v1/iam/scopes")
    def list_scopes(request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        from ..iam import SCOPES
        return {"count": len(SCOPES), "scopes": sorted(SCOPES)}

    @router.post("/api/v1/iam/roles")
    def create_role(body: RoleBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], "iam.manage")
        try:
            return {"role": iam.create_custom_role(
                name=body.name, description=body.description,
                scopes=body.scopes, created_by=p["actor"])}
        except IAMError as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/iam/simulate")
    def simulate(request: Request, username: str, scope: str,
                 customer_id: str = "", project_id: str = "") -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], "iam.read")
        return iam.simulate(username=username, scope=scope,
                            customer_id=customer_id,
                            project_id=project_id)

    @router.post("/api/v1/master/{kind}/{object_id}/status")
    def master_status(kind: str, object_id: str, body: MasterStatusBody,
                      request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], "master.manage")
        try:
            return master.set_status(kind=kind, object_id=object_id,
                                     status=body.status, actor=p["actor"])
        except MasterDataError as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/master/duplicates")
    def master_duplicates(request: Request) -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], "master.read")
        return master.duplicates()

    return router
