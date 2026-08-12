"""SI3 T5：历史数据追加式纠偏（指令第六节）。

原则：
- 不删除历史；可变业务对象经结构字段修正；
- 不可变 Usage/Evidence 不 UPDATE 原行，经
  scope_attribution_ledger_v1 追加式绑定计算 effective_scope；
- 每条规则写审计（scope_backfill_audit_v1）：规则/来源父对象/
  数量/影响 ID hash/actor/commit/时间；
- 运行时不依赖名称 LIKE（仅结构父链推导）；
- 回填前后 SQLite integrity 必须均 ok。

用法：
  python3 scripts/scope_backfill_v3.py            # dry-run（只报告）
  python3 scripts/scope_backfill_v3.py --apply    # 实际执行
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path

DB = ".platform/platform.sqlite"
FIXTURE = ("uat_fixture", "demo_fixture")
ACTOR = "si3-backfill"
TERMINAL_RUNS = ("succeeded", "failed", "partial_failed", "cancelled",
                 "rejected")
ACTIVE_NODE = ("running", "pending", "queued", "waiting", "paused",
               "started", "in_progress", "scheduled", "waiting_timer",
               "waiting_approval", "waiting_human")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+0800")


def _ids_hash(ids: list[str]) -> str:
    return hashlib.sha256(",".join(sorted(ids)).encode()).hexdigest()[:16]


class Backfill:
    def __init__(self, conn: sqlite3.Connection, apply: bool,
                 commit_ref: str) -> None:
        self.conn = conn
        self.apply = apply
        self.commit_ref = commit_ref
        self.report: dict = {"apply": apply, "commit_ref": commit_ref,
                             "rules": []}

    def audit(self, table: str, rule: str, ids: list[str], scope: str,
              test_run: str, parent_ref: str) -> None:
        if not ids:
            return
        if self.apply:
            self.conn.execute(
                "INSERT INTO scope_backfill_audit_v1 (occurred_at,"
                " actor, table_name, matched_by, matched_count,"
                " assigned_scope, assigned_test_run_id, detail_json)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (_now(), ACTOR, table, rule, len(ids), scope, test_run,
                 json.dumps({"source_parent": parent_ref,
                             "ids_hash": _ids_hash(ids),
                             "commit_ref": self.commit_ref,
                             "ids": ids[:200]},
                            ensure_ascii=False)))
        self.report["rules"].append({
            "rule": rule, "table": table, "count": len(ids),
            "scope": scope, "test_run": test_run,
            "parent": parent_ref, "ids_hash": _ids_hash(ids)})

    # ---------- 推导 ----------

    def tr_of_run(self, run_id: str) -> str:
        r = self.conn.execute(
            "SELECT COALESCE(test_run_id,'') t FROM business_run_v1"
            " WHERE run_id=?", (run_id,)).fetchone()
        return r["t"] if r else ""

    def tr_of_customer(self, cid: str) -> str:
        if not cid:
            return ""
        r = self.conn.execute(
            "SELECT COALESCE(test_run_id,'') t FROM md_customer_v1"
            " WHERE customer_id=?", (cid,)).fetchone()
        if r and r["t"]:
            return r["t"]
        r = self.conn.execute(
            "SELECT test_run_id FROM uat_test_run_v1 WHERE"
            " customer_ids_json LIKE ? ORDER BY created_at DESC"
            " LIMIT 1", ('%"' + cid + '"%',)).fetchone()
        return r["test_run_id"] if r else ""

    # ---------- 规则 ----------

    def r0_runs_by_test_run_registry(self) -> None:
        """结构性规则：run 带已登记 namespace（uat_test_run_v1 存在）
        但自身未标 fixture → 结构性归 fixture（一次性 legacy
        backfill，全量审计）。"""
        rows = self.conn.execute(
            "SELECT r.run_id, r.test_run_id FROM business_run_v1 r"
            " WHERE COALESCE(r.data_scope,'operational')='operational'"
            " AND COALESCE(r.test_run_id,'')!='' AND EXISTS (SELECT 1"
            " FROM uat_test_run_v1 t WHERE t.test_run_id=r.test_run_id)"
        ).fetchall()
        ids = [r["run_id"] for r in rows]
        self.audit("business_run_v1", "r0_runs_by_test_run_registry",
                   ids, "uat_fixture", "per-row",
                   "uat_test_run_v1 registry")
        if self.apply and ids:
            qm = ",".join("?" * len(ids))
            self.conn.execute(
                f"UPDATE business_run_v1 SET data_scope='uat_fixture'"
                f" WHERE run_id IN ({qm})", tuple(ids))

    def r1_work_under_fixture_run(self) -> None:
        rows = self.conn.execute(
            "SELECT w.work_id, w.run_id FROM work_item_v2 w JOIN"
            " business_run_v1 r ON r.run_id=w.run_id WHERE"
            " COALESCE(w.data_scope,'operational')='operational' AND"
            " (r.data_scope IN ('uat_fixture','demo_fixture') OR"
            " COALESCE(r.test_run_id,'')!='')").fetchall()
        ids = [r["work_id"] for r in rows]
        self.audit("work_item_v2", "r1_work_under_fixture_run", ids,
                   "uat_fixture", "", "business_run_v1.run_id")
        if self.apply and ids:
            qm = ",".join("?" * len(ids))
            self.conn.execute(
                f"UPDATE work_item_v2 SET data_scope='uat_fixture',"
                f" visibility='history', superseded_at=? WHERE work_id"
                f" IN ({qm})", (_now(), *ids))

    def r2_media_under_fixture_response(self) -> None:
        rows = self.conn.execute(
            "SELECT m.media_id, COALESCE(r.test_run_id, a.test_run_id,"
            " '') tr FROM survey_media_v1 m JOIN survey_response_v1 r"
            " ON r.response_id=m.response_id LEFT JOIN"
            " survey_assignment_v1 a ON a.assignment_id="
            " r.assignment_id WHERE"
            " COALESCE(m.data_scope,'operational')='operational' AND"
            " (r.data_scope IN ('uat_fixture','demo_fixture') OR"
            " COALESCE(r.test_run_id,'')!='' OR"
            " a.data_scope IN ('uat_fixture','demo_fixture') OR"
            " COALESCE(a.test_run_id,'')!='')").fetchall()
        for r in rows:
            if self.apply:
                self.conn.execute(
                    "UPDATE survey_media_v1 SET data_scope="
                    "'uat_fixture', test_run_id=? WHERE media_id=?",
                    (r["tr"], r["media_id"]))
        self.audit("survey_media_v1", "r2_media_under_fixture_response",
                   [r["media_id"] for r in rows], "uat_fixture",
                   "per-row", "survey_response_v1.response_id")

    def r3_recognition_under_fixture_run(self) -> None:
        rows = self.conn.execute(
            "SELECT t.task_id, t.run_id FROM recognition_task t JOIN"
            " business_run_v1 r ON r.run_id=t.run_id WHERE"
            " COALESCE(t.data_scope,'operational')='operational' AND"
            " (r.data_scope IN ('uat_fixture','demo_fixture') OR"
            " COALESCE(r.test_run_id,'')!='')").fetchall()
        for r in rows:
            tr = self.tr_of_run(r["run_id"])
            if self.apply:
                self.conn.execute(
                    "UPDATE recognition_task SET data_scope="
                    "'uat_fixture', test_run_id=? WHERE task_id=?",
                    (tr, r["task_id"]))
        self.audit("recognition_task",
                   "r3_recognition_under_fixture_run",
                   [r["task_id"] for r in rows], "uat_fixture",
                   "per-row", "business_run_v1.run_id")

    def r4_bi_draft_by_fixture_run(self) -> None:
        rows = self.conn.execute(
            "SELECT b.spec_id, b.version, b.created_at FROM"
            " bi_report_spec_v1 b WHERE b.created_by="
            "'workflow_runtime' AND COALESCE(b.data_scope,"
            "'operational')='operational' AND EXISTS (SELECT 1 FROM"
            " business_run_v1 r WHERE r.data_scope IN ('uat_fixture',"
            "'demo_fixture') AND r.started_at <= b.created_at AND"
            " b.created_at < COALESCE(r.ended_at,'9999') AND NOT"
            " EXISTS (SELECT 1 FROM business_run_v1 o WHERE"
            " o.data_scope NOT IN ('uat_fixture','demo_fixture') AND"
            " o.started_at <= b.created_at AND b.created_at <"
            " COALESCE(o.ended_at,'9999')))").fetchall()
        for r in rows:
            tr_row = self.conn.execute(
                "SELECT COALESCE(test_run_id,'') t FROM business_run_v1"
                " WHERE data_scope IN ('uat_fixture','demo_fixture')"
                " AND started_at <= ? AND ? < COALESCE(ended_at,'9999')"
                " ORDER BY started_at DESC LIMIT 1",
                (r["created_at"], r["created_at"])).fetchone()
            tr = tr_row["t"] if tr_row else ""
            if self.apply:
                self.conn.execute(
                    "UPDATE bi_report_spec_v1 SET data_scope="
                    "'uat_fixture', test_run_id=? WHERE spec_id=? AND"
                    " version=?", (tr, r["spec_id"], r["version"]))
        self.audit("bi_report_spec_v1", "r4_bi_draft_by_fixture_run",
                   [f"{r['spec_id']}@{r['version']}" for r in rows],
                   "uat_fixture", "per-row",
                   "business_run_v1（创建时刻唯一活跃 fixture Run）")

    def r5_failed_agent_under_fixture(self) -> None:
        rows = self.conn.execute(
            "SELECT a.run_id, a.customer_id, a.business_run_id FROM"
            " agent_run_v1 a WHERE a.status='failed' AND"
            " COALESCE(a.data_scope,'operational')='operational' AND"
            " (a.customer_id IN (SELECT customer_id FROM md_customer_v1"
            " WHERE data_scope IN ('uat_fixture','demo_fixture') OR"
            " is_test_fixture=1) OR a.business_run_id IN (SELECT run_id"
            " FROM business_run_v1 WHERE data_scope IN ('uat_fixture',"
            "'demo_fixture') OR COALESCE(test_run_id,'')!=''))"
        ).fetchall()
        for r in rows:
            tr = self.tr_of_run(r["business_run_id"]) \
                or self.tr_of_customer(r["customer_id"])
            if self.apply:
                self.conn.execute(
                    "UPDATE agent_run_v1 SET data_scope='uat_fixture',"
                    " test_run_id=? WHERE run_id=?", (tr, r["run_id"]))
        self.audit("agent_run_v1", "r5_failed_agent_under_fixture",
                   [r["run_id"] for r in rows], "uat_fixture",
                   "per-row", "customer/business_run 父链")

    def r6_fixture_flag_customer(self) -> None:
        rows = self.conn.execute(
            "SELECT customer_id FROM md_customer_v1 WHERE"
            " is_test_fixture=1 AND COALESCE(data_scope,'operational')"
            "='operational'").fetchall()
        for r in rows:
            tr = self.tr_of_customer(r["customer_id"])
            if self.apply:
                self.conn.execute(
                    "UPDATE md_customer_v1 SET data_scope="
                    "'uat_fixture', test_run_id=?, updated_at=?"
                    " WHERE customer_id=?",
                    (tr, _now(), r["customer_id"]))
        self.audit("md_customer_v1", "r6_fixture_flag_customer",
                   [r["customer_id"] for r in rows], "uat_fixture",
                   "per-row", "uat_test_run_v1 registry")

    def r7_children_of_fixture_customer(self) -> None:
        for table, id_col in (("md_project_v1", "project_id"),
                              ("field_task_v1", "task_id"),
                              ("route_plan_v1", "plan_id"),
                              ("user_calendar_v1", "event_id"),
                              ("survey_assignment_v1", "assignment_id"),
                              ("survey_response_v1", "response_id"),
                              ("geo_address_v1", "address_id"),
                              ("geo_employee_v1", "employee_id")):
            try:
                rows = self.conn.execute(
                    f"SELECT t.{id_col} iid, t.customer_id cid FROM"
                    f" {table} t JOIN md_customer_v1 c ON"
                    " c.customer_id=t.customer_id WHERE"
                    " COALESCE(t.data_scope,'operational')"
                    "='operational' AND (c.data_scope IN"
                    " ('uat_fixture','demo_fixture') OR"
                    " c.is_test_fixture=1)").fetchall()
            except sqlite3.OperationalError:
                continue
            for r in rows:
                tr = self.tr_of_customer(r["cid"])
                if self.apply:
                    self.conn.execute(
                        f"UPDATE {table} SET data_scope='uat_fixture',"
                        f" test_run_id=? WHERE {id_col}=?",
                        (tr, r["iid"]))
            self.audit(table, "r7_children_of_fixture_customer",
                       [r["iid"] for r in rows], "uat_fixture",
                       "per-row", "md_customer_v1.customer_id")

    def r8_nodes_under_fixture_run(self) -> None:
        for table in ("workflow_node_execution_v1", "workflow_timer_v1",
                      "workflow_branch_v1"):
            rows = self.conn.execute(
                f"SELECT t.rowid rid, t.run_id FROM {table} t JOIN"
                " business_run_v1 r ON r.run_id=t.run_id WHERE"
                " COALESCE(t.data_scope,'operational')='operational'"
                " AND (r.data_scope IN ('uat_fixture','demo_fixture')"
                " OR COALESCE(r.test_run_id,'')!='')").fetchall()
            for r in rows:
                tr = self.tr_of_run(r["run_id"])
                if self.apply:
                    self.conn.execute(
                        f"UPDATE {table} SET data_scope='uat_fixture',"
                        f" test_run_id=? WHERE rowid=?",
                        (tr, r["rid"]))
            self.audit(table, "r8_nodes_under_fixture_run",
                       [str(r["rid"]) for r in rows], "uat_fixture",
                       "per-row", "business_run_v1.run_id")

    def r9_immutable_attribution(self) -> None:
        # Usage：父 run fixture 或客户 fixture；自身 operational
        rows = self.conn.execute(
            "SELECT u.usage_id, COALESCE(r.test_run_id, c.test_run_id,"
            " '') tr FROM usage_event_v2 u LEFT JOIN business_run_v1 r"
            " ON r.run_id=u.run_id AND u.run_id!='' LEFT JOIN"
            " md_customer_v1 c ON c.customer_id=u.customer_id AND"
            " u.customer_id!='' WHERE COALESCE(u.data_scope,"
            "'operational')='operational' AND NOT EXISTS (SELECT 1"
            " FROM scope_attribution_ledger_v1 a WHERE"
            " a.subject_table='usage_event_v2' AND"
            " a.subject_id=u.usage_id) AND ((r.data_scope IN"
            " ('uat_fixture','demo_fixture') OR"
            " COALESCE(r.test_run_id,'')!='') OR (c.data_scope IN"
            " ('uat_fixture','demo_fixture') OR c.is_test_fixture=1))"
        ).fetchall()
        for r in rows:
            if self.apply:
                self.conn.execute(
                    "INSERT INTO scope_attribution_ledger_v1"
                    " (attribution_id, subject_table, subject_id,"
                    " effective_scope, test_run_id, parent_ref, rule,"
                    " created_by, created_at, commit_ref)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    ("attr-" + uuid.uuid4().hex[:12], "usage_event_v2",
                     r["usage_id"], "uat_fixture", r["tr"],
                     "run/customer 父链", "r9_immutable_attribution",
                     ACTOR, _now(), self.commit_ref))
        self.audit("scope_attribution_ledger_v1",
                   "r9_usage_attribution",
                   [r["usage_id"] for r in rows], "uat_fixture",
                   "per-row", "usage_event_v2（原行不改）")
        # Evidence：父 run fixture
        rows = self.conn.execute(
            "SELECT e.evidence_id, COALESCE(r.test_run_id,'') tr FROM"
            " evidence_bundle_v1 e JOIN business_run_v1 r ON"
            " r.run_id=e.run_id WHERE COALESCE(e.data_scope,"
            "'operational')='operational' AND (r.data_scope IN"
            " ('uat_fixture','demo_fixture') OR"
            " COALESCE(r.test_run_id,'')!='') AND NOT EXISTS"
            " (SELECT 1 FROM scope_attribution_ledger_v1 a WHERE"
            " a.subject_table='evidence_bundle_v1' AND"
            " a.subject_id=e.evidence_id)").fetchall()
        for r in rows:
            if self.apply:
                self.conn.execute(
                    "INSERT INTO scope_attribution_ledger_v1"
                    " (attribution_id, subject_table, subject_id,"
                    " effective_scope, test_run_id, parent_ref, rule,"
                    " created_by, created_at, commit_ref)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    ("attr-" + uuid.uuid4().hex[:12],
                     "evidence_bundle_v1", r["evidence_id"],
                     "uat_fixture", r["tr"], "run 父链",
                     "r9_immutable_attribution", ACTOR, _now(),
                     self.commit_ref))
        self.audit("scope_attribution_ledger_v1",
                   "r9_evidence_attribution",
                   [r["evidence_id"] for r in rows], "uat_fixture",
                   "per-row", "evidence_bundle_v1（原行不改）")

    def r10_terminal_node_convergence(self) -> None:
        rows = self.conn.execute(
            "SELECT n.rowid rid, n.run_id, n.node_id, br.status rs FROM"
            " workflow_node_execution_v1 n JOIN business_run_v1 br ON"
            " br.run_id=n.run_id WHERE br.status IN"
            " ('succeeded','failed','partial_failed','cancelled') AND"
            f" n.status IN {ACTIVE_NODE}").fetchall()
        target_of = {"succeeded": "skipped", "failed": "failed",
                     "partial_failed": "failed", "cancelled":
                     "cancelled", "rejected": "cancelled"}
        for r in rows:
            if self.apply:
                self.conn.execute(
                    "UPDATE workflow_node_execution_v1 SET status=?,"
                    " ended_at=?, error=CASE WHEN COALESCE(error,'')"
                    "='' THEN 'SI3 终态收敛' ELSE error END WHERE"
                    " rowid=?",
                    (target_of[r["rs"]], _now(), r["rid"]))
        self.audit("workflow_node_execution_v1",
                   "r10_terminal_node_convergence",
                   [f"{r['run_id']}:{r['node_id']}" for r in rows],
                   "per-run-terminal", "per-row",
                   "business_run_v1.status")

    def r11_survey_def_by_fixture_lineage(self) -> None:
        rows = self.conn.execute(
            "SELECT DISTINCT s.survey_id, COALESCE(a.test_run_id,"
            " r.test_run_id, '') tr FROM survey_definition_v1 s"
            " LEFT JOIN survey_assignment_v1 a ON a.survey_id="
            " s.survey_id AND (a.data_scope IN ('uat_fixture',"
            "'demo_fixture') OR COALESCE(a.test_run_id,'')!='')"
            " LEFT JOIN survey_response_v1 r ON r.survey_id="
            " s.survey_id AND (r.data_scope IN ('uat_fixture',"
            "'demo_fixture') OR COALESCE(r.test_run_id,'')!='')"
            " WHERE COALESCE(s.data_scope,'operational')='operational'"
            " AND (a.assignment_id IS NOT NULL OR r.response_id IS"
            " NOT NULL)").fetchall()
        for r in rows:
            if self.apply:
                self.conn.execute(
                    "UPDATE survey_definition_v1 SET data_scope="
                    "'uat_fixture', test_run_id=? WHERE survey_id=?",
                    (r["tr"], r["survey_id"]))
        self.audit("survey_definition_v1",
                   "r11_survey_def_by_fixture_lineage",
                   [r["survey_id"] for r in rows], "uat_fixture",
                   "per-row", "assignment/response 父链")

    def r13_legacy_namespace_backfill(self) -> None:
        """一次性 legacy backfill（指令六.7：名称识别仅允许一次性
        且人工可审计）：从 work 标题/run params 提取 namespace，
        必须命中 uat_test_run_v1 registry（结构校验）才生效。"""
        namespaces = [r["test_run_id"] for r in self.conn.execute(
            "SELECT test_run_id FROM uat_test_run_v1").fetchall()]
        run_hits: dict[str, str] = {}
        work_hits: dict[str, str] = {}
        for r in self.conn.execute(
                "SELECT run_id, params_json FROM business_run_v1 WHERE"
                " COALESCE(data_scope,'operational')='operational' AND"
                " COALESCE(test_run_id,'')=''").fetchall():
            blob = r["params_json"] or ""
            for ns in namespaces:
                if ns in blob:
                    run_hits[r["run_id"]] = ns
                    break
        for r in self.conn.execute(
                "SELECT work_id, run_id, title FROM work_item_v2 WHERE"
                " COALESCE(data_scope,'operational')='operational' AND"
                " COALESCE(visibility,'current')='current'").fetchall():
            title = r["title"] or ""
            for ns in namespaces:
                if ns in title:
                    work_hits[r["work_id"]] = ns
                    if r["run_id"]:
                        run_hits.setdefault(r["run_id"], ns)
                    break
        self.audit("business_run_v1", "r13_legacy_namespace_backfill",
                   list(run_hits), "uat_fixture", "per-row",
                   "uat_test_run_v1 registry（名称一次性回填）")
        self.audit("work_item_v2", "r13_legacy_namespace_backfill",
                   list(work_hits), "uat_fixture", "per-row",
                   "uat_test_run_v1 registry（名称一次性回填）")
        if self.apply:
            for run_id, ns in run_hits.items():
                self.conn.execute(
                    "UPDATE business_run_v1 SET data_scope="
                    "'uat_fixture', test_run_id=? WHERE run_id=?",
                    (ns, run_id))
            for wid, ns in work_hits.items():
                self.conn.execute(
                    "UPDATE work_item_v2 SET data_scope='uat_fixture',"
                    " visibility='history', superseded_at=? WHERE"
                    " work_id=?", (_now(), wid))

    def r14_parent_chain_children(self) -> None:
        """历史行：父 run 已 fixture 但子对象（work/agent_run/node/
        timer/branch）自身仍 operational → 沿父链结构性修正。"""
        rows = self.conn.execute(
            "SELECT w.work_id iid, r.test_run_id tr FROM work_item_v2 w"
            " JOIN business_run_v1 r ON r.run_id=w.run_id WHERE"
            " COALESCE(w.data_scope,'operational')='operational' AND"
            " (r.data_scope IN ('uat_fixture','demo_fixture') OR"
            " COALESCE(r.test_run_id,'')!='')").fetchall()
        for r in rows:
            if self.apply:
                self.conn.execute(
                    "UPDATE work_item_v2 SET data_scope='uat_fixture',"
                    " visibility='history', superseded_at=? WHERE"
                    " work_id=?", (_now(), r["iid"]))
        self.audit("work_item_v2", "r14_parent_chain_children",
                   [r["iid"] for r in rows], "uat_fixture", "per-row",
                   "business_run_v1.run_id")
        rows = self.conn.execute(
            "SELECT a.run_id iid, r.test_run_id tr FROM agent_run_v1 a"
            " JOIN business_run_v1 r ON r.run_id=a.business_run_id"
            " WHERE COALESCE(a.data_scope,'operational')='operational'"
            " AND (r.data_scope IN ('uat_fixture','demo_fixture') OR"
            " COALESCE(r.test_run_id,'')!='')").fetchall()
        for r in rows:
            if self.apply:
                self.conn.execute(
                    "UPDATE agent_run_v1 SET data_scope='uat_fixture',"
                    " test_run_id=? WHERE run_id=?",
                    (r["tr"], r["iid"]))
        self.audit("agent_run_v1", "r14_parent_chain_children",
                   [r["iid"] for r in rows], "uat_fixture", "per-row",
                   "business_run_v1.run_id(business_run_id)")
        for table in ("workflow_node_execution_v1", "workflow_timer_v1",
                      "workflow_branch_v1"):
            rows = self.conn.execute(
                f"SELECT t.rowid rid, r.test_run_id tr FROM {table} t"
                " JOIN business_run_v1 r ON r.run_id=t.run_id WHERE"
                " COALESCE(t.data_scope,'operational')='operational'"
                " AND (r.data_scope IN ('uat_fixture','demo_fixture')"
                " OR COALESCE(r.test_run_id,'')!='')").fetchall()
            for r in rows:
                if self.apply:
                    self.conn.execute(
                        f"UPDATE {table} SET data_scope='uat_fixture',"
                        f" test_run_id=? WHERE rowid=?",
                        (r["tr"], r["rid"]))
            self.audit(table, "r14_parent_chain_children",
                       [str(r["rid"]) for r in rows], "uat_fixture",
                       "per-row", "business_run_v1.run_id")

    def r12_finance_under_fixture_customer(self) -> None:
        for table, id_col in (("fin_invoice_v1", "invoice_id"),
                              ("fin_invoice_line_v1", "invoice_id"),
                              ("fin_adjustment_v1", "adjustment_id")):
            try:
                rows = self.conn.execute(
                    f"SELECT t.{id_col} iid, t.customer_id cid FROM"
                    f" {table} t JOIN md_customer_v1 c ON"
                    " c.customer_id=t.customer_id WHERE"
                    " COALESCE(t.data_scope,'operational')"
                    "='operational' AND (c.data_scope IN"
                    " ('uat_fixture','demo_fixture') OR"
                    " c.is_test_fixture=1)").fetchall()
            except sqlite3.OperationalError:
                continue
            for r in rows:
                tr = self.tr_of_customer(r["cid"])
                if self.apply:
                    self.conn.execute(
                        f"UPDATE {table} SET data_scope='uat_fixture',"
                        f" test_run_id=? WHERE {id_col}=?",
                        (tr, r["iid"]))
            self.audit(table, "r12_finance_under_fixture_customer",
                       [r["iid"] for r in rows], "uat_fixture",
                       "per-row", "md_customer_v1.customer_id")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--db", default=DB)
    args = ap.parse_args()
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True,
            text=True, timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001
        head = ""
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    bf = Backfill(conn, args.apply, commit_ref=head)
    for fn in (bf.r0_runs_by_test_run_registry,
               bf.r13_legacy_namespace_backfill,
               bf.r1_work_under_fixture_run,
               bf.r2_media_under_fixture_response,
               bf.r3_recognition_under_fixture_run,
               bf.r4_bi_draft_by_fixture_run,
               bf.r5_failed_agent_under_fixture,
               bf.r6_fixture_flag_customer,
               bf.r7_children_of_fixture_customer,
               bf.r8_nodes_under_fixture_run,
               bf.r9_immutable_attribution,
               bf.r10_terminal_node_convergence,
               bf.r11_survey_def_by_fixture_lineage,
               bf.r14_parent_chain_children,
               bf.r12_finance_under_fixture_customer):
        fn()
    if args.apply:
        conn.commit()
        ic = conn.execute("PRAGMA integrity_check").fetchone()[0]
        bf.report["post_integrity"] = ic
        assert ic == "ok"
    conn.close()
    out = Path(".eval/scope_v3/backfill_report"
               + ("_apply" if args.apply else "_dryrun") + ".json")
    out.write_text(json.dumps(bf.report, ensure_ascii=False, indent=2))
    total = sum(r["count"] for r in bf.report["rules"])
    print(json.dumps({r["rule"]: r["count"]
                      for r in bf.report["rules"]},
                     ensure_ascii=False, indent=2))
    print(f"\ntotal={total} apply={args.apply} → {out}")


if __name__ == "__main__":
    main()
