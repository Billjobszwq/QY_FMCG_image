"""UFC T4 / SI2 T5：测试与证据 API（UAT fixture 隔离/归档/查询/
Test Run 上下文/一致性扫描）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..auth import AuthService, require_principal
from ..iam import IAMService
from ..test_data import TestDataService


class MarkBody(BaseModel):
    namespace: str
    customer_ids: list[str]


class TestRunBody(BaseModel):
    namespace: str
    customer_ids: list[str] = []


class ArchiveBody(BaseModel):
    namespace: str


def _is_admin(iam: IAMService, actor: str, role: str) -> bool:
    if role == "admin":
        return True
    roles = set(iam.roles_of(actor))
    return "platform_admin" in roles or "owner" in roles


def create_test_data_router(store: Any, svc: TestDataService,
                            iam: IAMService,
                            auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["test-data"])

    @router.get("/api/v1/test-data/namespaces")
    def namespaces(request: Request) -> dict:
        p = require_principal(auth, request, csrf=False)
        return {"namespaces": svc.list_namespaces(),
                "operational_residue": svc.operational_residue(),
                "operational_residue_full": svc.operational_residue_full()}

    @router.get("/api/v1/test-data/center")
    def center(request: Request) -> dict:
        """SI2 T5：测试与证据中心总览（fixture 历史完整可审计；
        不提供不可恢复删除）。"""
        p = require_principal(auth, request, csrf=False)
        return svc.center_summary()

    @router.post("/api/v1/test-data/run")
    def create_test_run(body: TestRunBody, request: Request) -> dict:
        """SI2：UAT 必须先建 Test Run 上下文，再在其内部创建对象。"""
        p = require_principal(auth, request, csrf=True)
        if not _is_admin(iam, p["actor"], p["role"]):
            raise HTTPException(403, "仅平台管理员可创建 UAT 上下文")
        try:
            return svc.create_test_run_context(
                body.namespace, customer_ids=body.customer_ids,
                actor=p["actor"])
        except ValueError as e:
            raise HTTPException(400, str(e))

    @router.get("/api/v1/test-data/work")
    def fixture_work(request: Request, namespace: str = "",
                     limit: int = 200) -> dict:
        p = require_principal(auth, request, csrf=False)
        rows = svc.list_fixture_work(namespace=namespace,
                                     limit=min(limit, 500))
        return {"count": len(rows), "work": rows,
                "note": "fixture 行保留可审计，不进运营投影"}

    @router.post("/api/v1/test-data/mark")
    def mark(body: MarkBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        if not _is_admin(iam, p["actor"], p["role"]):
            raise HTTPException(403, "仅平台管理员可标记测试数据")
        try:
            return svc.mark_namespace(body.namespace,
                                      customer_ids=body.customer_ids,
                                      actor=p["actor"])
        except ValueError as e:
            raise HTTPException(400, str(e))

    @router.post("/api/v1/test-data/archive")
    def archive(body: ArchiveBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        if not _is_admin(iam, p["actor"], p["role"]):
            raise HTTPException(403, "仅平台管理员可归档测试数据")
        return svc.archive_namespace(body.namespace, actor=p["actor"])

    @router.post("/api/v1/test-data/converge-legacy")
    def converge_legacy(request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        if not _is_admin(iam, p["actor"], p["role"]):
            raise HTTPException(403, "仅平台管理员可回填遗留 fixture")
        n = svc.converge_legacy_fixtures(actor=p["actor"])
        return {"converged_customers": n,
                "operational_residue": svc.operational_residue()}

    return router
