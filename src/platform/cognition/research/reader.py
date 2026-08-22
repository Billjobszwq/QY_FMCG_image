"""Evidence Reader（R2-06 / 04 §10）：从已权限过滤的检索命中抽取
可定位证据 span；并提供受控查询改写（gap/counterevidence）。

规则：quote 必须来自检索结果，不改写成更强结论；counterevidence
查询保持中性，不得把期望结论写成事实前提。
"""
from __future__ import annotations

import re
from typing import Any

_TRAIL_PUNCT = re.compile(r"[?？。！!\s]+$")


def extract_evidence(hits_by_sq: dict[str, list[dict]]
                     ) -> dict[str, list[dict]]:
    """hits → 每子问题的 span 证据列表（span_id/chunk_id/quote/来源）。"""
    evidence: dict[str, list[dict]] = {}
    for sq_id, hits in (hits_by_sq or {}).items():
        spans = []
        for h in hits:
            for sp in h.get("spans", []):
                spans.append({"span_id": sp["span_id"],
                              "chunk_id": sp.get("chunk_id"),
                              "quote": sp.get("normalized_quote", ""),
                              "target_id": h["target_id"],
                              "target_kind": h["target_kind"]})
        evidence[sq_id] = spans
    return evidence


def gap_rewrite(text: str) -> str:
    """缺口补查改写：受控扩展（同义检索面），不追加无意义填充词。"""
    base = _TRAIL_PUNCT.sub("", (text or "").strip())
    return f"{base} 相关规定 条款 细则"


def counterevidence_query(proposition: str) -> str:
    """反证查询：中性措辞，主动寻找不同规定/例外/反例，不预设结论、
    不包含具体数值断言。"""
    base = _TRAIL_PUNCT.sub("", (proposition or "").strip())
    return f"{base} 不同规定 例外 反例"
