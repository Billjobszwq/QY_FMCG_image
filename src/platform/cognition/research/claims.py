"""Claim 支持性验证（R2-07 / round-2-hardening/01 §8）。

两层验证：
1. 确定性层：数字/单位/命题键/否定方向一致性（本模块）；
2. source/span/ACL/time/scope 有效性：由 CitationVerifier 完成。

span 存在 ≠ 支持。判定集合：supports / contradicts / context /
insufficient。ClaimBuilder 初始关系必须是 unverified，只有验证后才
允许写 supports；验证记录 verifier id/version、input hash、score、
reason，可回查。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Protocol

from .critic import _KEY_CLEAN, _NUM, _SENT_SPLIT, extract_value_facts

_NEG = re.compile(r"(不得|不允许|不可以|禁止|未|没有|无|不|非)")

SUPPORT_RELATIONS = ("supports", "contradicts", "context",
                     "insufficient", "unverified")


@dataclass(frozen=True)
class SupportJudgment:
    relation: str
    score: float
    reason: str


class ClaimSupportVerifier(Protocol):
    verifier_id: str
    verifier_version: str

    def verify(self, claim_text: str, quote: str) -> SupportJudgment: ...


def _clean_tokens(text: str) -> set[str]:
    """CJK bigram + ASCII 词（与检索 tokenizer 同源的轻量版）。"""
    toks: set[str] = set()
    norm = _KEY_CLEAN.sub(" ", text or "")
    for part in norm.split():
        if re.fullmatch(r"[A-Za-z0-9]+", part):
            toks.add(part.lower())
        else:
            cjk = re.sub(r"[^一-鿿]", "", part)
            for i in range(len(cjk) - 1):
                toks.add(cjk[i:i + 2])
            if len(cjk) == 1:
                toks.add(cjk)
    return toks


def _overlap(a: str, b: str) -> float:
    ta, tb = _clean_tokens(a), _clean_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta)


def _key_bigrams(key: str) -> set[str]:
    if len(key) < 2:
        return {key} if key else set()
    return {key[i:i + 2] for i in range(len(key) - 1)}


def _key_matches(k1: str, k2: str) -> bool:
    """命题键匹配：包含关系或 bigram 高重叠（容忍插入词，如
    “机票经济舱上限” vs “机票经济舱报销上限是”）。"""
    if not k1 or not k2:
        return False
    if k1 == k2 or k1 in k2 or k2 in k1:
        return True
    b1, b2 = _key_bigrams(k1), _key_bigrams(k2)
    if not b1 or not b2:
        return False
    inter = len(b1 & b2)
    return inter / min(len(b1), len(b2)) >= 0.6


def input_hash(claim_text: str, span_ids: list[str],
               verifier_version: str) -> str:
    payload = "|".join([claim_text or "",
                             ",".join(sorted(span_ids)),
                             verifier_version])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class DeterministicClaimSupportVerifier:
    """确定性支持性验证：数值/单位/命题键/否定/主题重叠。

    不做语义推断；不可判定时给 insufficient（高重要性 Claim 由此被
    gate 阻断，而不是默认放行）。
    """

    verifier_id = "claim-support-deterministic"
    verifier_version = "1"

    def verify(self, claim_text: str, quote: str) -> SupportJudgment:
        c_facts = extract_value_facts(claim_text)
        s_facts = extract_value_facts(quote)
        overlap = _overlap(claim_text, quote)

        # 1) 数值/单位/命题键一致性
        matched_value = False
        for cf in c_facts:
            for sf in s_facts:
                if sf["unit"] != cf["unit"]:
                    continue
                if not _key_matches(cf["key"], sf["key"]):
                    continue
                if abs(sf["value"] - cf["value"]) < 1e-9:
                    matched_value = True
                else:
                    return SupportJudgment(
                        "contradicts", 0.9,
                        f"数值互斥: claim={cf['value']}{cf['unit']} "
                        f"span={sf['value']}{sf['unit']}（命题键"
                        f"{cf['key'][:30]}）")
        # 2) 否定方向一致性（主题重叠时否定词翻转 = 矛盾）
        if overlap >= 0.4:
            neg_c = bool(_NEG.search(claim_text or ""))
            neg_s = bool(_NEG.search(quote or ""))
            if neg_c != neg_s:
                return SupportJudgment(
                    "contradicts", 0.8, "否定方向不一致")
        # 3) 数值断言无匹配 → 支持不足
        if c_facts and not matched_value:
            if overlap >= 0.5:
                return SupportJudgment(
                    "context", 0.4, "主题相关但数值断言无对应证据")
            return SupportJudgment(
                "insufficient", 0.1,
                "Claim 的数值/主体断言在 span 中无对应事实")
        # 4) 无数值断言：按主题重叠判定
        if matched_value and overlap >= 0.3:
            return SupportJudgment(
                "supports", min(0.95, 0.7 + 0.3 * overlap),
                "数值与命题键一致")
        if overlap >= 0.6:
            return SupportJudgment("supports",
                                   round(0.5 + 0.4 * overlap, 4),
                                   "主题与表述高度重叠")
        if overlap >= 0.3:
            return SupportJudgment("context", round(overlap, 4),
                                   "仅提供背景，不构成支持")
        return SupportJudgment("insufficient", round(overlap, 4),
                               "主题不相关或重叠不足")
