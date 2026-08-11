"""ABOSV2 Phase F：Analytics/BI 服务层（03-DOMAIN-PACKS-SPEC §4）。

- 语义层：注册制 Metric（只从平台事实表聚合，禁止任意 SQL）；
- ReportSpec 版本化：draft→approved→published；异常回答后报表刷新
  生成新版本（不覆盖旧报告）；
- Analytics Agent：NL→指标映射只命中已注册 metric（fail-closed），
  产出 draft，发布必须人工批准；
- 异常规则：observed 越界 → 异常 + 追问 WorkItem → 回答 → 报表刷新。
"""
from __future__ import annotations

import json
import uuid
from typing import Any


class AnalyticsError(Exception):
    pass


def _new_id(prefix: str) -> str:
    return f"{prefix}-" + uuid.uuid4().hex[:12]


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# 注册制指标定义（source 表 + 聚合方式，全部来自平台事实表）
METRIC_DEFS: tuple[tuple[str, str, str], ...] = (
    ("recognition.photos", "识别照片数", "usage:recognition_photo:sum"),
    ("recognition.compute_ms", "识别计算时长(ms)",
     "usage:model_compute_ms:sum"),
    ("recognition.tasks", "识别任务数", "recognition_tasks:count"),
    ("survey.submitted", "问卷已提交数", "survey:submitted:count"),
    ("survey.avg_score", "问卷平均分", "survey:avg_score"),
    ("workflow.runs", "工作流运行数", "workflow_runs:count"),
)


