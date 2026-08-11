"""ABOSV2 Phase F：财务与计费 API（finance.read scope + 客户作用域）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..auth import AuthService, require_principal
from ..finance import FinanceError, FinanceService
from ..iam import IAMService


class ContractBody(BaseModel):
    customer_id: str
    kind: str = "usage"
    rate_card_id: str = "rc_standard"


class InvoiceBody(BaseModel):
    customer_id: str
    period: str
    contract_id: str = ""
    include_subscription: bool = True


class AdjustBody(BaseModel):
    kind: str
    amount: float
    reason: str


class RateCardBody(BaseModel):
    lines: list[dict]


def _platform(iam: IAMService, actor: str, session_role: str) -> bool:
    if session_role == "admin":
        return True
    roles = set(iam.roles_of(actor))
    return "platform_admin" in roles or "owner" in roles


def _guard(iam: IAMService, actor: str, session_role: str,
           customer_id: str = "") -> None:
    if _platform(iam, actor, session_role):
        return
    if not iam.authorize(actor, "finance.read", customer_id=customer_id):
        raise HTTPException(
            403, f"无权访问财务数据（customer={customer_id or '未指定'}）")


def create_finance_router(store: Any, svc: FinanceService,
                          iam: IAMService,
                          auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["finance"])

    def _wrap(fn):
        def wrap(*a, **kw):
            try:
                return fn(*a, **kw)
            except FinanceError as e:
                raise HTTPException(409, str(e))
        return wrap

    @router.get("/api/v1/finance/rate-cards/{rate_card_id}")
    def rate_card(rate_card_id: str, request: Request,
                  version: int | None = None) -> dict:
        p = require_principal(auth, request, csrf=False)
        return {"rate_card": _wrap(svc.get_rate_card)(rate_card_id,
                                                      version)}

    @router.post("/api/v1/finance/rate-cards/{rate_card_id}/new-version")
    def new_version(rate_card_id: str, body: RateCardBody,
                    request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        # 价格变更属高风险：仅平台角色
        if not _platform(iam, p["actor"], p["role"]):
            raise HTTPException(403, "价格变更仅限平台角色")
        return {"rate_card": _wrap(svc.new_rate_card_version)(
            rate_card_id, lines=body.lines, actor=p["actor"])}

    @router.post("/api/v1/finance/contracts")
    def contract(body: ContractBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], body.customer_id)
        return {"contract": _wrap(svc.create_contract)(
            customer_id=body.customer_id, kind=body.kind,
            rate_card_id=body.rate_card_id)}

    @router.get("/api/v1/finance/contracts")
    def contracts(request: Request, customer_id: str) -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], customer_id)
        rows = svc.list_contracts(customer_id=customer_id)
        return {"count": len(rows), "contracts": rows}

    @router.post("/api/v1/finance/invoices/generate")
    def generate(body: InvoiceBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], body.customer_id)
        return {"invoice": _wrap(svc.generate_invoice)(
            customer_id=body.customer_id, period=body.period,
            contract_id=body.contract_id,
            include_subscription=body.include_subscription,
            actor=p["actor"])}

    @router.get("/api/v1/finance/invoices")
    def invoices(request: Request, customer_id: str) -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], customer_id)
        rows = svc.list_invoices(customer_id=customer_id)
        return {"count": len(rows), "invoices": rows}

    @router.get("/api/v1/finance/invoices/{invoice_id}")
    def invoice(invoice_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=False)
        try:
            inv = svc.get_invoice(invoice_id)
        except FinanceError as e:
            raise HTTPException(404, str(e))
        _guard(iam, p["actor"], p["role"], inv["customer_id"])
        return {"invoice": inv}

    @router.post("/api/v1/finance/invoices/{invoice_id}/issue")
    def issue(invoice_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        return {"invoice": _wrap(svc.issue_invoice)(invoice_id,
                                                    actor=p["actor"])}

    @router.post("/api/v1/finance/invoices/{invoice_id}/adjust")
    def adjust(invoice_id: str, body: AdjustBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        return {"invoice": _wrap(svc.adjust_invoice)(
            invoice_id, kind=body.kind, amount=body.amount,
            reason=body.reason, actor=p["actor"])}

    @router.post("/api/v1/finance/invoices/{invoice_id}/settle")
    def settle(invoice_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        return {"invoice": _wrap(svc.settle_invoice)(invoice_id,
                                                     actor=p["actor"])}

    return router
