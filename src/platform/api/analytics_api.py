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


class ComputedMetricBody(BaseModel):
    metric_id: str
    name: str
    formula: str


class DashboardBody(BaseModel):
    name: str
    customer_id: str = ""
    widgets: list = []
    filters: dict = {}


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

    # ---- ABOSV3 T9：受限公式计算指标 + 下钻 + Dashboard ----

    @router.post("/api/v1/analytics/metrics/computed")
    def computed_metric(body: ComputedMetricBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"])
        try:
            return svc.create_computed_metric(
                metric_id=body.metric_id, name=body.name,
                formula=body.formula, actor=p["actor"])
        except AnalyticsError as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/analytics/metrics/{metric_id}/evaluate")
    def evaluate_metric(metric_id: str, request: Request,
                        customer_id: str) -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], customer_id)
        from ..rate_limit import enforce
        enforce(request, "bi.query", p["actor"])
        try:
            v = svc.evaluate_metric(metric_id, customer_id=customer_id)
        except AnalyticsError as e:
            raise HTTPException(409, str(e))
        return {"metric_id": metric_id, "customer_id": customer_id,
                "value": v}

    @router.get("/api/v1/analytics/metrics/{metric_id}/drilldown")
    def drilldown(metric_id: str, request: Request,
                  customer_id: str, limit: int = 20) -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], customer_id)
        from ..rate_limit import enforce
        enforce(request, "bi.query", p["actor"])
        try:
            return svc.drilldown(metric_id, customer_id=customer_id,
                                 limit=min(limit, 100))
        except AnalyticsError as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/analytics/data-products")
    def data_products(request: Request) -> dict:
        """数据产品与血缘（事实表计数 + 导入批次溯源）。"""
        p = require_principal(auth, request, csrf=False)
        conn = store._conn

        def count(table: str) -> int:
            try:
                return conn.execute(
                    f"SELECT count(*) c FROM {table}").fetchone()["c"]
            except Exception:
                return 0

        products = [
            {"product": "master.customers_v1", "rows":
                count("md_customer_v1"), "lineage": "Import Center → 客户库"},
            {"product": "master.projects_v1", "rows":
                count("md_project_v1"), "lineage": "Import Center → 项目库"},
            {"product": "master.skus_v1", "rows": count("md_sku_v1"),
             "lineage": "Import Center → SKU 库"},
            {"product": "survey.responses_v1", "rows":
                count("survey_response_v1"),
             "lineage": "问卷发布 → 分配 → 填写 → 报表"},
            {"product": "vision.recognition_tasks", "rows":
                count("recognition_task"),
             "lineage": "五入口 → Command Gateway → 任务台账"},
            {"product": "usage.event_v2", "rows":
                count("usage_event_v2"),
             "lineage": "运行节点 → 不可变账本 → 账单"},
            {"product": "geo.addresses_v1", "rows":
                count("geo_address_v1"),
             "lineage": "地址导入/地理编码 → 确认 → 路线"},
            {"product": "import.batches_v1", "rows":
                count("import_batch_v1"),
             "lineage": "模板 → 上传 → dry-run → 提交 → 证据"},
        ]
        return {"count": len(products), "products": products}

    @router.post("/api/v1/analytics/dashboards")
    def create_dashboard(body: DashboardBody, request: Request) -> dict:
        import json as _json
        import uuid as _uuid
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], body.customer_id)
        did = "dash-" + _uuid.uuid4().hex[:10]
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        store._conn.execute(
            "INSERT INTO bi_dashboard_v1 (dashboard_id, name,"
            " customer_id, widgets_json, filters_json, status,"
            " created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (did, body.name, body.customer_id,
             _json.dumps(body.widgets, ensure_ascii=False),
             _json.dumps(body.filters, ensure_ascii=False), "draft",
             p["actor"], now, now))
        store._conn.commit()
        return {"dashboard_id": did, "name": body.name,
                "status": "draft"}

    @router.get("/api/v1/analytics/dashboards")
    def list_dashboards(request: Request) -> dict:
        import json as _json
        p = require_principal(auth, request, csrf=False)
        rows = store._conn.execute(
            "SELECT * FROM bi_dashboard_v1 ORDER BY updated_at DESC"
            " LIMIT 100").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["widgets"] = _json.loads(d.pop("widgets_json"))
            d["filters"] = _json.loads(d.pop("filters_json"))
            out.append(d)
        return {"count": len(out), "dashboards": out}

    @router.put("/api/v1/analytics/dashboards/{dashboard_id}")
    def update_dashboard(dashboard_id: str, body: DashboardBody,
                         request: Request) -> dict:
        import json as _json
        from datetime import datetime, timezone
        p = require_principal(auth, request, csrf=True)
        n = store._conn.execute(
            "UPDATE bi_dashboard_v1 SET name=?, widgets_json=?,"
            " filters_json=?, updated_at=? WHERE dashboard_id=?",
            (body.name,
             _json.dumps(body.widgets, ensure_ascii=False),
             _json.dumps(body.filters, ensure_ascii=False),
             datetime.now(timezone.utc).isoformat(), dashboard_id))
        if n.rowcount != 1:
            raise HTTPException(404, f"dashboard 不存在: {dashboard_id}")
        store._conn.commit()
        return {"dashboard_id": dashboard_id, "status": "saved"}

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
            limit = iam.visible_customers(p["actor"]) or []
            reps = [r for r in reps
                    if r["customer_id"] in limit]
        return {"count": len(reps), "reports": reps}

    @router.get("/api/v1/analytics/reports/{spec_id}/versions")
    def report_versions(spec_id: str, request: Request) -> dict:
        """ABOSV3-P0-004：v1/v2 分别可见、可比较；旧版不被覆盖。"""
        p = require_principal(auth, request, csrf=False)
        try:
            versions = svc.list_report_versions(spec_id)
        except AnalyticsError as e:
            raise HTTPException(404, str(e))
        _guard(iam, p["actor"], p["role"], "analytics.read",
               customer_id=versions[-1]["customer_id"])
        return {"spec_id": spec_id, "count": len(versions),
                "versions": versions}

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
            limit = iam.visible_customers(p["actor"]) or []
            rows = svc.list_anomalies(customer_id=cid)
            if not cid:
                rows = [r for r in rows
                        if r.get("customer_id") in limit]
        else:
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
