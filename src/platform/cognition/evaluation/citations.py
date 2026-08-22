"""引证指标（Task 12 / 03 §9.2）：citation precision/recall/support。

纯函数、确定性。基于 claim 的 support_status 与引证关系。
"""
from __future__ import annotations


def citation_support_rate(claims: list[dict]) -> float:
    """有证据支持的 claim 比例（supported / 全部可验证 claim）。"""
    verifiable = [c for c in claims
                  if c.get("claim_type") in ("fact", "inference")]
    if not verifiable:
        return 1.0
    supported = [c for c in verifiable
                 if c.get("support_status") == "supported"]
    return len(supported) / len(verifiable)


def unsupported_high_importance(claims: list[dict]) -> int:
    """高重要性且无支持/被反驳的 claim 数（发布硬门，必须为 0）。"""
    return sum(1 for c in claims
               if c.get("importance") == "high"
               and c.get("support_status") in ("unsupported",
                                               "contradicted"))


def citation_precision(citations: list[dict]) -> float:
    """引证精确率：supports 关系引证占比（剔除 contradicts/context 噪声）。"""
    if not citations:
        return 1.0
    supports = [c for c in citations if c.get("relation") == "supports"]
    return len(supports) / len(citations)


def run_citation_gold(store, gold_path=None) -> dict:
    """用人工 gold relation 计算 citation precision/recall（R2-08）。

    不得把系统自己写入的 relation 当真值：对每条 gold (claim_text,
    span_quote, gold_relation) 重新跑支持性验证器得到系统 relation，
    再与 gold 对照。
    - precision = 系统判 supports 且 gold 为 supports / 系统判 supports 总数
    - recall_high_importance = gold supports 且高重要性中被系统判 supports
      的比例
    fixture 缺失 → measured=False（fail-closed，不以满分充数）。
    """
    import json
    from pathlib import Path
    from ..research.claims import DeterministicClaimSupportVerifier
    if gold_path is None:
        gold_path = (Path(__file__).resolve().parents[4] / "tests" /
                     "fixtures" / "cognition" /
                     "gold_claim_citations.jsonl")
    gold_path = Path(gold_path)
    if not gold_path.exists():
        return {"measured": False, "precision": None,
                "recall_high_importance": None, "samples": 0}
    verifier = DeterministicClaimSupportVerifier()
    pred_supports = 0
    tp_supports = 0
    hi_total = 0
    hi_tp = 0
    n = 0
    for line in gold_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        d = json.loads(line)
        n += 1
        j = verifier.verify(d["claim_text"], d["span_quote"])
        sys_supports = (j.relation == "supports")
        gold_supports = (d["gold_relation"] == "supports")
        if sys_supports:
            pred_supports += 1
            if gold_supports:
                tp_supports += 1
        if gold_supports and d.get("importance") == "high":
            hi_total += 1
            if sys_supports:
                hi_tp += 1
    precision = (tp_supports / pred_supports) if pred_supports else None
    recall_hi = (hi_tp / hi_total) if hi_total else None
    return {"measured": True, "precision": precision,
            "recall_high_importance": recall_hi, "samples": n,
            "verifier": f"{verifier.verifier_id}@{verifier.verifier_version}"}
