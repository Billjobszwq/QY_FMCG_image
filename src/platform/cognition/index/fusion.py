"""检索融合（Task 8）：Reciprocal Rank Fusion + 文档多样性去重 +
rerank 端口。"""
from __future__ import annotations

from typing import Any, Protocol


class RerankerPort(Protocol):
    """重排端口：对 top-N 候选重新打分。不可用时网关必须显式跳过
    （不伪造 rerank 分）。"""

    model_name: str

    def available(self) -> bool: ...

    def rerank(self, query: str,
               items: list[dict[str, Any]]) -> list[float]: ...


def reciprocal_rank_fusion(rank_lists: list[list[tuple[str, float]]],
                           k: int = 60) -> dict[str, float]:
    """rank_lists: 每路按分数降序的 (id, score) 列表 → RRF 融合分。"""
    fused: dict[str, float] = {}
    for ranked in rank_lists:
        for rank, (cid, _score) in enumerate(ranked, start=1):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank)
    return fused


def dedup_by_document(hits: list[dict[str, Any]], *,
                      max_per_document: int) -> list[dict[str, Any]]:
    """同一 document（knowledge_id）最多保留 max_per_document 个最优
    chunk（hits 已按分数降序）。"""
    counts: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for h in hits:
        doc = h["document_key"]
        if counts.get(doc, 0) >= max_per_document:
            continue
        counts[doc] = counts.get(doc, 0) + 1
        out.append(h)
    return out
