"""VLM-010：Qwen3-VL 零样本/评估契约（确定性纯函数）。

红线：
- 高 precision 不能掩盖零 coverage：全 abstain 时 accepted_precision=None
  且 gate_pass=False；
- candidate escape（accepted 给出候选外 SKU）必须为 0；
- schema 不合规不得过 gate；
- 分母为 0 的指标一律 None，不得伪造 1.0。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

EVALUATION_VERSION = "vlm-evaluation.v1"


def record(
    *,
    gt: str | None,
    decision: str,
    pred: str | None,
    topk: list[str] | None = None,
    target_type: str = "closed_set",
    schema_ok: bool = True,
    candidate_escape: bool = False,
    attribute_correct: bool | None = None,
    latency_ms: float = 0.0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    error: str | None = None,
) -> dict[str, Any]:
    """单条评估记录（金标准 gt + 模型 decision/pred + 证据）。"""
    return {"gt": gt, "decision": decision, "pred": pred, "topk": topk,
            "target_type": target_type, "schema_ok": schema_ok,
            "candidate_escape": candidate_escape,
            "attribute_correct": attribute_correct,
            "latency_ms": latency_ms, "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens, "error": error}


def _ratio(num: int, den: int) -> float | None:
    return None if den == 0 else num / den


def _percentile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = q * (len(sorted_values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def evaluate_records(
    records: Iterable[Mapping[str, Any]],
    *,
    min_accepted_precision: float = 0.9,
    wall_seconds: float | None = None,
) -> dict[str, Any]:
    """确定性评估报告。gate_pass 必须同时满足：coverage>0、
    accepted_precision≥阈值、candidate_escape=0、schema 全合规。"""
    recs = list(records)
    total = len(recs)
    if total == 0:
        return {"evaluation_version": EVALUATION_VERSION, "total": 0,
                "coverage": 0.0, "accepted_precision": None,
                "gate_pass": False, "reason": "no_records"}

    accepted = [r for r in recs if r["decision"] == "accepted"]
    accepted_correct = sum(1 for r in accepted if r["pred"] == r["gt"])
    coverage = len(accepted) / total
    accepted_precision = _ratio(accepted_correct, len(accepted))

    with_pred = [r for r in recs if r["pred"] is not None]
    top1 = _ratio(sum(1 for r in with_pred if r["pred"] == r["gt"]),
                  len(with_pred))
    with_topk = [r for r in recs if r["topk"]]
    top5 = _ratio(sum(1 for r in with_topk if r["gt"] in r["topk"]),
                  len(with_topk))

    def _pr(kind_decision: str, kind_target: str) -> tuple:
        tp = sum(1 for r in recs if r["decision"] == kind_decision
                 and r["target_type"] == kind_target)
        precision = _ratio(tp, sum(1 for r in recs
                                   if r["decision"] == kind_decision))
        recall = _ratio(tp, sum(1 for r in recs
                                if r["target_type"] == kind_target))
        return precision, recall

    unknown_p, unknown_r = _pr("unknown", "unknown")
    new_p, new_r = _pr("new_package", "new_package")

    schema_compliance = sum(1 for r in recs if r["schema_ok"]) / total
    escapes = sum(1 for r in recs if r["candidate_escape"])

    latencies = sorted(float(r["latency_ms"]) for r in recs)
    total_tokens = sum(int(r["prompt_tokens"]) + int(r["completion_tokens"])
                       for r in recs)
    tokens_per_second = (total_tokens / wall_seconds
                         if wall_seconds else None)

    with_attr = [r for r in recs if r["attribute_correct"] is not None]
    attribute_accuracy = _ratio(
        sum(1 for r in with_attr if r["attribute_correct"]), len(with_attr))

    error_ledger = [{"index": i, "error": r["error"],
                     "decision": r["decision"]}
                    for i, r in enumerate(recs) if r["error"]]

    gate_pass = (
        coverage > 0.0
        and accepted_precision is not None
        and accepted_precision >= min_accepted_precision
        and escapes == 0
        and schema_compliance == 1.0
    )

    return {
        "evaluation_version": EVALUATION_VERSION,
        "total": total,
        "coverage": coverage,
        "accepted_precision": accepted_precision,
        "top1_accuracy": top1,
        "top5_accuracy": top5,
        "unknown_precision": unknown_p,
        "unknown_recall": unknown_r,
        "new_package_precision": new_p,
        "new_package_recall": new_r,
        "schema_compliance": schema_compliance,
        "candidate_escape": escapes,
        "attribute_accuracy": attribute_accuracy,
        "p50_latency_ms": _percentile(latencies, 0.50),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "tokens_per_second": tokens_per_second,
        "error_ledger": error_ledger,
        "min_accepted_precision": min_accepted_precision,
        "gate_pass": gate_pass,
    }
