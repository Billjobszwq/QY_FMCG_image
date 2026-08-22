"""研究预算（Task 9 / 03 §5.2）。

预算按 mode 给定，不由 Prompt 放大；消耗持久化在 research_run_v1.
consumed_json，resume 不重复消费。达到硬上限 → 停止并诚实报告
（不伪装完整）。
"""
from __future__ import annotations

DEFAULT_BUDGETS: dict[str, dict[str, int]] = {
    "lookup": {"max_iterations": 1, "max_queries": 4,
               "max_subquestions": 1, "max_steps": 40,
               "deadline_seconds": 120},
    "case_analysis": {"max_iterations": 2, "max_queries": 8,
                      "max_subquestions": 3, "max_steps": 80,
                      "deadline_seconds": 600},
    "methodology": {"max_iterations": 2, "max_queries": 8,
                    "max_subquestions": 3, "max_steps": 80,
                    "deadline_seconds": 600},
    "deep_research": {"max_iterations": 6, "max_queries": 36,
                      "max_subquestions": 12, "max_steps": 200,
                      "deadline_seconds": 1800},
}


def budget_for(mode: str, override: dict | None = None) -> dict[str, int]:
    base = dict(DEFAULT_BUDGETS.get(mode, DEFAULT_BUDGETS["lookup"]))
    if override:
        for k in base:
            if k in override:
                base[k] = int(override[k])
    return base


def check_budget(consumed: dict, budget: dict) -> str | None:
    """返回被违反的预算名（fail 原因），无违反返回 None。"""
    if consumed.get("queries", 0) >= budget["max_queries"]:
        return "budget_exhausted:max_queries"
    if consumed.get("steps", 0) >= budget["max_steps"]:
        return "budget_exhausted:max_steps"
    return None
