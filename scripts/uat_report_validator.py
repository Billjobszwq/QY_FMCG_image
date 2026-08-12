"""UATCC：UAT V2 机器报告校验器（fail-closed）。

规则（指令 §9.1/§9.7）：
- 缺任一手册规定关键 ID/字段 → 判失败，不允许只计算"通过项数量"；
- `inserted=0 / skipped=1` 的实体不得记为"从空白创建成功"。
"""
from __future__ import annotations

# 报告必须包含的顶层 ID / 实体键
REQUIRED_ID_KEYS = (
    "customer", "project", "tenant", "sku", "employee",
    "survey", "assignment", "response", "workflow_definition",
    "workflow_run", "agent_run", "recognition_task",
    "usage", "evidence", "dashboard",
)

# 报告必须包含的结构段
REQUIRED_SECTIONS = (
    "roles",            # 六角色权限矩阵
    "api_steps",        # 每步 API 状态
    "projection",       # DB 投影状态
    "events",           # 事件序列
    "hashes",           # 制品/定义 hash
    "browser",          # 浏览器截图与 console
    "latency",          # p50/p95
    "recovery",         # 重启恢复
    "failures",         # 失败与人工接管证据
    "relations",        # run/work/branch/agent/recognition/usage/evidence 关系
)

# UFC T6：主工作流必备节点类型；model/command 任一即可作为
# capability 节点（指令："model或command/capability"）。
REQUIRED_NODE_TYPES = ("trigger", "transform", "condition", "wait",
                       "parallel", "join", "loop", "human_approval",
                       "agent")
CAPABILITY_NODE_TYPES = ("model", "command")


def check_created(result: dict) -> tuple[bool, str]:
    """实体创建结果判定：inserted=0/skipped>0 不得当作创建成功。"""
    inserted = int(result.get("inserted", 0) or 0)
    skipped = int(result.get("skipped", 0) or 0)
    if inserted <= 0 or skipped > 0:
        return False, (f"inserted={inserted} skipped={skipped}："
                       "不得记为从空白创建成功")
    return True, ""


# SI2：UAT V4 协议必备断言（scope-first；见 04-UAT-V4-PROTOCOL）
REQUIRED_UATV4_CHECKS = (
    "test_run_context_first", "fixture_customer_scoped",
    "fixture_survey_scoped", "fixture_workflow_scoped",
    "workflow_run_started", "workflow_run_scope_inherited",
    "storefront_negative_rejected", "storefront_positive_submitted",
    "agent_failure_ledger_recorded",
    "home_zero_fixture_during_uat", "archive_ok",
    "post_archive_leakage_zero", "post_archive_test_run_full",
    "post_archive_parent_child_ok", "center_keeps_history",
    "home_zero_fixture_after_archive",
)


def _validate_uatv4(report: dict) -> list[str]:
    problems: list[str] = []
    if not report.get("namespace"):
        problems.append("缺 namespace")
    if int(report.get("failed", 0) or 0) > 0:
        problems.append(f"failed={report.get('failed')} > 0")
    checks = {c.get("check"): c for c in report.get("checks", []) or []}
    for name, c in checks.items():
        if not c.get("ok"):
            problems.append(f"check 失败: {name}")
    for req in REQUIRED_UATV4_CHECKS:
        if req not in checks:
            problems.append(f"缺必备断言: {req}")
    return problems


