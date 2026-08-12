"""SI3 T0：独立只读 Scope 审计器（Scope Integrity V3）。

不信任旧报告：直接对 .platform/platform.sqlite 复算 effective scope
泄漏。effective_scope = 自身列 ∪ 父链（run/customer/response/agent）
推导；operational 投影中 effective=fixture 的行即为泄漏。

只读连接（mode=ro），不写库。输出 JSON 到 .eval/scope_v3/。
用法：python3 scripts/scope_audit_v3.py [--db PATH] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

FIXTURE = "('uat_fixture','demo_fixture')"
OP = "COALESCE(data_scope,'operational')='operational'"
TERMINAL_RUN = ('succeeded', 'failed', 'partial_failed', 'cancelled',
                'rejected')
NONTERMINAL_NODE = ('running', 'pending', 'queued', 'waiting', 'paused',
                    'in_progress', 'scheduled', 'started')


def _c(sql: str, conn: sqlite3.Connection) -> int:
    return conn.execute(sql).fetchone()[0]


def audit(db: Path) -> dict:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    out: dict = {}

    # 1) fixture response → operational survey_media
    out["media_from_fixture_response_operational"] = _c(f"""
        SELECT count(*) FROM survey_media_v1 m
        JOIN survey_response_v1 r ON r.response_id=m.response_id
        WHERE {OP.replace('data_scope', 'm.data_scope')}
          AND (r.data_scope IN {FIXTURE}
               OR COALESCE(r.test_run_id,'')!='')
    """, conn)

    # 2) fixture Run → operational WorkItem
    out["work_from_fixture_run_operational"] = _c(f"""
        SELECT count(*) FROM work_item_v2 w
        JOIN business_run_v1 r ON r.run_id=w.run_id
        WHERE {OP.replace('data_scope', 'w.data_scope')}
          AND (r.data_scope IN {FIXTURE}
               OR COALESCE(r.test_run_id,'')!='')
    """, conn)

    # 3) fixture Run/客户 → operational recognition_task
    out["recognition_from_fixture_run_operational"] = _c(f"""
        SELECT count(*) FROM recognition_task t
        WHERE {OP.replace('data_scope', 't.data_scope')}
          AND (COALESCE(t.test_run_id,'')!=''
               OR t.run_id IN (SELECT run_id FROM business_run_v1
                    WHERE data_scope IN {FIXTURE}
                       OR COALESCE(test_run_id,'')!='')
               OR EXISTS (SELECT 1 FROM business_run_v1 r
                    JOIN md_customer_v1 c ON c.customer_id=r.customer_id
                    WHERE r.run_id=t.run_id
                      AND c.data_scope IN {FIXTURE}))
    """, conn)

    # 4) fixture Agent → operational BI report
    # BI 表无 run_id 列，只能经“创建时刻的活跃 Run”推父链；
    # 严格口径：创建时刻存在 started_at<=t<ended_at 的 fixture Run
    out["bi_from_fixture_agent_operational"] = _c(f"""
        SELECT count(*) FROM bi_report_spec_v1 b
        WHERE {OP.replace('data_scope', 'b.data_scope')}
          AND (COALESCE(b.test_run_id,'')!=''
               OR EXISTS (SELECT 1 FROM business_run_v1 r
                    WHERE r.data_scope IN {FIXTURE}
                      AND r.started_at <= b.created_at
                      AND b.created_at < COALESCE(r.ended_at,'9999')))
    """, conn)
    out["bi_from_fixture_agent_strict"] = _c(f"""
        SELECT count(*) FROM bi_report_spec_v1 b
        WHERE {OP.replace('data_scope', 'b.data_scope')}
          AND EXISTS (SELECT 1 FROM business_run_v1 r
               WHERE r.data_scope IN {FIXTURE}
                 AND r.started_at <= b.created_at
                 AND b.created_at < COALESCE(r.ended_at,'9999')
                 AND NOT EXISTS (SELECT 1 FROM business_run_v1 o
                      WHERE o.data_scope NOT IN {FIXTURE}
                        AND o.started_at <= b.created_at
                        AND b.created_at < COALESCE(o.ended_at,'9999')))
    """, conn)

    # 5) fixture/测试客户下失败 Agent Run/Work/Usage 为 operational
    out["failed_agent_under_fixture_operational"] = _c(f"""
        SELECT count(*) FROM agent_run_v1 a
        WHERE a.status='failed' AND {OP.replace('data_scope', 'a.data_scope')}
          AND (a.customer_id IN (SELECT customer_id FROM md_customer_v1
                    WHERE data_scope IN {FIXTURE} OR is_test_fixture=1)
               OR a.business_run_id IN (SELECT run_id FROM
                    business_run_v1 WHERE data_scope IN {FIXTURE}
                    OR COALESCE(test_run_id,'')!=''))
    """, conn)

    # 6) fixture Run → operational Usage（V3：已 attribution 绑定
    # 的行视为已纠偏，不计泄漏；原行不可变）
    out["usage_from_fixture_run_operational"] = _c(f"""
        SELECT count(*) FROM usage_event_v2 u
        WHERE {OP.replace('data_scope', 'u.data_scope')}
          AND (COALESCE(u.test_run_id,'')!=''
               OR u.run_id IN (SELECT run_id FROM business_run_v1
                    WHERE data_scope IN {FIXTURE}
                       OR COALESCE(test_run_id,'')!='')
               OR u.customer_id IN (SELECT customer_id FROM
                    md_customer_v1 WHERE data_scope IN {FIXTURE}
                    OR is_test_fixture=1))
          AND NOT EXISTS (SELECT 1 FROM scope_attribution_ledger_v1 a
               WHERE a.subject_table='usage_event_v2' AND
               a.subject_id=u.usage_id AND a.effective_scope IN
               {FIXTURE})
    """, conn)

    # 7) is_test_fixture=1 但 data_scope=operational 客户
    out["fixture_flag_customer_operational"] = _c(f"""
        SELECT count(*) FROM md_customer_v1
        WHERE is_test_fixture=1 AND {OP}
    """, conn)
    out["fixture_flag_customer_operational_ids"] = [
        r["customer_id"] for r in conn.execute(f"""
        SELECT customer_id FROM md_customer_v1
        WHERE is_test_fixture=1 AND {OP}""").fetchall()]

    # 8) terminal Run 下 non-terminal workflow node
    out["nonterminal_node_under_terminal_run"] = _c(f"""
        SELECT count(*) FROM workflow_node_execution_v1 n
        JOIN business_run_v1 r ON r.run_id=n.run_id
        WHERE r.status IN {TERMINAL_RUN}
          AND n.status IN {NONTERMINAL_NODE}
    """, conn)

    # 补充：timer/branch 终态漂移
    try:
        out["nonterminal_timer_under_terminal_run"] = _c(f"""
            SELECT count(*) FROM workflow_timer_v1 t
            JOIN business_run_v1 r ON r.run_id=t.run_id
            WHERE r.status IN {TERMINAL_RUN}
              AND t.status IN {NONTERMINAL_NODE}
        """, conn)
    except sqlite3.Error as e:
        out["nonterminal_timer_under_terminal_run"] = f"ERR:{e}"
    try:
        out["nonterminal_branch_under_terminal_run"] = _c(f"""
            SELECT count(*) FROM workflow_branch_v1 b
            JOIN business_run_v1 r ON r.run_id=b.run_id
            WHERE r.status IN {TERMINAL_RUN}
              AND b.status IN {NONTERMINAL_NODE}
        """, conn)
    except sqlite3.Error as e:
        out["nonterminal_branch_under_terminal_run"] = f"ERR:{e}"

    # 9) 首页口径：operational 投影中仍含 fixture 客户/BI/失败待办
    out["home_fixture_customers_in_operational_list"] = _c("""
        SELECT count(*) FROM md_customer_v1
        WHERE COALESCE(data_scope,'operational')='operational'
          AND (is_test_fixture=1 OR customer_id LIKE 'uat%'
               OR name LIKE '%UAT%' OR name LIKE '%uat%')
    """, conn)
    out["home_bi_draft_uat_in_operational"] = _c("""
        SELECT count(*) FROM bi_report_spec_v1
        WHERE COALESCE(data_scope,'operational')='operational'
          AND status IN ('draft','drafting')
          AND (name LIKE '%UAT%' OR name LIKE '%uat%'
               OR COALESCE(test_run_id,'')!='')
    """, conn)
    out["home_work_current_uat_title"] = _c("""
        SELECT count(*) FROM work_item_v2
        WHERE COALESCE(data_scope,'operational')='operational'
          AND COALESCE(visibility,'current')='current'
          AND (title LIKE '%uat%' OR title LIKE '%UAT%')
    """, conn)

    # 10/11) 普通列表口径：客户/问卷列表默认是否含 fixture
    # survey_definition 无 customer_id，经 assignment/response 推父链
    out["survey_def_operational_with_fixture_lineage"] = _c(f"""
        SELECT count(DISTINCT s.survey_id) FROM survey_definition_v1 s
        WHERE {OP.replace('data_scope', 's.data_scope')}
          AND (COALESCE(s.test_run_id,'')!=''
               OR s.survey_id IN (SELECT survey_id FROM
                    survey_assignment_v1 WHERE data_scope IN {FIXTURE}
                    OR COALESCE(test_run_id,'')!='')
               OR s.survey_id IN (SELECT survey_id FROM
                    survey_response_v1 WHERE data_scope IN {FIXTURE}
                    OR COALESCE(test_run_id,'')!='')
               OR s.name LIKE '%uat%' OR s.name LIKE '%UAT%')
    """, conn)

    # 12) usage 财务口径：operational 发票覆盖 fixture usage 客户
    # （V3：发票自身结构化 scope 列；旧库无列时回退父链口径）
    fin_cols = {r[1] for r in conn.execute(
        "PRAGMA table_info(fin_invoice_v1)").fetchall()}
    if "data_scope" in fin_cols:
        out["finance_invoice_operational_from_fixture_usage"] = _c(f"""
            SELECT count(*) FROM fin_invoice_v1 i
            WHERE COALESCE(i.data_scope,'operational')='operational'
              AND EXISTS (SELECT 1 FROM usage_event_v2 u
                   WHERE u.customer_id=i.customer_id
                     AND (u.run_id IN (SELECT run_id FROM
                            business_run_v1 WHERE data_scope IN
                            {FIXTURE})
                          OR COALESCE(u.test_run_id,'')!=''))
        """, conn)
    else:
        out["finance_invoice_operational_from_fixture_usage"] = _c(f"""
            SELECT count(*) FROM fin_invoice_v1 i
            WHERE EXISTS (SELECT 1 FROM usage_event_v2 u
                   WHERE u.customer_id=i.customer_id
                     AND (u.run_id IN (SELECT run_id FROM business_run_v1
                            WHERE data_scope IN {FIXTURE})
                          OR COALESCE(u.test_run_id,'')!=''))
        """, conn)

    # 13) Gate 一致性：gate.json READY 与上述计数冲突（由调用方比对）
    # 19) UAT V4 report ids
    try:
        rep = json.loads(Path(".eval/uat_scope_v2/uatv4/report.json")
                         .read_text())
        out["uatv4_report_ids_count"] = len(rep.get("ids") or {})
    except Exception as e:  # noqa: BLE001
        out["uatv4_report_ids_count"] = f"ERR:{e}"

    # 汇总
    out["_integrity_check"] = conn.execute(
        "PRAGMA integrity_check").fetchone()[0]
    conn.close()
    return out


def _has_col(conn: sqlite3.Connection, table: str, col: str) -> bool:
    return col in {r[1] for r in conn.execute(
        f"PRAGMA table_info({table})").fetchall()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=".platform/platform.sqlite")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    result = audit(Path(args.db))
    out_path = Path(args.out) if args.out else (
        Path(".eval/scope_v3/audit_latest.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[saved] {out_path}")


if __name__ == "__main__":
    main()
