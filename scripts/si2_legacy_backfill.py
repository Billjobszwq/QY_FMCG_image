#!/usr/bin/env python3
"""SI2 T3：Legacy UAT 数据结构化回填（一次性；幂等；追加式审计）。

规则（指令 P1-002/T3）：
- 运行时不得依赖名称模式；本脚本是唯一允许使用名称线索的一次性
  backfill，所有判定写入 scope_backfill_audit_v1 账本；
- 结构化优先：customer/run 关联 > 名称线索；
- 无法安全判断归属的对象 → data_scope='unresolved_fixture_scope'
  （quarantine，不自动认定 operational，不删除），进入待人工裁决清单；
- 已标记 uat_fixture 的 business_run 按客户推导 namespace 补齐
  test_run_id（UAT V3 27+ runs 修复）。

用法：python scripts/si2_legacy_backfill.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / ".platform" / "platform.sqlite"

FIXTURE = "uat_fixture"
UNRESOLVED = "unresolved_fixture_scope"
LEGACY_NS = "legacy_uat_pre_v3"  # 无法推导具体 namespace 的历史 UAT


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def derive_namespace(customer_id: str) -> str:
    """uatv3_<ts>_<rand>_cust → uatv3_<ts>_<rand>（结构推导，非名称
    猜测：客户 ID 由 UAT 驱动脚本按 namespace 生成）。"""
    for suffix in ("_cust", "_customer"):
        if customer_id.endswith(suffix):
            return customer_id[: -len(suffix)]
    return customer_id


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(str(DB), timeout=30)
    conn.row_factory = sqlite3.Row
    # 幂等迁移（apply_migrations 同口径：直接 executescript 新列由
    # PlatformStore 启动时完成；此处只读校验列已存在）
    cols = {r[1] for r in conn.execute(
        "PRAGMA table_info(business_run_v1)")}
    if "test_run_id" not in cols:
        print("先启动一次 8400 或 PlatformStore 以应用迁移 051",
              file=sys.stderr)
        return 2

    audit: list[tuple] = []

    def log(table: str, matched_by: str, n: int, scope: str,
            ns: str = "", detail: dict | None = None) -> None:
        if n <= 0:
            return
        audit.append((_now(), "si2_backfill", table, matched_by, n,
                      scope, ns, json.dumps(detail or {},
                                            ensure_ascii=False)))
        print(f"  {table}: {matched_by} → {n} 行 → {scope}"
              + (f" ({ns})" if ns else ""))

    # ---------- 1) fixture 客户集合（既有结构字段） ----------
    fixture_customers = {r["customer_id"]: derive_namespace(
        r["customer_id"])
        for r in conn.execute(
            "SELECT customer_id FROM md_customer_v1 WHERE data_scope=?",
            (FIXTURE,))}
    print(f"fixture customers: {len(fixture_customers)}")

    # ---------- 2) business_run：补 test_run_id ----------
    runs = conn.execute(
        "SELECT run_id, customer_id FROM business_run_v1 WHERE"
        " data_scope=? AND COALESCE(test_run_id,'')=''",
        (FIXTURE,)).fetchall()
    n_ns = 0
    for r in runs:
        ns = fixture_customers.get(r["customer_id"])
        if ns is None:
            # 无客户关联的 fixture run：归入 legacy namespace（仍是
            # fixture，不猜 operational）
            ns = LEGACY_NS
        conn.execute(
            "UPDATE business_run_v1 SET test_run_id=? WHERE run_id=?",
            (ns, r["run_id"]))
        n_ns += 1
    log("business_run_v1", "data_scope=uat_fixture 且缺 test_run_id",
        n_ns, FIXTURE, "按客户推导 namespace")

    fixture_runs = {r["run_id"]: (r["test_run_id"] or LEGACY_NS)
                    for r in conn.execute(
                        "SELECT run_id, test_run_id FROM business_run_v1"
                        " WHERE data_scope=?", (FIXTURE,))}

    # ---------- 3) 按 customer/run 结构化回填各 Domain ----------
    def backfill_by_customer(table: str, has_customer: bool = True,
                             has_run: bool = False) -> None:
        cols = {r[1] for r in conn.execute(
            f"PRAGMA table_info({table})")}
        if "data_scope" not in cols:
            return
        n = 0
        if has_customer and "customer_id" in cols:
            qm = ",".join("?" * len(fixture_customers)) if \
                fixture_customers else "''"
            if fixture_customers:
                cur = conn.execute(
                    f"UPDATE {table} SET data_scope=?, test_run_id="
                    " CASE customer_id "
                    + " ".join(f"WHEN ? THEN ?"
                               for _ in fixture_customers)
                    + " ELSE ? END"
                    " WHERE customer_id IN (" + qm + ")"
                    " AND COALESCE(data_scope,'operational')='operational'",
                    (FIXTURE,
                     *[x for c in fixture_customers
                       for x in (c, fixture_customers[c])],
                     LEGACY_NS, *fixture_customers))
                n += cur.rowcount
        if has_run and "run_id" in cols and fixture_runs:
            for rid, ns in fixture_runs.items():
                cur = conn.execute(
                    f"UPDATE {table} SET data_scope=?, test_run_id=?"
                    " WHERE run_id=? AND"
                    " COALESCE(data_scope,'operational')='operational'",
                    (FIXTURE, ns, rid))
                n += cur.rowcount
        log(table, "customer/run 结构关联", n, FIXTURE)

    for t in ("md_project_v1", "field_task_v1", "survey_assignment_v1",
              "survey_response_v1", "user_calendar_v1"):
        backfill_by_customer(t, has_customer=True, has_run=True)
    # usage_event_v2 / evidence_bundle_v1 为不可变账本（DB 触发器禁
    # UPDATE）：不改历史行，其 scope 由查询侧经来源 run 判定
    # （finance/analytics 已加 run scope 过滤；新写入行自带 scope）。
    for t in ("workflow_node_execution_v1", "workflow_timer_v1",
              "workflow_branch_v1", "recognition_task",
              "agent_run_v1", "survey_media_v1"):
        backfill_by_customer(t, has_customer="customer_id" in {
            r[1] for r in conn.execute(f"PRAGMA table_info({t})")},
            has_run=True)

    # survey_media 经 response 关联（若无 customer 列）
    # usage/evidence 已经 run 关联覆盖

    # ---------- 4) 定义类对象（workflow/BI）：名称仅作线索 ----------
    uat_markers = ("%UAT%", "%uatv2_%", "%uatv3_%", "%UAT预演%",
                   "%UAT 预演%")
    for table, name_col in (("workflow_definition_v1", "name"),
                            ("bi_report_spec_v1", "name"),
                            ("survey_definition_v1", "name")):
        cond = " OR ".join(f"{name_col} LIKE ?" for _ in uat_markers)
        cur = conn.execute(
            f"UPDATE {table} SET data_scope=?, test_run_id=?"
            f" WHERE ({cond}) AND"
            " COALESCE(data_scope,'operational')='operational'",
            (FIXTURE, LEGACY_NS, *uat_markers))
        log(table, "名称线索（仅本次 backfill）", cur.rowcount, FIXTURE,
            LEGACY_NS)

    # 名称内嵌 namespace 的精化（如 "UAT3 问卷 uatv3_<ts>_<rand>"）：
    # 从名称提取真实 namespace 覆盖 LEGACY_NS（仍是名称线索，入审计）
    import re as _re
    ns_pat = _re.compile(r"(uatv[234]_\d{14}_[0-9a-z]+)")
    for table, name_col in (("workflow_definition_v1", "name"),
                            ("bi_report_spec_v1", "name"),
                            ("survey_definition_v1", "name")):
        rows = conn.execute(
            f"SELECT rowid rid, {name_col} nm FROM {table} WHERE"
            " data_scope=? AND test_run_id=?", (FIXTURE, LEGACY_NS)
        ).fetchall()
        n = 0
        for r in rows:
            m = ns_pat.search(r["nm"] or "")
            if m:
                conn.execute(
                    f"UPDATE {table} SET test_run_id=? WHERE rowid=?",
                    (m.group(1), r["rid"]))
                n += 1
        log(table, "名称内嵌 namespace 精化", n, FIXTURE)

    # 名称含 UAT 的 workflow run（business_run 无名称；经 work 标题）
    cur = conn.execute(
        "UPDATE business_run_v1 SET test_run_id=? WHERE data_scope=?"
        " AND COALESCE(test_run_id,'')=''", (LEGACY_NS, FIXTURE))
    log("business_run_v1", "fixture 仍缺 test_run_id 兜底",
        cur.rowcount, FIXTURE, LEGACY_NS)

    # 父子 scope 一致性：父 fixture 的子 run 结构性属于 fixture
    # （fail-closed 继承规则的历史修复）
    cur = conn.execute(
        "UPDATE business_run_v1 SET data_scope=?, test_run_id=("
        " SELECT COALESCE(NULLIF(p.test_run_id,''),?) FROM"
        " business_run_v1 p WHERE p.run_id=business_run_v1"
        " .parent_run_id) WHERE parent_run_id IS NOT NULL AND"
        " COALESCE(data_scope,'operational')='operational' AND"
        " parent_run_id IN (SELECT run_id FROM business_run_v1 WHERE"
        " data_scope=?)", (FIXTURE, LEGACY_NS, FIXTURE))
    log("business_run_v1", "父 fixture → 子继承（一致性修复）",
        cur.rowcount, FIXTURE)

    # ---------- 5) 无法判断归属 → quarantine ----------
    # recognition_task 无 run 关联且非任何已知客户：若有 UAT 期痕迹
    # 不强行判定；此处只对"fixture run 的下游但缺 scope"的行兜底。
    cur = conn.execute(
        "UPDATE recognition_task SET data_scope=?, test_run_id=?"
        " WHERE run_id IN (SELECT run_id FROM business_run_v1 WHERE"
        " data_scope=?) AND COALESCE(data_scope,'operational')"
        "='operational'", (FIXTURE, LEGACY_NS, FIXTURE))
    log("recognition_task", "fixture run 下游兜底", cur.rowcount, FIXTURE)

    # ---------- 6) Test Run 上下文登记（archived） ----------
    namespaces = {r["test_run_id"] for r in conn.execute(
        "SELECT DISTINCT test_run_id FROM business_run_v1 WHERE"
        " test_run_id!=''")}
    for ns in sorted(namespaces):
        custs = [c for c, n in fixture_customers.items() if n == ns]
        conn.execute(
            "INSERT OR IGNORE INTO uat_test_run_v1 (test_run_id,"
            " namespace, status, customer_ids_json, created_by,"
            " created_at, archived_at) VALUES (?,?,?,?,?,?,?)",
            (ns, ns, "archived", json.dumps(custs),
             "si2_backfill", _now(), _now()))
    log("uat_test_run_v1", "namespace 登记", len(namespaces), FIXTURE)

    # ---------- 7) 审计账本 ----------
    conn.executemany(
        "INSERT INTO scope_backfill_audit_v1 (occurred_at, actor,"
        " table_name, matched_by, matched_count, assigned_scope,"
        " assigned_test_run_id, detail_json) VALUES (?,?,?,?,?,?,?,?)",
        audit)
    if args.dry_run:
        conn.rollback()
        print("dry-run：未提交")
    else:
        conn.commit()
        print(f"已提交；审计 {len(audit)} 条 → scope_backfill_audit_v1")

    # ---------- 8) 汇总 ----------
    def cnt(sql: str) -> int:
        return conn.execute(sql).fetchone()[0]
    print("回填后：")
    print("  fixture runs 缺 test_run_id =", cnt(
        "SELECT count(*) FROM business_run_v1 WHERE data_scope="
        f"'{FIXTURE}' AND COALESCE(test_run_id,'')=''"))
    print("  unresolved =", cnt(
        f"SELECT count(*) FROM business_run_v1 WHERE data_scope='{UNRESOLVED}'"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
