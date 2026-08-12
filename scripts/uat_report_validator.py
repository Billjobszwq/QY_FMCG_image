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


def check_created(result: dict) -> tuple[bool, str]:
    """实体创建结果判定：inserted=0/skipped>0 不得当作创建成功。"""
    inserted = int(result.get("inserted", 0) or 0)
    skipped = int(result.get("skipped", 0) or 0)
    if inserted <= 0 or skipped > 0:
        return False, (f"inserted={inserted} skipped={skipped}："
                       "不得记为从空白创建成功")
    return True, ""


def validate_report(report: dict) -> list[str]:
    """返回缺失项列表；非空即报告 FAIL。"""
    problems: list[str] = []
    ids = report.get("ids") or {}
    for k in REQUIRED_ID_KEYS:
        v = ids.get(k)
        if not v:
            problems.append(f"缺关键 ID: ids.{k}")
    for s in REQUIRED_SECTIONS:
        if s not in report or report[s] in (None, "", [], {}):
            problems.append(f"缺必填段: {s}")
    # 实体创建判定：任何 inserted=0/skipped>0 标记失败
    for name, res in (report.get("created") or {}).items():
        ok, reason = check_created(res or {})
        if not ok:
            problems.append(f"实体 {name} {reason}")
    return problems


if __name__ == "__main__":
    import json
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else \
        ".eval/v3_uat_v2/report.json"
    try:
        rep = json.load(open(path, encoding="utf-8"))
    except FileNotFoundError:
        print(f"[FAIL] 报告不存在: {path}")
        raise SystemExit(1)
    probs = validate_report(rep)
    if probs:
        print("[FAIL] UAT V2 报告校验未通过：")
        for p in probs:
            print("  -", p)
        raise SystemExit(1)
    print("[PASS] UAT V2 报告校验通过")
