"""UFC T5：证据驱动 Gate 判定器（fail-closed）。

规则（指令第十一节）：
- Gate 只由 evaluate_gate_from_evidence() 从 Store/报告/测试/服务/
  浏览器证据自动计算；禁止调用方手写布尔值宣布 READY。
- 任一证据缺失或失败 → BLOCKED_BY_*；结果写入机器 gate.json，
  文档只引用，不得人工改写。
- 旧 evaluate_gate(布尔入参) 仅保留为内部单元参考，任何生产路径
  不得用它宣布 READY。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

READY = "READY_FOR_REAL_DATA_UAT"
EVALUATOR_VERSION = "2.0.0"

# UAT 主工作流必备节点类型（含 model/capability 真实调用）
REQUIRED_WORKFLOW_NODE_TYPES = ("trigger", "transform", "condition",
                                "wait", "parallel", "join", "loop",
                                "human_approval", "agent", "model")


def evaluate_gate(*, p0_open: int, p1_open: int, rate_limit_ok: bool,
                  scenarios_ok: bool, parallel_ok: bool,
                  storefront_contract_ok: bool = True,
                  usage_lineage_ok: bool = True,
                  uat_v2_ok: bool = True,
                  v4_honesty_ok: bool = True) -> tuple[str, list[str]]:
    """【已废弃的生产入口】仅保留为内部单元参考。生产 Gate 必须走
    evaluate_gate_from_evidence()。"""
    reasons: list[str] = []
    if p0_open > 0:
        reasons.append(f"存在 {p0_open} 个未关闭 P0")
    if p1_open > 0:
        reasons.append(f"存在 {p1_open} 个未关闭 P1")
    if not rate_limit_ok:
        reasons.append("rate limit 未真实实现/未验证（BLOCKED_BY_RATE_LIMIT）")
    if not scenarios_ok:
        reasons.append("UAT 必填场景缺失（BLOCKED_BY_UAT_EVIDENCE）")
    if not parallel_ok:
        reasons.append("parallel 无真实并发证明（BLOCKED_BY_WORKFLOW_RUNTIME）")
    if not storefront_contract_ok:
        reasons.append("门头必拍契约未通过（BLOCKED_BY_PHOTO_CONTRACT）")
    if not usage_lineage_ok:
        reasons.append("Agent Usage 链路不完整（BLOCKED_BY_USAGE_LINEAGE）")
    if not uat_v2_ok:
        reasons.append("UAT V2 未完整执行（BLOCKED_BY_UAT_EVIDENCE）")
    if not v4_honesty_ok:
        reasons.append("V4 证据口径不诚实（BLOCKED_BY_UAT_EVIDENCE）")
    if reasons:
        gate = "BLOCKED_BY_" + (
            "P0" if p0_open else "P1" if p1_open else "CONTRACT")
        return gate, reasons
    return READY, []


# --------------------------------------------------------------------
# 证据驱动主入口
# --------------------------------------------------------------------

def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except Exception:
        return ""


def _load_json(path) -> dict | None:
    try:
        p = Path(path)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def scan_terminal_drift(store) -> list[dict]:
    """DB 终态漂移扫描：run 终态但主 work/approval/timer/branch 未收敛。

    UFC T4：uat_fixture 为归档测试数据，不参与运营一致性判定。"""
    drift: list[dict] = []
    conn = store._conn
    rows = conn.execute(
        "SELECT br.run_id, br.status AS run_status, w.status AS"
        " work_status FROM business_run_v1 br JOIN work_item_v2 w"
        " ON w.work_id=br.work_id WHERE br.status IN"
        " ('succeeded','failed','partial_failed','cancelled') AND"
        " COALESCE(br.data_scope,'operational')='operational'"
        ).fetchall()
    expect = {"succeeded": "done", "failed": "blocked",
              "partial_failed": "blocked", "cancelled": "cancelled"}
    for r in rows:
        if r["work_status"] != expect[r["run_status"]]:
            drift.append({"kind": "main_work", "run_id": r["run_id"],
                          "run": r["run_status"],
                          "work": r["work_status"]})
    rows = conn.execute(
        "SELECT br.run_id, br.status AS run_status, w.work_id,"
        " w.status FROM business_run_v1 br JOIN work_item_v2 w"
        " ON w.run_id=br.run_id WHERE br.status IN"
        " ('succeeded','failed','partial_failed','cancelled') AND"
        " w.status='approval' AND"
        " COALESCE(br.data_scope,'operational')='operational'")
    rows = rows.fetchall()
    for r in rows:
        drift.append({"kind": "approval_open", "run_id": r["run_id"],
                      "run": r["run_status"], "work": r["work_id"]})
    rows = conn.execute(
        "SELECT t.run_id, t.status FROM workflow_timer_v1 t JOIN"
        " business_run_v1 br ON br.run_id=t.run_id WHERE br.status IN"
        " ('succeeded','failed','partial_failed','cancelled') AND"
        " t.status='pending' AND"
        " COALESCE(br.data_scope,'operational')='operational'")
    rows = rows.fetchall()
    for r in rows:
        drift.append({"kind": "timer_pending", "run_id": r["run_id"]})
    rows = conn.execute(
        "SELECT b.run_id, b.branch_id, b.status FROM"
        " workflow_branch_v1 b JOIN business_run_v1 br ON"
        " br.run_id=b.run_id WHERE br.status IN"
        " ('succeeded','failed','partial_failed','cancelled') AND"
        " b.status IN ('pending','running') AND"
        " COALESCE(br.data_scope,'operational')='operational'")
    rows = rows.fetchall()
    for r in rows:
        drift.append({"kind": "branch_open", "run_id": r["run_id"],
                      "branch": r["branch_id"]})
    return drift


def _open_issues(issue_ledger_path) -> list[dict]:
    """解析 ISSUES.md 表格中 OPEN 的 P0/P1。"""
    out = []
    try:
        text = Path(issue_ledger_path).read_text(encoding="utf-8")
    except Exception:
        return out
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[2].upper() == "OPEN" \
                and cells[1].upper() in ("P0", "P1"):
            out.append({"id": cells[0], "level": cells[1],
                        "summary": cells[3] if len(cells) > 3 else ""})
    return out


def evaluate_gate_from_evidence(*, store=None,
                                uat_report_path=None,
                                browser_report_path=None,
                                issue_ledger_path=None,
                                test_report_path=None,
                                service_health=None,
                                source_commit: str = "",
                                out_path=None) -> dict:
    """从证据自动计算 Gate。任一证据缺失/失败 → BLOCKED_BY_*。"""
    checks: list[dict] = []
    block_hint: list[str] = []

    def chk(name: str, ok: bool, evidence: str = "",
            block: str = "") -> bool:
        checks.append({"check": name, "ok": bool(ok),
                       "evidence": str(evidence)[:300]})
        if not ok and block and block not in block_hint:
            block_hint.append(block)
        return bool(ok)

    evidence_hashes: dict[str, str] = {}

    # ---- UAT 报告与 validator ----
    rep = _load_json(uat_report_path) if uat_report_path else None
    if uat_report_path:
        evidence_hashes["uat_report"] = _file_sha(Path(uat_report_path))
    if rep is None:
        chk("uat_report_present", False, "UAT 报告缺失",
            "BLOCKED_BY_GATE_EVIDENCE")
    else:
        failed_checks = [c for c in rep.get("checks", [])
                         if not c.get("ok")]
        chk("uat_checks_all_ok",
            not failed_checks and rep.get("failed", 0) == 0,
            f"failed={rep.get('failed')} "
            f"checks_failed={len(failed_checks)}",
            "BLOCKED_BY_GATE_EVIDENCE")
        try:
            from scripts.uat_report_validator import validate_report
            rep.setdefault("_base_dir",
                           str(Path(uat_report_path).parent))
            problems = validate_report(rep)
        except Exception as e:
            problems = [f"validator 异常: {e}"]
        chk("uat_validator_clean", not problems, str(problems)[:200],
            "BLOCKED_BY_GATE_EVIDENCE")
        # 主工作流必备节点（含 model/capability）
        node_types = set(rep.get("workflow_node_types") or [])
        missing_nodes = [t for t in REQUIRED_WORKFLOW_NODE_TYPES
                         if t not in node_types]
        chk("workflow_model_chain", not missing_nodes,
            f"missing={missing_nodes}",
            "BLOCKED_BY_WORKFLOW_MODEL_CHAIN")
        # 门头契约负例+成功例
        sf = rep.get("storefront") or {}
        chk("storefront_contract",
            bool(sf.get("negative_rejected"))
            and bool(sf.get("positive_submitted")),
            str(sf)[:200], "BLOCKED_BY_GATE_EVIDENCE")
        # parallel 真实并行与终态
        par = rep.get("parallel") or {}
        wall = par.get("wall_seconds")
        chk("parallel_real",
            isinstance(wall, (int, float)) and wall < 3.5
            and par.get("terminal") == "succeeded",
            str(par)[:200], "BLOCKED_BY_WORKFLOW_MODEL_CHAIN")
        # 异常追问链
        an = rep.get("anomaly_chain") or {}
        chk("anomaly_followup_chain",
            bool(an.get("anomaly_id")) and bool(an.get("follow_up"))
            and bool(an.get("human_answer"))
            and an.get("resolved") is True
            and int(an.get("report_versions", 0)) >= 2,
            str(an)[:200], "BLOCKED_BY_ANALYTICS_FOLLOWUP")
        # Agent 失败账本
        af = rep.get("agent_failure") or {}
        chk("agent_failure_lineage",
            bool(af.get("failed_run")) and bool(af.get("evidence"))
            and af.get("usage_recorded") is True,
            str(af)[:200], "BLOCKED_BY_AGENT_FAILURE_LINEAGE")
        # rate limit 拒绝证据
        rl = rep.get("rate_limit") or {}
        chk("rate_limit_denied_evidence", bool(rl.get("denied_429")),
            str(rl)[:200], "BLOCKED_BY_GATE_EVIDENCE")
        # 当前模型 / 训练进程 / fixture 残留
        chk("current_bundle_v4",
            rep.get("current_bundle") == "prod_v4_best_r1",
            str(rep.get("current_bundle")), "BLOCKED_BY_GATE_EVIDENCE")
        chk("no_training_process",
            int(rep.get("training_processes", 1)) == 0,
            str(rep.get("training_processes")),
            "BLOCKED_BY_GATE_EVIDENCE")
        chk("operational_uat_residue_zero",
            int(rep.get("operational_residue", 1)) == 0,
            str(rep.get("operational_residue")),
            "BLOCKED_BY_UAT_FIXTURE_POLLUTION")
        # Usage 完整率
        usage = rep.get("usage_lineage") or {}
        chk("usage_lineage_full",
            usage.get("total", 0) > 0
            and usage.get("linked", 0) == usage.get("total", 0),
            str(usage)[:200], "BLOCKED_BY_AGENT_FAILURE_LINEAGE")

    # ---- DB 终态漂移与 Agent 账本 ----
    if store is not None:
        try:
            drift = scan_terminal_drift(store)
            chk("no_terminal_drift", not drift, str(drift)[:250],
                "BLOCKED_BY_STATE_PROJECTION")
        except Exception as e:
            chk("no_terminal_drift", False, f"扫描异常: {e}",
                "BLOCKED_BY_STATE_PROJECTION")
        try:
            conn = store._conn
            n_failed_agent = conn.execute(
                "SELECT count(*) c FROM business_run_v1 WHERE"
                " command_kind='agent.invoke' AND status IN"
                " ('failed','partial_failed')").fetchone()["c"]
            chk("agent_failure_ledger_exists", n_failed_agent >= 1,
                f"failed_agent_runs={n_failed_agent}",
                "BLOCKED_BY_AGENT_FAILURE_LINEAGE")
            ic = conn.execute("PRAGMA integrity_check").fetchone()[0]
            chk("sqlite_integrity", ic == "ok", ic,
                "BLOCKED_BY_GATE_EVIDENCE")
        except Exception as e:
            chk("sqlite_integrity", False, str(e),
                "BLOCKED_BY_GATE_EVIDENCE")
    else:
        chk("store_present", False, "store 缺失",
            "BLOCKED_BY_GATE_EVIDENCE")

    # ---- ISSUES 账本 ----
    if issue_ledger_path:
        evidence_hashes["issue_ledger"] = _file_sha(
            Path(issue_ledger_path))
        opens = _open_issues(issue_ledger_path)
        chk("no_open_p0_p1", not opens, str(opens)[:250],
            "BLOCKED_BY_" + ("P0" if any(o["level"] == "P0"
                                         for o in opens) else "P1"))
    else:
        chk("issue_ledger_present", False, "ISSUES 账本缺失",
            "BLOCKED_BY_GATE_EVIDENCE")

    # ---- 测试报告 ----
    if test_report_path:
        evidence_hashes["test_report"] = _file_sha(
            Path(test_report_path))
        tr = _load_json(test_report_path)
        if tr is not None:
            failed_n = int(tr.get("failed", 0))
            chk("tests_all_passed", failed_n == 0,
                f"failed={failed_n} passed={tr.get('passed')}",
                "BLOCKED_BY_GATE_EVIDENCE")
        else:
            txt = Path(test_report_path).read_text(encoding="utf-8")
            ok = " failed" not in txt and (" passed" in txt)
            chk("tests_all_passed", ok, txt[-160:],
                "BLOCKED_BY_GATE_EVIDENCE")
    else:
        chk("test_report_present", False, "测试报告缺失",
            "BLOCKED_BY_GATE_EVIDENCE")

    # ---- 浏览器证据（文件必须存在，不接受纯文字） ----
    brow = _load_json(browser_report_path) if browser_report_path else None
    if browser_report_path:
        evidence_hashes["browser_report"] = _file_sha(
            Path(browser_report_path))
    if brow is None:
        chk("browser_evidence_present", False, "浏览器证据缺失",
            "BLOCKED_BY_GATE_EVIDENCE")
    else:
        files = brow.get("files") or []
        base = Path(browser_report_path).parent
        missing = [f for f in files
                   if not (base / f).exists()]
        chk("browser_screenshots_exist",
            bool(files) and not missing,
            f"total={len(files)} missing={missing[:5]}",
            "BLOCKED_BY_GATE_EVIDENCE")
        chk("browser_console_clean",
            brow.get("console_errors_unexplained", 1) == 0,
            str(brow.get("console_errors_unexplained")),
            "BLOCKED_BY_GATE_EVIDENCE")

    # ---- 服务健康 ----
    if service_health is not None:
        down = [k for k, v in (service_health or {}).items() if not v]
        chk("services_healthy", not down, str(service_health)[:200],
            "BLOCKED_BY_GATE_EVIDENCE")
    else:
        chk("service_health_present", False, "服务健康证据缺失",
            "BLOCKED_BY_GATE_EVIDENCE")

    # ---- 判定 ----
    all_ok = all(c["ok"] for c in checks)
    if all_ok:
        gate = READY
        reasons: list[str] = []
    else:
        gate = block_hint[0] if block_hint else "BLOCKED_BY_GATE_EVIDENCE"
        reasons = [c["check"] for c in checks if not c["ok"]]
    result = {"gate": gate, "reasons": reasons, "checks": checks,
              "evidence_hashes": evidence_hashes,
              "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "evaluator_version": EVALUATOR_VERSION,
              "source_commit": source_commit}
    if out_path:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    return result
