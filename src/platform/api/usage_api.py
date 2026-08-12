"""ABOSV3 T10：客户级 Usage 工作台 API。

- 按客户/项目/单位/日期统计不可变 usage_event_v2；
- 每行下钻 run/work/evidence/model/rate version；
- 趋势（按日）、异常（日峰值 > 3×均值）、未归属、CSV 导出。
"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from ..auth import AuthService, require_principal
from ..iam import IAMService


def _platform(iam: IAMService, actor: str, session_role: str) -> bool:
    if session_role == "admin":
        return True
    roles = set(iam.roles_of(actor))
    return "platform_admin" in roles or "owner" in roles


def create_usage_router(store: Any, iam: IAMService,
                        auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["usage"])

    def _check(p, customer_id: str) -> None:
        if _platform(iam, p["actor"], p["role"]):
            return
        if not iam.authorize(p["actor"], "finance.read",
                             customer_id=customer_id):
            raise HTTPException(
                403, f"无权查看该客户 Usage（{customer_id or '未指定'}）")

    @router.get("/api/v1/usage/summary")
    def summary(request: Request, customer_id: str = "",
                project_id: str = "") -> dict:
        p = require_principal(auth, request, csrf=False)
        _check(p, customer_id)
        where, params = [], []
        if customer_id:
            where.append("customer_id=?"); params.append(customer_id)
        if project_id:
            where.append("project_id=?"); params.append(project_id)
        w = (" WHERE " + " AND ".join(where)) if where else ""
        conn = store._conn
        by_unit = [dict(r) for r in conn.execute(
            f"SELECT unit, sum(quantity) total, count(*) n FROM"
            f" usage_event_v2{w} GROUP BY unit ORDER BY unit",
            params).fetchall()]
        by_date = [dict(r) for r in conn.execute(
            f"SELECT substr(occurred_at,1,10) day, count(*) n,"
            f" sum(quantity) total FROM usage_event_v2{w}"
            " GROUP BY day ORDER BY day DESC LIMIT 30",
            params).fetchall()]
        # 异常：单日事件数 > 3× 均值（诚实简单规则，标注口径）
        anomalies = []
        if len(by_date) >= 3:
            avg = sum(d["n"] for d in by_date) / len(by_date)
            for d in by_date:
                if avg > 0 and d["n"] > 3 * avg:
                    anomalies.append({"day": d["day"], "count": d["n"],
                                      "avg": round(avg, 1),
                                      "rule": "day_count > 3×mean"})
        unattributed = conn.execute(
            "SELECT count(*) c FROM usage_event_v2 WHERE"
            " customer_id=''").fetchone()["c"]
        return {"customer_id": customer_id or "*",
                "by_unit": by_unit, "by_date": by_date,
                "anomalies": anomalies,
                "unattributed": unattributed,
                "note": "账本不可变；调整经 finance adjustments"
                        "（append-only）"}

    @router.get("/api/v1/usage/rows")
    def rows(request: Request, customer_id: str = "",
             unit: str = "", limit: int = 50) -> dict:
        p = require_principal(auth, request, csrf=False)
        _check(p, customer_id)
        where, params = [], []
        if customer_id:
            where.append("customer_id=?"); params.append(customer_id)
        if unit:
            where.append("unit=?"); params.append(unit)
        w = (" WHERE " + " AND ".join(where)) if where else ""
        rs = [dict(r) for r in store._conn.execute(
            f"SELECT usage_id, unit, quantity, run_id, work_id, node,"
            f" capability, model, profile_id, tier, project_id,"
            f" source_evidence, occurred_at FROM usage_event_v2{w}"
            " ORDER BY occurred_at DESC LIMIT ?",
            params + [min(limit, 500)]).fetchall()]
        # 下钻：每行关联 run 状态与证据 bundle
        for r in rs:
            run = store._conn.execute(
                "SELECT status, current_node, evidence_bundle_id FROM"
                " business_run_v1 WHERE run_id=?",
                (r["run_id"],)).fetchone() if r["run_id"] else None
            r["run_status"] = run["status"] if run else None
            r["evidence_bundle_id"] = (run["evidence_bundle_id"]
                                       if run else None)
        return {"count": len(rs), "rows": rs}

    @router.get("/api/v1/usage/export.csv")
    def export_csv(request: Request, customer_id: str = "") -> Response:
        p = require_principal(auth, request, csrf=False)
        _check(p, customer_id)
        where, params = "", []
        if customer_id:
            where, params = "WHERE customer_id=?", [customer_id]
        rs = store._conn.execute(
            f"SELECT usage_id, occurred_at, customer_id, project_id,"
            f" unit, quantity, run_id, work_id, node, capability,"
            f" profile_id, tier, source_evidence FROM usage_event_v2"
            f" {where} ORDER BY occurred_at DESC LIMIT 5000",
            params).fetchall()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["usage_id", "occurred_at", "customer_id",
                    "project_id", "unit", "quantity", "run_id",
                    "work_id", "node", "capability", "profile_id",
                    "tier", "source_evidence"])
        for r in rs:
            w.writerow([r["usage_id"], r["occurred_at"],
                        r["customer_id"], r["project_id"], r["unit"],
                        r["quantity"], r["run_id"], r["work_id"],
                        r["node"], r["capability"], r["profile_id"],
                        r["tier"], r["source_evidence"]])
        return Response(
            content=buf.getvalue().encode("utf-8-sig"),
            media_type="text/csv",
            headers={"content-disposition":
                     'attachment; filename="usage_export.csv"'})

    @router.get("/api/v1/usage/budgets")
    def budgets(request: Request, customer_id: str = "") -> dict:
        """预算：来自项目库 budget_json（total/spent 口径诚实标注）。"""
        p = require_principal(auth, request, csrf=False)
        _check(p, customer_id)
        where, params = "", []
        if customer_id:
            where, params = "WHERE customer_id=?", [customer_id]
        rows = store._conn.execute(
            f"SELECT project_id, customer_id, name, budget_json FROM"
            f" md_project_v1 {where}", params).fetchall()
        import json as _json
        out = []
        for r in rows:
            b = _json.loads(r["budget_json"] or "{}")
            spent = store._conn.execute(
                "SELECT count(*) c FROM usage_event_v2 WHERE"
                " project_id=?", (r["project_id"],)).fetchone()["c"]
            out.append({"project_id": r["project_id"],
                        "customer_id": r["customer_id"],
                        "name": r["name"],
                        "budget_total": b.get("total"),
                        "usage_events": spent,
                        "note": "spent 为事件计数口径（非金额）"})
        return {"count": len(out), "budgets": out}

    return router
