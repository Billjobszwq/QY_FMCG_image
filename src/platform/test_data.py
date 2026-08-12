"""UFC T4：UAT fixture 结构性隔离与归档服务。

- 不删除任何历史数据：只做追加式标记（data_scope/visibility/
  superseded_at/test_run_id）；
- 隔离按结构字段生效（名字前缀只是遗留回填的识别线索）；
- operational 投影默认排除全部 uat_fixture；当前一次 UAT 以
  visibility=current 在"测试与证据"端点可查，结束后归档为 history。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

LEGACY_PREFIXES = ("uatv2_", "uat_fixture_v3", "uat-cust")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TestDataService:
    def __init__(self, store: Any) -> None:
        self.store = store

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
        """归档一次 UAT：visibility=history + superseded_at（行保留，
        仍可审计）。"""
        conn = self.store._conn
        now = _now()
        conn.execute(
            "UPDATE work_item_v2 SET visibility='history',"
            " superseded_at=? WHERE data_scope='uat_fixture' AND"
            " (run_id IN (SELECT run_id FROM business_run_v1 WHERE"
            " test_run_id=?) OR customer_id LIKE ?)",
            (now, namespace, namespace + "%"))
        conn.execute(
            "UPDATE business_run_v1 SET data_scope='uat_fixture'"
            " WHERE test_run_id=? OR customer_id LIKE ?",
            (namespace, namespace + "%"))
        # 运行期新建的 work（customer 可能为空）：按已标记 fixture
        # 的 run 追加式归档。
        conn.execute(
            "UPDATE work_item_v2 SET data_scope='uat_fixture',"
            " visibility='history', superseded_at=? WHERE"
            " data_scope='operational' AND run_id IN (SELECT run_id"
            " FROM business_run_v1 WHERE data_scope='uat_fixture')",
            (now,))
        conn.commit()
        self._audit(actor, "test_data.archived", namespace, {})
        return {"namespace": namespace, "archived_at": now}

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
        """operational 投影中的 UAT 残留：visibility=current 的
        fixture work 数（归档后应为 0）。"""
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