class AnalyticsService:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.seed_metrics()

    # ---------- 语义层 ----------

    def seed_metrics(self) -> None:
        for mid, name, definition in METRIC_DEFS:
            self.store._conn.execute(
                "INSERT OR IGNORE INTO bi_metric_v1 (metric_id, name,"
                " definition_json, created_at) VALUES (?,?,?,?)",
                (mid, name, json.dumps({"source": definition}), _now()))
        self.store._conn.commit()

    def list_metrics(self) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM bi_metric_v1 ORDER BY metric_id").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["definition"] = json.loads(d["definition_json"])
            out.append(d)
        return out

    def evaluate_metric(self, metric_id: str, *, customer_id: str,
                        project_id: str = "") -> float:
        """只从注册定义求值；未注册指标 fail-closed。"""
        row = self.store._conn.execute(
            "SELECT definition_json FROM bi_metric_v1 WHERE metric_id=?",
            (metric_id,)).fetchone()
        if row is None:
            raise AnalyticsError(
                f"指标未注册（禁止任意查询）: {metric_id}")
        source = json.loads(row["definition_json"])["source"]
        conn = self.store._conn
        if source.startswith("usage:"):
            _, unit, agg = source.split(":")
            where = "WHERE unit=? AND customer_id=?"
            params: list = [unit, customer_id]
            if project_id:
                where += " AND project_id=?"; params.append(project_id)
            val = conn.execute(
                f"SELECT {'sum(quantity)' if agg == 'sum' else 'count(*)'}"
                f" v FROM usage_event_v2 {where}", params).fetchone()["v"]
            return float(val or 0)
        if source == "recognition_tasks:count":
            val = conn.execute(
                "SELECT count(*) v FROM recognition_task t"
                " JOIN business_run_v1 r ON r.run_id=t.run_id"
                " WHERE r.customer_id=?", (customer_id,)).fetchone()["v"]
            return float(val or 0)
        if source == "survey:submitted:count":
            val = conn.execute(
                "SELECT count(*) v FROM survey_response_v1"
                " WHERE customer_id=? AND status='submitted'",
                (customer_id,)).fetchone()["v"]
            return float(val or 0)
        if source == "survey:avg_score":
            rows = conn.execute(
                "SELECT scores_json FROM survey_response_v1"
                " WHERE customer_id=? AND status='submitted'",
                (customer_id,)).fetchall()
            totals = [json.loads(r["scores_json"] or "{}").get("total", 0)
                      for r in rows]
            return float(sum(totals) / len(totals)) if totals else 0.0
        if source == "workflow_runs:count":
            val = conn.execute(
                "SELECT count(*) v FROM business_run_v1"
                " WHERE command_kind='workflow.run' AND customer_id=?",
                (customer_id,)).fetchone()["v"]
            return float(val or 0)
        raise AnalyticsError(f"未知指标来源: {source}")

    # ---------- ReportSpec 生命周期 ----------

    def create_report_spec(self, *, name: str, metrics: list[str],
                           customer_id: str, actor: str,
                           dimensions: list | None = None,
                           nl_query: str = "",
                           note: str = "") -> dict:
        for m in metrics:
            if not any(d["metric_id"] == m for d in self.list_metrics()):
                raise AnalyticsError(f"指标未注册: {m}（fail-closed）")
        spec_id = _new_id("rep")
        now = _now()
        self.store._conn.execute(
            "INSERT INTO bi_report_spec_v1 (spec_id, version, name, status,"
            " customer_id, metrics_json, dimensions_json, nl_query, note,"
            " created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (spec_id, 1, name, "draft", customer_id,
             json.dumps(metrics), json.dumps(dimensions or []),
             nl_query, note, actor, now, now))
        self.store._conn.commit()
        return self.get_report_spec(spec_id)

    def get_report_spec(self, spec_id: str,
                        version: int | None = None) -> dict:
        if version is None:
            row = self.store._conn.execute(
                "SELECT * FROM bi_report_spec_v1 WHERE spec_id=?"
                " ORDER BY version DESC LIMIT 1", (spec_id,)).fetchone()
        else:
            row = self.store._conn.execute(
                "SELECT * FROM bi_report_spec_v1 WHERE spec_id=? AND"
                " version=?", (spec_id, version)).fetchone()
        if row is None:
            raise AnalyticsError(f"报表不存在: {spec_id}")
        d = dict(row)
        d["metrics"] = json.loads(d["metrics_json"])
        d["dimensions"] = json.loads(d["dimensions_json"])
        return d

    def list_report_specs(self) -> list[dict]:
        """ABOSV3-P0-004：每个 spec 只出现一次（取最新版本）；
        不得对每个版本行再取 latest 造成 v2 重复、v1 消失。
        历史版本经 list_report_versions 单独可查。"""
        rows = self.store._conn.execute(
            "SELECT spec_id, max(version) v FROM bi_report_spec_v1"
            " GROUP BY spec_id ORDER BY spec_id").fetchall()
        return [self.get_report_spec(r["spec_id"], r["v"]) for r in rows]

    def list_report_versions(self, spec_id: str) -> list[dict]:
        """同一 spec 的全部版本（v1 不得消失；旧版不可被覆盖）。"""
        rows = self.store._conn.execute(
            "SELECT version FROM bi_report_spec_v1 WHERE spec_id=?"
            " ORDER BY version", (spec_id,)).fetchall()
        if not rows:
            raise AnalyticsError(f"报表不存在: {spec_id}")
        return [self.get_report_spec(spec_id, r["version"]) for r in rows]

    def approve_report(self, spec_id: str, *, actor: str) -> dict:
        d = self.get_report_spec(spec_id)
        if d["status"] != "draft":
            raise AnalyticsError(f"只有 draft 可批准（当前 {d['status']}）")
        self.store._conn.execute(
            "UPDATE bi_report_spec_v1 SET status='approved', updated_at=?"
            " WHERE spec_id=? AND version=?",
            (_now(), spec_id, d["version"]))
        self.store._conn.commit()
        return self.get_report_spec(spec_id)

    def publish_report(self, spec_id: str, *, actor: str) -> dict:
        d = self.get_report_spec(spec_id)
        if d["status"] != "approved":
            raise AnalyticsError("发布必须先经人工批准")
        self.store._conn.execute(
            "UPDATE bi_report_spec_v1 SET status='published',"
            " published_at=?, updated_at=? WHERE spec_id=? AND version=?",
            (_now(), _now(), spec_id, d["version"]))
        self.store._conn.commit()
        return self.get_report_spec(spec_id)

    def evaluate_report(self, spec_id: str, *,
                        version: int | None = None) -> dict:
        d = self.get_report_spec(spec_id, version)
        values = {}
        for m in d["metrics"]:
            values[m] = self.evaluate_metric(
                m, customer_id=d["customer_id"])
        breakdown: dict[str, dict] = {}
        if "project" in d["dimensions"]:
            rows = self.store._conn.execute(
                "SELECT DISTINCT project_id FROM usage_event_v2"
                " WHERE customer_id=? AND project_id != ''",
                (d["customer_id"],)).fetchall()
            for r in rows:
                pid = r["project_id"]
                breakdown[pid] = {}
                for m in d["metrics"]:
                    try:
                        breakdown[pid][m] = self.evaluate_metric(
                            m, customer_id=d["customer_id"],
                            project_id=pid)
                    except AnalyticsError:
                        breakdown[pid][m] = None
        return {"spec_id": spec_id, "version": d["version"],
                "status": d["status"], "customer_id": d["customer_id"],
                "values": values, "breakdown": breakdown,
                "generated_at": _now()}

    # ---------- Analytics Agent（NL→draft，仅注册指标） ----------

    def agent_draft(self, text: str, *, customer_id: str,
                    actor: str) -> dict:
        t = text or ""
        metrics: list[str] = []
        if "识别" in t or "照片" in t:
            metrics += ["recognition.photos", "recognition.compute_ms",
                        "recognition.tasks"]
        if "问卷" in t or "评分" in t or "巡检" in t:
            metrics += ["survey.submitted", "survey.avg_score"]
        if "工作流" in t:
            metrics += ["workflow.runs"]
        if not metrics:
            return {"note": "未识别到已注册指标对应的业务意图；"
                            "Analytics Agent 不得生成任意查询",
                    "metrics": [], "draft": None,
                    "requires_human_approval": True}
        draft = self.create_report_spec(
            name=f"Agent 草稿：{(t or '未命名')[:24]}", metrics=metrics,
            customer_id=customer_id, actor=actor,
            dimensions=["project"] if "项目" in t or "拆分" in t else [],
            nl_query=t, note="Analytics Agent 生成；发布必须人工批准")
        return {"note": "已映射到已注册指标（无任意 SQL）",
                "metrics": metrics, "draft": draft,
                "requires_human_approval": True}

    # ---------- 异常与追问 ----------

    def check_anomaly(self, *, metric_id: str, customer_id: str,
                      op: str, threshold: float,
                      actor: str) -> dict:
        observed = self.evaluate_metric(metric_id, customer_id=customer_id)
        hit = {"lt": observed < threshold, "gt": observed > threshold,
               "le": observed <= threshold, "ge": observed >= threshold,
               }.get(op)
        if hit is None:
            raise AnalyticsError(f"不支持的操作符: {op}")
        if not hit:
            return {"anomaly": None, "observed": observed,
                    "threshold": threshold, "hit": False}
        anomaly_id = _new_id("ano")
        work = self.store.insert_work_item_v2({
            "work_id": _new_id("work"), "status": "todo",
            "owner_type": "human", "owner_id": "analyst",
            "title": f"异常追问：{metric_id} {op} {threshold}",
            "business_summary": f"observed={observed}",
            "subject_type": "bi_anomaly", "subject_id": anomaly_id})
        self.store._conn.execute(
            "INSERT INTO bi_anomaly_v1 (anomaly_id, metric_id,"
            " customer_id, rule_json, observed, threshold, status,"
            " follow_up_work_id, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (anomaly_id, metric_id, customer_id,
             json.dumps({"op": op, "threshold": threshold}), observed,
             threshold, "open", work["work_id"], _now()))
        self.store._conn.commit()
        return {"anomaly": self.get_anomaly(anomaly_id),
                "observed": observed, "threshold": threshold, "hit": True}

    def get_anomaly(self, anomaly_id: str) -> dict:
        row = self.store._conn.execute(
            "SELECT * FROM bi_anomaly_v1 WHERE anomaly_id=?",
            (anomaly_id,)).fetchone()
        if row is None:
            raise AnalyticsError(f"anomaly 不存在: {anomaly_id}")
        d = dict(row)
        d["rule"] = json.loads(d["rule_json"])
        return d

    def list_anomalies(self, *, customer_id: str = "") -> list[dict]:
        if customer_id:
            rows = self.store._conn.execute(
                "SELECT anomaly_id FROM bi_anomaly_v1 WHERE customer_id=?"
                " ORDER BY created_at", (customer_id,)).fetchall()
        else:
            rows = self.store._conn.execute(
                "SELECT anomaly_id FROM bi_anomaly_v1"
                " ORDER BY created_at").fetchall()
        return [self.get_anomaly(r["anomaly_id"]) for r in rows]

    def answer_anomaly(self, anomaly_id: str, *, answer: str,
                       actor: str) -> dict:
        """回答追问 → 异常关闭 → 相关报表刷新（新版本，不覆盖旧报告）。"""
        a = self.get_anomaly(anomaly_id)
        if a["status"] != "open":
            raise AnalyticsError("异常已关闭")
        self.store._conn.execute(
            "INSERT INTO bi_followup_answer_v1 (anomaly_id, answer, actor,"
            " created_at) VALUES (?,?,?,?)",
            (anomaly_id, answer, actor, _now()))
        self.store._conn.execute(
            "UPDATE bi_anomaly_v1 SET status='resolved', resolved_at=?"
            " WHERE anomaly_id=?", (_now(), anomaly_id))
        # 工作项关闭
        self.store.set_work_item_v2_status(a["follow_up_work_id"], "done")
        # 报表刷新：包含该指标的最新报表生成新版本（draft，重新批准发布）
        refreshed = None
        rows = self.store._conn.execute(
            "SELECT spec_id, version, name, customer_id, metrics_json,"
            " dimensions_json, nl_query FROM bi_report_spec_v1"
            " ORDER BY spec_id, version").fetchall()
        latest: dict[str, dict] = {}
        for r in rows:
            if a["metric_id"] in json.loads(r["metrics_json"]) and \
                    r["customer_id"] == a["customer_id"]:
                latest[r["spec_id"]] = dict(r)
        for spec_id, r in latest.items():
            now = _now()
            self.store._conn.execute(
                "INSERT INTO bi_report_spec_v1 (spec_id, version, name,"
                " status, customer_id, metrics_json, dimensions_json,"
                " nl_query, note, created_by, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (spec_id, r["version"] + 1, r["name"], "draft",
                 r["customer_id"], r["metrics_json"],
                 r["dimensions_json"], r["nl_query"],
                 f"异常 {anomaly_id} 已回答并刷新：{answer[:60]}",
                 actor, now, now))
            refreshed = self.get_report_spec(spec_id)
        self.store._conn.commit()
        self.store.rebuild_work_projection()
        return {"anomaly": self.get_anomaly(anomaly_id),
                "refreshed_report": refreshed}
