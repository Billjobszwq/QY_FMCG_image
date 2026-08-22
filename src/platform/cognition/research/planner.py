"""Research Planner 端口与 typed 计划（R2-06 / 03 §5 / 04 §9）。

- lookup/case/methodology：确定性最小计划（单原子问题），不依赖外部
  provider；
- deep_research：必须有界子问题 + 依赖 + 期望证据 + target kinds +
  时间/scope + 停止条件 + 至少一个反证/替代解释查询；
- planner provider 不可用时 deep_research 必须 degraded/abstain，
  不得用单问题冒充规划完成。

计划必须经预算/结构校验后才进入执行。
"""
from __future__ import annotations

from typing import Any, Protocol


class PlannerProvider(Protocol):
    def available(self) -> bool: ...

    def plan(self, *, question: str, mode: str,
             budget: dict) -> dict[str, Any]: ...


class UnavailablePlannerProvider:
    """显式不可用 planner：deep_research 据此 degraded/abstain。"""

    def available(self) -> bool:
        return False

    def plan(self, *, question: str, mode: str,
             budget: dict) -> dict[str, Any]:
        raise RuntimeError("planner provider 不可用（不得调用）")


_REQUIRED_SQ_FIELDS = ("sq_id", "text", "stop_condition", "target_kinds")


def validate_plan(plan: dict[str, Any], budget: dict) -> list[str]:
    """结构校验：返回错误列表（空=通过）。计划不得无界。"""
    errors: list[str] = []
    sqs = plan.get("subquestions")
    if not isinstance(sqs, list) or not sqs:
        return ["计划缺少 subquestions"]
    max_sq = int(budget.get("max_subquestions", 12))
    if len(sqs) > max_sq:
        errors.append(f"subquestions 超出预算上限 {max_sq}")
    seen_ids: set[str] = set()
    for sq in sqs:
        if not isinstance(sq, dict):
            errors.append("subquestion 必须是对象")
            continue
        for f in _REQUIRED_SQ_FIELDS:
            if not sq.get(f):
                errors.append(f"subquestion 缺 {f}: {sq.get('sq_id')}")
        sqid = sq.get("sq_id", "")
        if sqid in seen_ids:
            errors.append(f"subquestion id 重复: {sqid}")
        seen_ids.add(sqid)
        deps = sq.get("depends_on") or []
        for d in deps:
            if d not in {s.get("sq_id") for s in sqs}:
                errors.append(f"依赖不存在: {sqid} -> {d}")
    return errors


def atomic_plan(question: str, *, target_kinds: list[str]) -> dict:
    """lookup/case/methodology 的最小 typed 计划（单原子问题）。"""
    return {"planner": "deterministic@1",
            "subquestions": [{
                "sq_id": "sq-1", "text": question, "depends_on": [],
                "expected_evidence": ["policy_or_case"],
                "target_kinds": list(target_kinds),
                "stop_condition": "找到可定位证据或穷尽授权来源"}]}
