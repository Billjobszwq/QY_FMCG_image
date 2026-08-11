"""ABOSV2 Phase F：Analytics/BI API（语义层/报表/异常追问）。

analytics.read scope + customer 作用域；Agent 只映射注册指标。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..analytics import AnalyticsError, AnalyticsService
from ..auth import AuthService, require_principal
from ..iam import IAMService


class ReportBody(BaseModel):
    name: str
    metrics: list[str] = []
    customer_id: str
    dimensions: list[str] = []
    nl_query: str = ""


class AgentDraftBody(BaseModel):
    text: str
    customer_id: str


class AnomalyBody(BaseModel):
    metric_id: str
    customer_id: str
    op: str = "lt"
    threshold: float = 0


class AnswerBody(BaseModel):
    answer: str


def _platform(iam: IAMService, actor: str, session_role: str) -> bool:
    if session_role == "admin":
        return True
    roles = set(iam.roles_of(actor))
    return "platform_admin" in roles or "owner" in roles


def _guard(iam: IAMService, actor: str, session_role: str,
           customer_id: str = "") -> None:
    if _platform(iam, actor, session_role):
        return
    if not iam.authorize(actor, "analytics.read", customer_id=customer_id):
        raise HTTPException(
            403, f"无权访问分析数据（customer={customer_id or '未指定'}）")


def create_analytics_router(store: Any, svc: AnalyticsService,
                            iam: IAMService,
                            auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["analytics"])

    @router.get("/api/v1/analytics/metrics")
    def metrics(request: Request) -> dict:
        p = require_principal(auth, request, csrf=False)
        rows = svc.list_metrics()
        return {"count": len(rows), "metrics": rows}

    @router.post("/api/v1/analytics/reports")
    def create_report(body: ReportBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], body.customer_id)
        try:
            return {"report": svc.create_report_spec(
                name=body.name, metrics=body.metrics,
                customer_id=body.customer_id, actor=p["actor"],
                dimensions=body.dimensions, nl_query=body.nl_query)}
        except AnalyticsError as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/analytics/agent-draft")
    def agent_draft(body: AgentDraftBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], body.customer_id)
        return svc.agent_draft(body.text, customer_id=body.customer_id,
                               actor=p["actor"])

    @router.get("/api/v1/analytics/reports")
    def list_reports(request: Request) -> dict:
        p = require_principal(auth, request, csrf=False)
        reps = svc.list_report_specs()
        if not _platform(iam, p["actor"], p["role"]):
            limit = iam.visible_customers(p["actor"])
            reps = [r for r in reps
                    if limit is None or r["customer_id"] == limit]
        return {"count": len(reps), "reports": reps}

    @router.post("/api/v1/analytics/reports/{spec_id}/approve")
    def approve(spec_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            d = svc.get_report_spec(spec_id)
        except AnalyticsError as e:
            raise HTTPException(404, str(e))
        _guard(iam, p["actor"], p["role"], d["customer_id"])
        try:
            return {"report": svc.approve_report(spec_id, actor=p["actor"])}
        except AnalyticsError as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/analytics/reports/{spec_id}/publish")
    def publish(spec_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            d = svc.get_report_spec(spec_id)
        except AnalyticsError as e:
            raise HTTPException(404, str(e))
        _guard(iam, p["actor"], p["role"], d["customer_id"])
        try:
            return {"report": svc.publish_report(spec_id, actor=p["actor"])}
        except AnalyticsError as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/analytics/reports/{spec_id}/evaluate")
    def evaluate(spec_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=False)
        try:
            d = svc.get_report_spec(spec_id)
        except AnalyticsError as e:
            raise HTTPException(404, str(e))
        _guard(iam, p["actor"], p["role"], d["customer_id"])
        try:
            return svc.evaluate_report(spec_id)
        except AnalyticsError as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/analytics/anomalies/check")
    def check(body: AnomalyBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], body.customer_id)
        try:
            return svc.check_anomaly(
                metric_id=body.metric_id, customer_id=body.customer_id,
                op=body.op, threshold=body.threshold, actor=p["actor"])
        except AnalyticsError as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/analytics/anomalies")
    def anomalies(request: Request, customer_id: str = "") -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], customer_id)
        cid = customer_id
        if not _platform(iam, p["actor"], p["role"]):
            limit = iam.visible_customers(p["actor"])
            cid = limit if limit and limit != "__none__" else "__none__"
        rows = svc.list_anomalies(customer_id=cid)
        return {"count": len(rows), "anomalies": rows}

    @router.post("/api/v1/analytics/anomalies/{anomaly_id}/answer")
    def answer(anomaly_id: str, body: AnswerBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            a = svc.get_anomaly(anomaly_id)
        except AnalyticsError as e:
            raise HTTPException(404, str(e))
        _guard(iam, p["actor"], p["role"], a["customer_id"])
        try:
            return svc.answer_anomaly(anomaly_id, answer=body.answer,
                                      actor=p["actor"])
        except AnalyticsError as e:
            raise HTTPException(409, str(e))

    return router