def validate_report(report: dict) -> list[str]:
    """返回缺失/违规项列表；非空即报告 FAIL（fail-closed）。

    UFC T6：除基础必填外，还拒绝 failed>0、check.ok=false、意外
    4xx/5xx、终态漂移/残留、工作流缺必备节点、异常链不完整、
    Agent 失败无账本、Usage 未挂链、浏览器证据缺文件、服务不
    健康、CURRENT 非 prod_v4_best_r1、存在长训练进程。

    SI2：protocol=uatv4 报告走 V4 协议校验（scope-first 检查集）。"""
    if report.get("protocol") == "uatv4":
        return _validate_uatv4(report)
    problems: list[str] = []
    ids = report.get("ids") or {}
    for k in REQUIRED_ID_KEYS:
        v = ids.get(k)
        if not v:
            problems.append(f"缺关键 ID: ids.{k}")
    for s in REQUIRED_SECTIONS:
        if s not in report or report[s] is None:
            problems.append(f"缺必填段: {s}")
        elif s != "failures" and report[s] in ("", [], {}):
            # failures 允许为空列表（无失败）；其余段不得为空
            problems.append(f"缺必填段: {s}")
    # 实体创建判定：任何 inserted=0/skipped>0 标记失败
    for name, res in (report.get("created") or {}).items():
        ok, reason = check_created(res or {})
        if not ok:
            problems.append(f"实体 {name} {reason}")

    # ---- UFC T6 强化校验 ----
    if int(report.get("failed", 0) or 0) > 0:
        problems.append(f"failed={report.get('failed')} > 0")
    for c in report.get("checks", []) or []:
        if not c.get("ok"):
            problems.append(f"check 失败: {c.get('check')}")
    # API 步骤：非预期 4xx/5xx（预期负例需标 expected_error）
    for s in report.get("api_steps", []) or []:
        st = s.get("status")
        if isinstance(st, int) and st >= 400 \
                and not s.get("expected_error"):
            problems.append(f"意外 {st}: {s.get('path')}")
    # 终态一致性：漂移/残留
    ts = report.get("terminal_state")
    if ts is not None:
        if ts.get("drift"):
            problems.append(f"终态漂移: {str(ts['drift'])[:120]}")
        if ts.get("open_approvals"):
            problems.append("approval 残留")
        if ts.get("open_branches"):
            problems.append("branch 残留")
        if ts.get("pending_timers"):
            problems.append("pending timer 残留")
    # 工作流必备节点（含 model/capability：model 或 command 任一）
    if "workflow_node_types" in report:
        wnt = set(report.get("workflow_node_types") or [])
        for t in REQUIRED_NODE_TYPES:
            if t not in wnt:
                problems.append(f"工作流缺必备节点类型: {t}")
        if not any(t in wnt for t in CAPABILITY_NODE_TYPES):
            problems.append("工作流缺 model/command capability 节点")
    # 异常追问链
    an = report.get("anomaly_chain")
    if an is not None:
        if not an.get("anomaly_id"):
            problems.append("anomaly 无真实 anomaly_id")
        if not an.get("follow_up"):
            problems.append("缺 Agent 追问")
        if not an.get("human_answer"):
            problems.append("缺人工回答")
        if int(an.get("report_versions", 0) or 0) < 2:
            problems.append("回答后无报表新版本")
        if an.get("resolved") is not True:
            problems.append("anomaly 未 resolved")
    # Agent 失败账本
    af = report.get("agent_failure")
    if af is not None:
        if not af.get("failed_run"):
            problems.append("Agent 失败缺 failed run")
        if not af.get("evidence"):
            problems.append("Agent 失败缺 evidence")
        if not af.get("usage_recorded"):
            problems.append("Agent 失败缺 Usage")
    # Usage 挂链完整率
    ul = report.get("usage_lineage")
    if ul is not None and int(ul.get("linked", 0) or 0) != \
            int(ul.get("total", 0) or 0):
        problems.append("Usage 未 100% 挂 run/work/evidence")
    # 浏览器证据：必须真实存在文件，不接受纯文字
    br = report.get("browser") or {}
    files = br.get("files") or []
    if br and not files:
        problems.append("浏览器证据只有文字，无截图文件")
    elif files:
        import os
        base = report.get("_base_dir") or ""
        for f in files:
            cands = [os.path.join(base, f),
                     os.path.join(base, "browser", f), f]
            if not any(os.path.exists(c) for c in cands):
                problems.append(f"截图不存在: {f}")
    # 服务健康 / 当前模型 / 训练进程
    if report.get("services_healthy") is False:
        problems.append("服务未健康")
    cb = report.get("current_bundle")
    if cb and cb != "prod_v4_best_r1":
        problems.append(f"CURRENT 非 prod_v4_best_r1: {cb}")
    if int(report.get("training_processes", 0) or 0) > 0:
        problems.append("检测到长训练进程")
    return problems


if __name__ == "__main__":
    import json
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else \
        ".eval/v3_uat_v3/report.json"
    try:
        rep = json.load(open(path, encoding="utf-8"))
    except FileNotFoundError:
        print(f"[FAIL] 报告不存在: {path}")
        raise SystemExit(1)
    import os as _os
    rep.setdefault("_base_dir", _os.path.dirname(_os.path.abspath(path)))
    probs = validate_report(rep)
    if probs:
        print(f"[FAIL] UAT 报告校验未通过（{len(probs)} 项）：")
        for p in probs:
            print("  -", p)
        raise SystemExit(1)
    print("[PASS] UAT 报告校验通过")
