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
    test_run_id: str = ""   # SI3：受信 UAT 路径


class AgentDraftBody(BaseModel):
    text: str
    customer_id: str


class AnomalyBody(BaseModel):
    metric_id: str
    customer_id: str
    op: str = "lt"
    threshold: float = 0
    test_run_id: str = ""   # SI3：受信 UAT 路径


class AnswerBody(BaseModel):
    answer: str


class ComputedMetricBody(BaseModel):
    metric_id: str
    name: str
    formula: str
    test_run_id: str = ""   # SI4：受信 UAT 路径


class DashboardBody(BaseModel):
    name: str
    customer_id: str = ""
    widgets: list = []
    filters: dict = {}
    test_run_id: str = ""   # SI4：受信 UAT 路径


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
        # SI4：metric provenance（受信 test_run 校验 + 同事务写入）。
        from ..scope import ScopeResolver, ScopeViolation
        try:
            mscope = ScopeResolver(store).resolve(
                test_run_id=getattr(body, "test_run_id", "") or "",
                actor_id=p["actor"], source="api")
        except ScopeViolation as e:
            raise HTTPException(409, str(e))
        try:
            return svc.create_computed_metric(
                metric_id=body.metric_id, name=body.name,
                formula=body.formula, actor=p["actor"],
                data_scope=mscope.data_scope,
                test_run_id=mscope.test_run_id)
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
        """数据产品与血缘（SI4：effective operational 口径，禁止
        物理总行数；fail-fast 不吞异常；与运营 Domain API 对账）。"""
        p = require_principal(auth, request, csrf=False)
        # SI4：唯一 effective 口径（与 Gate 3.1 对账共用）。
        from ..analytics import bi_effective_counts
        effc = bi_effective_counts(store._conn)
        products = [
            {"product": "master.customers_v1", "rows":
                effc["md_customer_v1"],
             "lineage": "Import Center → 客户库"},
            {"product": "master.projects_v1", "rows":
                effc["md_project_v1"], "lineage": "Import Center → 项目库"},
            {"product": "master.skus_v1", "rows": effc["md_sku_v1"],
             "lineage": "Import Center → SKU 库"},
            {"product": "survey.responses_v1", "rows":
                effc["survey_response_v1"],
             "lineage": "问卷发布 → 分配 → 填写 → 报表"},
            {"product": "vision.recognition_tasks", "rows":
                effc["recognition_task"],
             "lineage": "五入口 → Command Gateway → 任务台账"},
            {"product": "usage.event_v2", "rows": effc["usage_event_v2"],
             "lineage": "运行节点 → 不可变账本 → 账单（effective）"},
            {"product": "geo.addresses_v1", "rows":
                effc["geo_address_v1"],
             "lineage": "地址导入/地理编码 → 确认 → 路线"},
            {"product": "import.batches_v1", "rows":
                effc["import_batch_v1"],
             "lineage": "模板 → 上传 → dry-run → 提交 → 证据"},
        ]
        return {"count": len(products), "products": products}

    @router.post("/api/v1/analytics/dashboards")
    def create_dashboard(body: DashboardBody, request: Request) -> dict:
        import json as _json
        import uuid as _uuid
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], body.customer_id)
        # SI4：看板继承调用方 scope（受信 test_run 校验）。
        from ..scope import ScopeResolver, ScopeViolation
        try:
            dscope = ScopeResolver(store).resolve(
                test_run_id=body.test_run_id,
                customer_id=body.customer_id, actor_id=p["actor"],
                source="api")
        except ScopeViolation as e:
            raise HTTPException(409, str(e))
        did = "dash-" + _uuid.uuid4().hex[:10]
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        store._conn.execute(
            "INSERT INTO bi_dashboard_v1 (dashboard_id, name,"
            " customer_id, widgets_json, filters_json, status,"
            " created_by, created_at, updated_at, data_scope,"
            " test_run_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (did, body.name, body.customer_id,
             _json.dumps(body.widgets, ensure_ascii=False),
             _json.dumps(body.filters, ensure_ascii=False), "draft",
             p["actor"], now, now, dscope.data_scope,
             dscope.test_run_id))
        store._conn.commit()
        return {"dashboard_id": did, "name": body.name,
                "status": "draft"}

    @router.get("/api/v1/analytics/dashboards")
    def list_dashboards(request: Request,
                        include_fixture: bool = False) -> dict:
        import json as _json
        p = require_principal(auth, request, csrf=False)
        # SI4：运营看板默认排除 fixture（指令 8.3）。
        where = "" if include_fixture else (
            " WHERE COALESCE(data_scope,'operational')='operational'")
        rows = store._conn.execute(
            "SELECT * FROM bi_dashboard_v1" + where +
            " ORDER BY updated_at DESC LIMIT 100").fetchall()
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
        # SI3：服务端解析 scope（fail-closed；同事务写入）
        from ..scope import ScopeResolver, ScopeViolation
        try:
            scope = ScopeResolver(store).resolve(
                test_run_id=body.test_run_id,
                customer_id=body.customer_id, actor_id=p["actor"],
                source="api")
        except ScopeViolation as e:
            raise HTTPException(409, str(e))
        try:
            return {"report": svc.create_report_spec(
                name=body.name, metrics=body.metrics,
                customer_id=body.customer_id, actor=p["actor"],
                dimensions=body.dimensions, nl_query=body.nl_query,
                data_scope=scope.data_scope,
                test_run_id=scope.test_run_id)}
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
        # SI3：运营报表列表默认排除 fixture（指令三.10 同口径）
        reps = [r for r in reps
                if (r.get("data_scope") or "operational")
                == "operational"]
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
        _guard(iam, p["actor"], p["role"],
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
        # SI3：异常对象继承调用方 scope（fail-closed）
        from ..scope import ScopeResolver, ScopeViolation
        try:
            ascope = ScopeResolver(store).resolve(
                test_run_id=body.test_run_id,
                customer_id=body.customer_id, actor_id=p["actor"],
                source="api")
        except ScopeViolation as e:
            raise HTTPException(409, str(e))
        try:
            out = svc.check_anomaly(
                metric_id=body.metric_id, customer_id=body.customer_id,
                op=body.op, threshold=body.threshold, actor=p["actor"],
                data_scope=ascope.data_scope,
                test_run_id=ascope.test_run_id)
        except AnalyticsError as e:
            raise HTTPException(409, str(e))
        # UFC T8：命中异常 → Analytics Agent 生成追问（带 run/work/
        # evidence 链）；人工回答前不得标 resolved。
        if out.get("hit") and out.get("anomaly"):
            ano = out["anomaly"]
            rt = getattr(request.app.state, "agent_runtime", None)
            question = ""
            agent_run = ""
            if rt is not None:
                try:
                    resp = rt.invoke(
                        "analytics_agent",
                        f"指标 {body.metric_id} 异常"
                        f"（observed={out['observed']}，阈值"
                        f" {body.threshold}），请生成追问并查询相关指标",
                        actor=p["actor"], customer_id=body.customer_id,
                        # SI3：追问 Agent 继承异常 scope（fixture 追问
                        # 不得落 operational，指令四.11）
                        test_run_id=ascope.test_run_id)
                    question = str(resp.get("message", ""))[:200]
                    agent_run = resp.get("business_run_id", "")
                except Exception as ae:
                    question = (f"指标 {body.metric_id} 异常，请说明"
                                f"原因（Agent 生成失败：{str(ae)[:60]}）")
            if not question:
                question = (f"指标 {body.metric_id} 观测值"
                            f" {out['observed']} 超过阈值"
                            f" {body.threshold}，请说明原因")
            store._conn.execute(
                "UPDATE bi_anomaly_v1 SET follow_up_question=?,"
                " followup_agent_run_id=? WHERE anomaly_id=?",
                (question, agent_run, ano["anomaly_id"]))
            store._conn.execute(
                "UPDATE work_item_v2 SET title=?, business_summary=?"
                " WHERE work_id=?",
                (f"异常追问：{question[:60]}",
                 f"metric={body.metric_id} observed={out['observed']}"
                 f" agent_run={agent_run}",
                 ano["follow_up_work_id"]))
            store._conn.commit()
            out["anomaly"]["follow_up_question"] = question
            out["anomaly"]["followup_agent_run_id"] = agent_run
        return out

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
