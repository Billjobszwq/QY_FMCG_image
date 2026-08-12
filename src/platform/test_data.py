"""UFC T4 / SI2 T5：UAT fixture 结构性隔离与归档服务（测试与证据中心后端）。

- 不删除任何历史数据：只做追加式标记（data_scope/visibility/
  superseded_at/test_run_id）；
- 隔离按结构字段生效（名字前缀只是遗留回填的识别线索，运行时
  禁止依赖名称模式）；
- operational 投影默认排除全部 uat_fixture；当前一次 UAT 以
  visibility=current 在"测试与证据"端点可查，结束后归档为 history；
- SI2：UAT 必须先 create_test_run_context（先建 Test Run，再在其
  内部创建对象），归档按 test_run_id 结构化执行全 Domain。
"""
from __future__ import annotations

import json as _json
from datetime import datetime, timezone
from typing import Any

from .scope import ScopedQuery

LEGACY_PREFIXES = ("uatv2_", "uat_fixture_v3", "uat-cust")

# SI2 T3：带结构化 scope 列、需随归档一并处理的 Domain 表（与
# 02-DOMAIN-SCOPE-MATRIX / 迁移 051 同源）。
_SCOPED_DOMAIN_TABLES = (
    "md_project_v1", "md_sku_v1",
    "field_task_v1", "route_plan_v1", "geofence_event_v1",
    "user_calendar_v1",
    "survey_definition_v1", "survey_assignment_v1", "survey_response_v1",
    "survey_media_v1",
    "workflow_definition_v1",
    "agent_run_v1", "recognition_task",
    "usage_event_v2", "evidence_bundle_v1",
    "bi_report_spec_v1", "bi_anomaly_v1",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FixtureTestDataService:
    """UAT fixture 隔离/归档/审计（类名避免 pytest 收集误判，
    SI2-009；保留 TestDataService 别名兼容旧引用）。"""

    __test__ = False  # 双保险：任何收集器不得视作测试类

    def __init__(self, store: Any) -> None:
        self.store = store

    # ---------- Test Run 上下文（SI2：先建上下文再建对象） ----------

    def create_test_run_context(self, namespace: str, *,
                                customer_ids: list[str],
                                actor: str = "system") -> dict:
        """创建一次 UAT 的结构化作用域上下文：所有后续对象必须
        携带 test_run_id=namespace 或从父对象继承（禁止后补标）。

        SI3：namespace 不可覆盖（禁止 INSERT OR REPLACE，指令四.9）：
        重复请求仅当内容完全一致时幂等返回，否则 409 冲突。"""
        if not namespace:
            raise ValueError("namespace 不得为空")
        conn = self.store._conn
        existing = conn.execute(
            "SELECT customer_ids_json, status, created_by FROM"
            " uat_test_run_v1 WHERE test_run_id=?",
            (namespace,)).fetchone()
        want = sorted(customer_ids or [])
        if existing is not None:
            have = sorted(_json.loads(
                existing["customer_ids_json"] or "[]"))
            if have != want:
                raise ValueError(
                    "409 test_run 已存在且内容不一致（namespace 不可"
                    f"覆盖）: {namespace} customers={have} → 请求"
                    f" {want}")
            return {"test_run_id": namespace, "namespace": namespace,
                    "customers": have,
                    "status": existing["status"]}
        conn.execute(
            "INSERT INTO uat_test_run_v1 (test_run_id,"
            " namespace, status, customer_ids_json, created_by,"
            " created_at) VALUES (?,?,?,?,?,?)",
            (namespace, namespace, "current",
             _json.dumps(customer_ids or []), actor, _now()))
        if customer_ids:
            qm = ",".join("?" * len(customer_ids))
            conn.execute(
                f"UPDATE md_customer_v1 SET data_scope='uat_fixture',"
                f" test_run_id=?, updated_at=? WHERE customer_id IN"
                f" ({qm})",
                (namespace, _now(), *customer_ids))
        conn.commit()
        self._audit(actor, "test_data.context_created", namespace,
                    {"customers": customer_ids})
        return {"test_run_id": namespace, "namespace": namespace,
                "customers": list(customer_ids), "status": "current"}

    # ---------- 标记 / 归档 ----------

    def mark_namespace(self, namespace: str, *,
                       customer_ids: list[str],
                       actor: str = "system") -> dict:
        """把一次 UAT 的客户/run/work 结构性标记为 uat_fixture
        （visibility=current，进行中）。"""
        conn = self.store._conn
        if not customer_ids:
            raise ValueError("customer_ids 不得为空")
        qm = ",".join("?" * len(customer_ids))
        conn.execute(
            f"UPDATE md_customer_v1 SET data_scope='uat_fixture',"
            f" updated_at=? WHERE customer_id IN ({qm})",
            (_now(), *customer_ids))
        conn.execute(
            f"UPDATE business_run_v1 SET data_scope='uat_fixture',"
            f" test_run_id=? WHERE customer_id IN ({qm})",
            (namespace, *customer_ids))
        conn.execute(
            f"UPDATE work_item_v2 SET data_scope='uat_fixture',"
            f" visibility='current' WHERE customer_id IN ({qm})",
            tuple(customer_ids))
        # 经 run 关联的 work（approval 子待办等可能 customer 为空）
        conn.execute(
            "UPDATE work_item_v2 SET data_scope='uat_fixture',"
            " visibility='current' WHERE run_id IN (SELECT run_id FROM"
            " business_run_v1 WHERE test_run_id=?)", (namespace,))
        conn.commit()
        self._audit(actor, "test_data.marked", namespace,
                    {"customers": customer_ids})
        return {"namespace": namespace,
                "customers": len(customer_ids)}

    def archive_namespace(self, namespace: str, *,
                          actor: str = "system") -> dict:
        """归档一次 UAT（全 Domain，按 test_run_id 结构化；不删行）。

        运行时不依赖名称前缀：只处理 test_run_id=namespace 的行与
        该上下文登记的 fixture 客户行；operational 对象（哪怕名称含
        UAT）不受影响。
        """
        conn = self.store._conn
        now = _now()
        # 1) work_item / business_run（既有结构字段）
        conn.execute(
            "UPDATE work_item_v2 SET visibility='history',"
            " superseded_at=? WHERE data_scope='uat_fixture' AND"
            " run_id IN (SELECT run_id FROM business_run_v1 WHERE"
            " test_run_id=?)",
            (now, namespace))
        # 兼容旧数据：客户归属该 namespace 登记的 fixture 客户
        cust_row = conn.execute(
            "SELECT customer_ids_json FROM uat_test_run_v1 WHERE"
            " test_run_id=?", (namespace,)).fetchone()
        cids = _json.loads(cust_row["customer_ids_json"]) if cust_row else []
        if cids:
            qm = ",".join("?" * len(cids))
            conn.execute(
                f"UPDATE work_item_v2 SET visibility='history',"
                f" superseded_at=? WHERE data_scope='uat_fixture' AND"
                f" customer_id IN ({qm})", (now, *cids))
            conn.execute(
                f"UPDATE business_run_v1 SET data_scope='uat_fixture',"
                f" test_run_id=? WHERE customer_id IN ({qm}) AND"
                " COALESCE(test_run_id,'')='' AND"
                " data_scope='uat_fixture'", (namespace, *cids))
        # 2) 全 Domain 结构化归档：带 test_run_id 的行结构性地属于
        # fixture（不得 operational；运行时不依赖名称）。
        # SI3：fail-fast——归档异常不得吞（指令九.5）。
        for table in _SCOPED_DOMAIN_TABLES:
            conn.execute(
                f"UPDATE {table} SET data_scope='uat_fixture' WHERE"
                " test_run_id=?", (namespace,))
        # node/timer/branch 随 run 归档（审计可见）
        for table in ("workflow_node_execution_v1", "workflow_timer_v1",
                      "workflow_branch_v1"):
            conn.execute(
                f"UPDATE {table} SET data_scope='uat_fixture' WHERE"
                " test_run_id=?", (namespace,))
        # 3) Test Run 上下文收尾
        conn.execute(
            "UPDATE uat_test_run_v1 SET status='archived', archived_at=?"
            " WHERE test_run_id=?", (now, namespace))
        conn.commit()
        self._audit(actor, "test_data.archived", namespace, {})
        return {"namespace": namespace, "archived_at": now}

    def operational_residue_full(self) -> dict[str, int]:
        """全 Domain operational 投影中的 fixture 残留（归档后应为
        空 dict）。Gate 2.1 直接消费；返回显式计数（0 也是 0）。"""
        return ScopedQuery(self.store).operational_leakage()

    # ---------- 测试与证据中心（SI2 T5） ----------

    def center_summary(self) -> dict:
        """测试中心总览：每个 Test Run 的跨 Domain 对象计数/状态/
        归档时间与一致性扫描（只读；fixture 历史完整可审计）。"""
        conn = self.store._conn
        sq = ScopedQuery(self.store)
        runs = [dict(r) for r in conn.execute(
            "SELECT * FROM uat_test_run_v1 ORDER BY created_at DESC"
        ).fetchall()]
        count_tables = {
            "runs": ("business_run_v1", None),
            "work_items": ("work_item_v2", None),
            "customers": ("md_customer_v1", None),
            "projects": ("md_project_v1", None),
            "field_tasks": ("field_task_v1", None),
            "surveys": ("survey_definition_v1", None),
            "survey_assignments": ("survey_assignment_v1", None),
            "survey_responses": ("survey_response_v1", None),
            "workflows": ("workflow_definition_v1", None),
            "agent_runs": ("agent_run_v1", None),
            "recognition_tasks": ("recognition_task", None),
            "bi_reports": ("bi_report_spec_v1", None),
        }
        for r in runs:
            r["customer_ids"] = _json.loads(r.get(
                "customer_ids_json") or "[]")
            counts: dict[str, int] = {}
            for key, (table, _x) in count_tables.items():
                try:
                    if key == "customers":
                        qm = ",".join("?" * len(r["customer_ids"])) \
                            if r["customer_ids"] else "''"
                        counts[key] = conn.execute(
                            f"SELECT count(*) c FROM {table} WHERE"
                            f" customer_id IN ({qm})",
                            tuple(r["customer_ids"])).fetchone()["c"] \
                            if r["customer_ids"] else 0
                    else:
                        if key == "work_items":
                            counts[key] = conn.execute(
                                "SELECT count(*) c FROM work_item_v2"
                                " WHERE run_id IN (SELECT run_id FROM"
                                " business_run_v1 WHERE test_run_id=?)",
                                (r["test_run_id"],)).fetchone()["c"]
                        else:
                            counts[key] = conn.execute(
                                f"SELECT count(*) c FROM {table} WHERE"
                                " test_run_id=?",
                                (r["test_run_id"],)).fetchone()["c"]
                except Exception:
                    counts[key] = 0
            r["objects"] = counts
        audit = [dict(r) for r in conn.execute(
            "SELECT occurred_at, actor, table_name, matched_by,"
            " matched_count, assigned_scope, assigned_test_run_id FROM"
            " scope_backfill_audit_v1 ORDER BY id DESC LIMIT 100"
        ).fetchall()]
        return {"test_runs": runs,
                "backfill_audit": audit,
                "scope_scan": {
                    "operational_leakage": sq.operational_leakage(),
                    "fixture_missing_test_run":
                        sq.fixture_missing_test_run(),
                    "parent_child_mismatch": sq.parent_child_mismatch(),
                    "recovery_residue": sq.recovery_residue(),
                    "work_residue_current": self.operational_residue()},
                "unresolved": conn.execute(
                    "SELECT count(*) c FROM business_run_v1 WHERE"
                    " data_scope='unresolved_fixture_scope'"
                ).fetchone()["c"]}

    def converge_legacy_fixtures(self, *, actor: str = "system") -> int:
        """遗留 uat* 客户追加式回填为 fixture 并归档（不删除）。"""
        conn = self.store._conn
        rows = conn.execute(
            "SELECT customer_id FROM md_customer_v1 WHERE"
            " data_scope='operational' AND (is_test_fixture=1 OR "
            + " OR ".join("customer_id LIKE ?"
                          for _ in LEGACY_PREFIXES) + ")",
            tuple(p + "%" for p in LEGACY_PREFIXES)).fetchall()
        cids = [r["customer_id"] for r in rows]
        now = _now()
        if cids:
            qm = ",".join("?" * len(cids))
            conn.execute(
                f"UPDATE md_customer_v1 SET data_scope='uat_fixture',"
                f" updated_at=? WHERE customer_id IN ({qm})",
                (now, *cids))
            conn.execute(
                f"UPDATE business_run_v1 SET data_scope='uat_fixture'"
                f" WHERE customer_id IN ({qm})", tuple(cids))
            conn.execute(
                f"UPDATE work_item_v2 SET data_scope='uat_fixture',"
                f" visibility='history', superseded_at=? WHERE"
                f" customer_id IN ({qm})", (now, *cids))
        conn.execute(
            "UPDATE work_item_v2 SET data_scope='uat_fixture',"
            " visibility='history', superseded_at=? WHERE run_id IN"
            " (SELECT run_id FROM business_run_v1 WHERE data_scope="
            "'uat_fixture') AND data_scope='operational'", (now,))
        # UFC：无 customer 关联但标题含 UAT namespace 标记的 work/run
        # （如工作流运行）也追加式归档。
        title_markers = ("%uatv2_%", "%uat_fixture_v3%", "%UAT2 %",
                         "%UAT预演%", "%UAT 预演%")
        conn.execute(
            "UPDATE work_item_v2 SET data_scope='uat_fixture',"
            " visibility='history', superseded_at=? WHERE"
            " data_scope='operational' AND (" + " OR ".join(
                "title LIKE ?" for _ in title_markers) + ")",
            (now, *title_markers))
        conn.execute(
            "UPDATE business_run_v1 SET data_scope='uat_fixture'"
            " WHERE data_scope='operational' AND run_id IN"
            " (SELECT run_id FROM work_item_v2 WHERE data_scope="
            "'uat_fixture')")
        conn.commit()
        self._audit(actor, "test_data.legacy_converged", "*",
                    {"customers": cids})
        return len(cids)

    # ---------- 查询 ----------

    def list_namespaces(self) -> list[dict]:
        """测试与证据：按 namespace/客户聚合 fixture 运行。"""
        conn = self.store._conn
        rows = conn.execute(
            "SELECT COALESCE(NULLIF(br.test_run_id,''),"
            " w.customer_id) ns, count(DISTINCT br.run_id) runs,"
            " count(DISTINCT w.work_id) works,"
            " min(w.visibility) visibility,"
            " max(w.created_at) last_at"
            " FROM work_item_v2 w LEFT JOIN business_run_v1 br"
            " ON br.run_id=w.run_id"
            " WHERE w.data_scope='uat_fixture' GROUP BY ns"
            " ORDER BY last_at DESC").fetchall()
        return [{"namespace": r["ns"], "runs": r["runs"],
                 "works": r["works"],
                 "visibility": ("history" if r["visibility"] == "history"
                                else "current"),
                 "last_at": r["last_at"]} for r in rows]

    def list_fixture_work(self, *, namespace: str = "",
                          limit: int = 200) -> list[dict]:
        where = "WHERE w.data_scope='uat_fixture'"
        params: tuple = ()
        if namespace:
            where += (" AND (w.customer_id LIKE ? OR w.run_id IN"
                      " (SELECT run_id FROM business_run_v1 WHERE"
                      " test_run_id=?))")
            params = (namespace + "%", namespace)
        rows = self.store._conn.execute(
            f"SELECT w.work_id, w.run_id, w.customer_id, w.status,"
            f" w.title, w.visibility, w.superseded_at, w.created_at"
            f" FROM work_item_v2 w {where} ORDER BY w.created_at DESC"
            f" LIMIT ?", (*params, limit)).fetchall()
        return [dict(r) for r in rows]

    def operational_residue(self) -> int:
        """operational 投影中的 UAT 残留（work 域；归档后应为 0）。"""
        return self.store._conn.execute(
            "SELECT count(*) c FROM work_item_v2 WHERE data_scope="
            "'uat_fixture' AND visibility='current'").fetchone()["c"]

    def _audit(self, actor: str, action: str, resource: str,
               detail: dict) -> None:
        try:
            import json
            self.store._conn.execute(
                "INSERT INTO iam_audit_event_v1 (occurred_at, actor_id,"
                " action, resource, detail_json, customer_id)"
                " VALUES (?,?,?,?,?,'')",
                (_now(), actor, action, resource,
                 json.dumps(detail, ensure_ascii=False)))
            self.store._conn.commit()
        except Exception:
            pass


# 兼容别名：旧代码引用 TestDataService；__test__=False 防止 pytest
# 收集警告（SI2-009）。
TestDataService = FixtureTestDataService
