"""词法分析端口（Task 8）。

V1 确定性 tokenizer：拉丁/数字/编号整词（保留业务编号，不做词干
截断），CJK 一元 + 二元。BM25-lite 评分（tf 饱和 + idf）。
"""
from __future__ import annotations

import math
import re
from typing import Any

LEX_ANALYZER_VERSION = "lex@1"

_WORD_RE = re.compile(r"[A-Za-z0-9_\-\.]+")
_CJK_RE = re.compile(r"[一-鿿]+")


def tokenize(text: str) -> list[str]:
    """拉丁/数字整词 + CJK 二元（不用一元：单字匹配会让无关文档
    普遍命中，破坏精确性）。"""
    toks = [t.lower() for t in _WORD_RE.findall(text or "")]
    for run in _CJK_RE.findall(text or ""):
        if len(run) == 1:
            toks.append(run)  # 孤立单字（无法成二元）保留
        else:
            toks.extend(run[i:i + 2] for i in range(len(run) - 1))
    return toks


def build_postings(docs: list[dict[str, Any]]
                   ) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    """docs: [{chunk_id, text}] → (postings: term→{chunk_id: tf},
    df: term→doc_freq)。"""
    postings: dict[str, dict[str, int]] = {}
    df: dict[str, int] = {}
    for d in docs:
        seen: set[str] = set()
        for tok in tokenize(d["text"]):
            postings.setdefault(tok, {})
            postings[tok][d["chunk_id"]] = \
                postings[tok].get(d["chunk_id"], 0) + 1
            seen.add(tok)
        for tok in seen:
            df[tok] = df.get(tok, 0) + 1
    return postings, df


def score_bm25(postings: dict[str, dict[str, int]], df: dict[str, int],
               n_docs: int, query_tokens: list[str],
               allowed: set[str], k1: float = 1.5) -> dict[str, float]:
    """BM25-lite：只对 allowed 集合内的 chunk 计分（ACL 前置过滤，
    过滤发生在评分之前，02 §1/§8.2）。"""
    scores: dict[str, float] = {}
    for tok in query_tokens:
        pl = postings.get(tok)
        if not pl:
            continue
        n_t = df.get(tok, 0)
        idf = math.log(1.0 + (n_docs - n_t + 0.5) / (n_t + 0.5))
        for cid, tf in pl.items():
            if cid not in allowed:
                continue
            scores[cid] = scores.get(cid, 0.0) + idf * (tf / (tf + k1))
    return scores
