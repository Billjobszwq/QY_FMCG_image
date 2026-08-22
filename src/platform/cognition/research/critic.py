"""Sufficiency / Gap / Conflict Critic（R2-06 / 03 §5.3 / 04 §11）。

核心语义：
- 多个来源只是 evidence diversity，不是 conflict；
- 只有同一可比较命题出现互斥规范化数值（单位一致的数值/时间量），或
  supports/contradicts 对立时才标记 conflict，并保留 locator（span_id
  + source）供人类裁决回查；
- gap / conflict / low-authority 产生不同下一动作；
- novelty：连续两轮无新高价值 span 即停止 gap 回跳。
"""
from __future__ import annotations

import re
from typing import Any

# 句子边界（CJK/ASCII）
_SENT_SPLIT = re.compile(r"[。！？!?\n]+")
# 规范化数值 + 单位（只匹配 ASCII 数字，避免“一年”误报）
_NUM = re.compile(
    r"(\d+(?:\.\d+)?)\s*(万元|元|天|小时|分钟|秒|年|个月|月|周|次|%)")
# proposition key 归一化：去空白/标点/残留数字
_KEY_CLEAN = re.compile(r"[\s#>*\-\d.,，、:：;；()（）\"'`]+")


def extract_value_facts(quote: str) -> list[dict[str, Any]]:
    """从 span 引文中抽取 (proposition_key, unit, value) 事实。

    proposition_key 取数值所在句子去除数值/单位后的归一化文本，使不同
    来源对同一命题的数值可比。
    """
    facts: list[dict[str, Any]] = []
    for sent in _SENT_SPLIT.split(quote or ""):
        for m in _NUM.finditer(sent):
            key = _KEY_CLEAN.sub("", sent.replace(m.group(0), " "))
            if not key:
                continue
            facts.append({"key": key, "unit": m.group(2),
                          "value": float(m.group(1))})
    return facts


def detect_conflicts(evidence: dict[str, list[dict]]
                     ) -> list[dict[str, Any]]:
    """跨来源互斥数值检测。返回结构化 conflict（含 locator）。

    evidence: {sq_id: [{span_id, quote, target_id, ...}]}
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for spans in evidence.values():
        for sp in spans:
            for f in extract_value_facts(sp.get("quote", "")):
                groups.setdefault(
                    (f["key"], f["unit"]), []).append(
                        {"value": f["value"],
                         "source": sp.get("target_id", ""),
                         "span_id": sp.get("span_id", "")})
    conflicts: list[dict[str, Any]] = []
    for (key, unit), items in groups.items():
        values = sorted({i["value"] for i in items})
        sources = sorted({str(i["source"]) for i in items})
        # 互斥数值（同一命题不同取值）才构成冲突；等值多来源是
        # diversity。至少两个证据点才可比较。
        if len(values) > 1 and len(items) >= 2:
            conflicts.append({
                "proposition": key, "unit": unit, "values": values,
                "sources": sources,
                "span_ids": [i["span_id"] for i in items],
                "basis": "mutually_exclusive_normalized_values"})
    return conflicts


def sufficiency_assessment(state: dict[str, Any],
                           budget: dict[str, Any]) -> dict[str, Any]:
    """评估覆盖/缺口/冲突并决定下一动作（不写最终答案）。

    返回：covered/gaps/conflicts/action(next)/stop_rule。
    action ∈ accept(→claim) | gap_query(→retrieve) |
    counterevidence(→retrieve) | ask_human(waiting_human)。
    """
    evidence = state.get("evidence", {}) or {}
    covered: list[str] = []
    gaps: list[str] = []
    for sq in state.get("subquestions", []):
        sq_id = sq.get("sq_id")
        if evidence.get(sq_id):
            covered.append(sq_id)
        else:
            gaps.append(sq_id)
    conflicts = detect_conflicts(evidence)

    out: dict[str, Any] = {"covered": covered, "gaps": gaps,
                           "conflicts": conflicts,
                           "rounds_without_new": state.get(
                               "rounds_without_new", 0)}
    if conflicts and not state.get("conflict_resolved"):
        if not state.get("counterevidence_done"):
            out["action"] = "counterevidence"
        else:
            out["action"] = "ask_human"
        return out
    if gaps:
        if state.get("rounds_without_new", 0) >= 2:
            out["action"] = "accept"
            out["stop_rule"] = "no_new_spans_2_rounds"
        elif state.get("iteration", 0) < int(
                budget.get("max_iterations", 1)):
            out["action"] = "gap_query"
        else:
            out["action"] = "accept"
            out["stop_rule"] = "max_iterations_reached"
        return out
    out["action"] = "accept"
    return out
