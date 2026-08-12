#!/usr/bin/env python3
"""SI2 T10：Gate 2.1 负例验证（指令第六节 12 项）。

每项在临时 DB/证据上构造违规场景，断言 Gate 拒绝放行或创建
fail-closed；不触碰生产库与历史证据。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.platform.data.store import PlatformStore  # noqa: E402
from src.platform.gate_evaluator import (  # noqa: E402
    evaluate_gate_from_evidence)
from src.platform.scope import ScopePolicy, ExecutionScopeV1, \
    ScopeViolation  # noqa: E402

RESULTS: list[dict] = []


def neg(name: str, ok: bool, evidence: str = "") -> None:
    RESULTS.append({"case": name, "blocked": ok,
                    "evidence": str(evidence)[:200]})
    print(("  ✓ 阻断 " if ok else "  ✗ 未阻断 ") + name +
          (f"  [{str(evidence)[:100]}]" if evidence else ""))


def tmp_store(tmp: Path) -> PlatformStore:
    return PlatformStore(tmp / "p.sqlite")


def base_eval(store, **kw):
    return evaluate_gate_from_evidence(store=store, source_commit="h",
                                       current_head="h", **kw)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="si2_neg_"))

    # 1) fixture 外勤任务泄漏进 operational 投影 → 阻断
    s = tmp_store(tmp / "1")
    s._conn.execute(
        "INSERT INTO field_task_v1 (task_id, customer_id, address_id,"
        " data_scope, test_run_id, created_at, updated_at)"
        " VALUES ('ft-leak','real','a','operational','uatv4_x',"
        " datetime('now'),datetime('now'))")
    s._conn.commit()
    r = base_eval(s)
    neg("1_fixture_field_task_operational_leak",
        r["gate"] == "BLOCKED_BY_UAT_FIXTURE_PROJECTION", r["gate"])

    # 2) fixture run 缺 test_run_id → 阻断
    s = tmp_store(tmp / "2")
    s._conn.execute(
        "INSERT INTO business_run_v1 (run_id, work_id, status,"
        " data_scope, created_at, updated_at)"
        " VALUES ('run-x','w','succeeded','uat_fixture',"
        "datetime('now'),datetime('now'))")
    s._conn.commit()
    r = base_eval(s)
    neg("2_fixture_run_missing_test_run_id",
        r["gate"] == "BLOCKED_BY_SCOPE_LINEAGE", r["gate"])

    # 3) 父 fixture → 子 operational 创建必须失败（fail-closed）
    pol = ScopePolicy()
    try:
        pol.check_child(
            ExecutionScopeV1(data_scope="uat_fixture",
                             test_run_id="uatv4_x"),
            ExecutionScopeV1(data_scope="operational"))
        neg("3_fixture_parent_operational_child", False, "未抛错")
    except ScopeViolation as e:
        neg("3_fixture_parent_operational_child", True, e.code)

    # 4) 浏览器证据对象 ID 不一致 → 阻断
    s = tmp_store(tmp / "4")
    bj = tmp / "4" / "b.json"
    bj.write_text(json.dumps({"files": [], "console_errors_unexplained": 0,
                              "pages": [{"route": "/w",
                                         "expected_object_id": "wf-A",
                                         "actual_object_id": "wf-B",
                                         "assertion": True}]}))
    r = base_eval(s, browser_report_path=str(bj))
    neg("4_browser_object_id_mismatch",
        r["gate"] == "BLOCKED_BY_BROWSER_SEMANTICS", r["gate"])

    # 5) 必需截图缺失 → 阻断
    s = tmp_store(tmp / "5")
    bj = tmp / "5" / "b.json"
    bj.parent.mkdir(parents=True, exist_ok=True)
    bj.write_text(json.dumps({"files": ["missing_shot.png"],
                              "console_errors_unexplained": 0,
                              "pages": []}))
    r = base_eval(s, browser_report_path=str(bj))
    neg("5_required_screenshot_missing",
        r["gate"] == "BLOCKED_BY_GATE_EVIDENCE", r["gate"])

    # 6) Gate 生成后 tracked 代码变化（树 hash 不一致）→ STALE
    s = tmp_store(tmp / "6")
    r = base_eval(s, recorded_tree_hash="hashA", current_tree_hash="hashB")
    neg("6_code_change_after_gate_stale",
        r["gate"] == "STALE_GATE_EVIDENCE", r["gate"])

    # 7) P0 OPEN → BLOCKED_BY_P0
    s = tmp_store(tmp / "7")
    iss = tmp / "7" / "ISSUES.md"
    iss.parent.mkdir(parents=True, exist_ok=True)
    iss.write_text("| ID | 级别 | 状态 | 摘要 |\n|---|---|---|---|\n"
                   "| X-1 | P0 | OPEN | 模拟 P0 |\n")
    r = base_eval(s, issue_ledger_path=str(iss))
    neg("7_p0_open_blocked", r["gate"] == "BLOCKED_BY_P0", r["gate"])

    # 8) CURRENT 非 prod_v4_best_r1 → 阻断
    s = tmp_store(tmp / "8")
    rep = tmp / "8" / "rep.json"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps({"protocol": "uatv4", "failed": 0,
                               "checks": [],
                               "current_bundle": "evil_bundle",
                               "training_processes": 0,
                               "operational_residue": 0}))
    r = base_eval(s, uat_report_path=str(rep))
    neg("8_current_bundle_not_v4",
        r["gate"] != "READY_FOR_REAL_DATA_UAT"
        and "current_bundle_v4" in r["reasons"], r["gate"])

    # 9) 存在训练进程 → 阻断
    rep.write_text(json.dumps({"protocol": "uatv4", "failed": 0,
                               "checks": [],
                               "current_bundle": "prod_v4_best_r1",
                               "training_processes": 2,
                               "operational_residue": 0}))
    r = base_eval(s, uat_report_path=str(rep))
    neg("9_training_process_running",
        r["gate"] != "READY_FOR_REAL_DATA_UAT"
        and "no_training_process" in r["reasons"], r["gate"])

    # 10) 服务健康失败 → 阻断
    r = base_eval(tmp_store(tmp / "10"),
                  service_health={"app": False})
    neg("10_service_unhealthy",
        r["gate"] != "READY_FOR_REAL_DATA_UAT"
        and "services_healthy" in r["reasons"], r["gate"])

    # 11) Agent 默认查询混入 fixture（模拟回归泄漏）→ 阻断
    s = tmp_store(tmp / "11")
    s._conn.execute(
        "INSERT INTO md_project_v1 (project_id, customer_id, name,"
        " data_scope, test_run_id, created_at, updated_at)"
        " VALUES ('prj-leak','c','x','operational','uatv4_x',"
        "datetime('now'),datetime('now'))")
    s._conn.commit()
    from src.platform.agents.runtime import AgentRuntime
    out = AgentRuntime(s)._exec_tool("master.data.summary", {},
                                     actor="sup", customer_id="")
    leaked_to_agent = out["projects"] == 1  # 若查询口径回归则计入
    r = base_eval(s)
    neg("11_agent_default_query_fixture",
        r["gate"] == "BLOCKED_BY_UAT_FIXTURE_PROJECTION"
        and not leaked_to_agent,
        f"gate={r['gate']} agent_projects={out['projects']}")

    # 12) fixture Usage 混入客户账单 → 阻断（泄漏场景：带 test_run
    # 的用量被误标 operational；不可变账本直接按泄漏形态构造）
    s = tmp_store(tmp / "12")
    s._conn.execute(
        "INSERT INTO business_run_v1 (run_id, work_id, customer_id,"
        " status, data_scope, test_run_id, created_at, updated_at)"
        " VALUES ('run-fx','w','real-c','succeeded','uat_fixture',"
        "'uatv4_x',datetime('now'),datetime('now'))")
    s.insert_usage_event_v2(usage_id="u-fx", unit="recognition_photo",
                            quantity=50, run_id="run-fx",
                            customer_id="real-c",
                            source_evidence="t",
                            data_scope="operational",
                            test_run_id="uatv4_x")
    s._conn.commit()
    r = base_eval(s)
    neg("12_fixture_usage_in_billing",
        r["gate"] == "BLOCKED_BY_UAT_FIXTURE_PROJECTION", r["gate"])

    failed = [x for x in RESULTS if not x["blocked"]]
    out = ROOT / ".eval" / "uat_scope_v2" / "gate_negative_tests.json"
    out.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\n负例 {len(RESULTS) - len(failed)}/{len(RESULTS)} 全部"
          f"阻断，证据：{out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
