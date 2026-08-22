"""检索指标（Task 12 / 03 §9.2）：Recall@K、MRR、nDCG、ACL 泄漏。

纯函数、确定性。命中判定基于返回候选的 target_id 与金标准
expect_knowledge_ids 的交集。
"""
from __future__ import annotations

import math
from typing import Any


def recall_at_k(retrieved_ids: list[str], relevant_ids: list[str],
                k: int) -> float:
    """前 K 个检索结果中覆盖的相关项比例（relevant 为空 → 1.0）。"""
    if not relevant_ids:
        return 1.0
    topk = retrieved_ids[:k]
    hit = len(set(topk) & set(relevant_ids))
    return hit / len(relevant_ids)


def mrr(retrieved_ids: list[str], relevant_ids: list[str]) -> float:
    """Mean Reciprocal Rank：第一个相关项的 1/rank（无命中 → 0）。"""
    if not relevant_ids:
        return 1.0
    rel = set(relevant_ids)
    for i, rid in enumerate(retrieved_ids, start=1):
        if rid in rel:
            return 1.0 / i
    return 0.0


def ndcg_at_k(retrieved_ids: list[str], relevant_ids: list[str],
              k: int) -> float:
    """nDCG@K（二值相关性）。对 retrieved 去重（同一 knowledge 多 chunk
    只计一次，评审 #T12-6：防止 nDCG>1）。"""
    if not relevant_ids:
        return 1.0
    rel = set(relevant_ids)
    seen: set[str] = set()
    deduped: list[str] = []
    for rid in retrieved_ids[:k]:
        if rid not in seen:
            seen.add(rid)
            deduped.append(rid)
    dcg = 0.0
    for i, rid in enumerate(deduped, start=1):
        if rid in rel:
            dcg += 1.0 / math.log2(i + 1)
    ideal = sum(1.0 / math.log2(i + 1)
                for i in range(1, min(len(relevant_ids), k) + 1))
    return min(1.0, dcg / ideal) if ideal > 0 else 0.0


def span_recall(retrieved_quotes: list[str],
                expected_substrings: list[str]) -> float:
    """证据片段召回：期望子串出现在任一返回片段中的比例。"""
    if not expected_substrings:
        return 1.0
    blob = "\n".join(retrieved_quotes)
    hit = sum(1 for s in expected_substrings if s in blob)
    return hit / len(expected_substrings)


def acl_leakage(leaks: list[dict[str, Any]]) -> int:
    """ACL 泄漏计数（必须为 0）。leaks: [{query_id, leaked_ids}]。"""
    return sum(len(l.get("leaked_ids", [])) for l in leaks)


def percentile(values: list[float], pct: float) -> float | None:
    """线性插值百分位（空列表 → None，不得以 0 充数）。"""
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    frac = k - lo
    return xs[lo] * (1 - frac) + xs[hi] * frac
