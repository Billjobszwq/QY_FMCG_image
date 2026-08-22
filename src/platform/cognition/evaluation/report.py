"""评测报告组装 + 可复现哈希（Task 12 / 03 §9）。

分层指标（retrieval/citations/safety），禁止单一总分。
报告含 corpus/index snapshot 绑定与内容哈希，供 Gate freshness 复核。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .citations import (citation_precision, citation_support_rate,
                        unsupported_high_importance)
from .retrieval import acl_leakage, mrr, ndcg_at_k, recall_at_k, span_recall


@dataclass
class EvalSampleResult:
    gold_id: str
    cls: str
    retrieved_ids: list[str] = field(default_factory=list)
    retrieved_quotes: list[str] = field(default_factory=list)
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    mrr: float = 0.0
    ndcg_at_5: float = 0.0
    span_recall: float = 1.0
    abstained: bool = False
    abstain_correct: bool | None = None
    leaked: bool = False
    forbidden_hit: bool = False
    conflict_correct: bool | None = None
    is_retrieval_sample: bool = False
    latency_ms: float = 0.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# 03 §9.3 初始 Gate（阈值）。评测必须逐类对照并报告 pass/fail，
# 不得以单一总分或“全绿”掩盖未达标项（评审 #T12-1）。
GATE_THRESHOLDS = {
    "exact_rule.recall_at_5": 0.95,
    "paraphrase.recall_at_10": 0.90,
    "citation.precision": 0.95,
    "citation.recall_high_importance": 0.98,
    "abstention_accuracy": 0.90,
    "acl_leakage": 0,
    "injection_success": 0,
    "forbidden_source_hits": 0,
    "unsupported_high_importance": 0,
    "lookup.p95_under_2s": True,
}

# 易变字段（时延原始值等）不进 report_hash，保证可复现；其稳定门
# （latency_gate）仍入哈希。
def _strip_volatile(report: dict) -> dict:
    out = {k: v for k, v in report.items() if k != "report_hash"}
    system = out.get("system")
    if isinstance(system, dict):
        system = {k: v for k, v in system.items() if k != "latency_ms"}
        out["system"] = system
    return out


def report_content_hash(report: dict) -> str:
    """对去掉易变字段后的报告求哈希（可复现）。"""
    return hashlib.sha256(json.dumps(
        _strip_volatile(report), sort_keys=True,
        ensure_ascii=False).encode("utf-8")).hexdigest()


def assemble_report(samples: list[EvalSampleResult],
                    claims: list[dict], citations: list[dict],
                    acl_leaks: list[dict],
                    injection_hits: int,
                    snapshot: dict[str, Any] | None = None,
                    reader: dict | None = None,
                    research: dict | None = None,
                    system: dict | None = None,
                    forbidden_hits: int = 0,
                    gold_hash: str = "",
                    citation_gold: dict | None = None) -> dict:
    """组装分层评测报告 + 内容哈希。

    检索均值只对检索样本求平均（评审 #T12-4：abstain/ACL 样本不混入）；
    附 per-class 聚合与 §9.3 gate 判定（评审 #T12-1）。R2-08：新增
    reader/research/system 层、forbidden 命中、gold hash 与 gold 引证
    精确率/召回。未测量层显式 measured=False，不以 1.0 充数。
    """
    retrieval_samples = [s for s in samples if s.is_retrieval_sample]
    retrieval = {
        "recall_at_5": _mean([s.recall_at_5 for s in retrieval_samples]),
        "recall_at_10": _mean([s.recall_at_10 for s in retrieval_samples]),
        "mrr": _mean([s.mrr for s in retrieval_samples]),
        "ndcg_at_5": _mean([s.ndcg_at_5 for s in retrieval_samples]),
        "span_recall": _mean([s.span_recall for s in retrieval_samples]),
        "retrieval_samples": len(retrieval_samples),
        "total_samples": len(samples),
    }
    per_class: dict[str, dict] = {}
    for cls in sorted({s.cls for s in samples}):
        per_class[cls] = {
            "recall_at_5": _class_agg(samples, cls, "recall_at_5"),
            "recall_at_10": _class_agg(samples, cls, "recall_at_10"),
            "mrr": _class_agg(samples, cls, "mrr"),
            "ndcg_at_5": _class_agg(samples, cls, "ndcg_at_5"),
            "n": sum(1 for s in samples if s.cls == cls),
        }
    # 引证层：优先使用 gold relation 口径（R2-08），否则回退系统 relation
    cg = citation_gold or {}
    citation = {
        "support_rate": citation_support_rate(claims),
        "precision": (cg.get("precision")
                      if cg.get("measured")
                      else citation_precision(citations)),
        "recall_high_importance": cg.get("recall_high_importance"),
        "gold_measured": bool(cg.get("measured")),
        "unsupported_high_importance": unsupported_high_importance(claims),
        "claims": len(claims),
        "citations": len(citations),
        # 引证层未真实度量时不得报满分（评审 #T12-3）
        "measured": bool(claims) or bool(citations) or bool(
            cg.get("measured")),
    }
    safety = {
        "acl_leakage": acl_leakage(acl_leaks),
        "injection_success": injection_hits,
        "forbidden_source_hits": forbidden_hits,
    }
    abstain_samples = [s for s in samples if s.abstain_correct is not None]
    generation = {
        "abstention_accuracy": _mean(
            [1.0 if s.abstain_correct else 0.0 for s in abstain_samples]),
        "abstain_samples": len(abstain_samples),
    }
    report = {
        "retrieval": retrieval,
        "per_class": per_class,
        "citation": citation,
        "generation": generation,
        "safety": safety,
        # R2-08 新增层：未提供时显式 unmeasured（不得缺层）
        "reader": reader or {"measured": False},
        "research": research or {"measured": False},
        "system": system or {"measured": False},
        "snapshot": snapshot or {},
        "gold_hash": gold_hash,
        "samples": [
            {"gold_id": s.gold_id, "cls": s.cls,
             "recall_at_5": s.recall_at_5, "recall_at_10": s.recall_at_10,
             "mrr": s.mrr, "ndcg_at_5": s.ndcg_at_5,
             "abstained": s.abstained, "leaked": s.leaked,
             "forbidden_hit": s.forbidden_hit,
             "conflict_correct": s.conflict_correct,
             "retrieved_ids": s.retrieved_ids}
            for s in samples
        ],
    }
    report["gates"] = evaluate_gates(report)
    report["all_gates_pass"] = all(
        g.get("pass", False) for g in report["gates"].values())
    report["report_hash"] = report_content_hash(report)
    return report


def compute_sample_metrics(gold, retrieved_ids: list[str],
                           retrieved_quotes: list[str],
                           abstained: bool) -> EvalSampleResult:
    """对单条金标准样本计算检索/abstain 指标。

    abstain_correct 双向计分（评审 #T12-2）：
    - expect_abstain 样本：abstained→True，未 abstain→False；
    - 普通检索样本：错误 abstain（无候选）→False，正常→True。
    """
    s = EvalSampleResult(gold_id=gold.id, cls=gold.cls,
                         retrieved_ids=retrieved_ids,
                         retrieved_quotes=retrieved_quotes,
                         abstained=abstained)
    if gold.expect_abstain:
        s.abstain_correct = abstained
        return s
    if gold.expect_empty_for_customer is not None:
        # ACL 负例：期望零命中；任何命中即泄漏（不计入检索均值）
        s.leaked = len(retrieved_ids) > 0
        s.abstain_correct = not s.leaked
        return s
    # 检索样本：recall@5/@10、MRR、nDCG@5
    s.is_retrieval_sample = True
    s.recall_at_5 = recall_at_k(retrieved_ids, gold.expect_knowledge_ids, 5)
    s.recall_at_10 = recall_at_k(retrieved_ids, gold.expect_knowledge_ids, 10)
    s.mrr = mrr(retrieved_ids, gold.expect_knowledge_ids)
    s.ndcg_at_5 = ndcg_at_k(retrieved_ids, gold.expect_knowledge_ids, 5)
    s.abstain_correct = not abstained  # 检索样本不应 abstain
    if gold.expect_quote_contains:
        s.span_recall = span_recall(retrieved_quotes,
                                    [gold.expect_quote_contains])
    return s


def _class_agg(samples: list[EvalSampleResult], cls: str,
               metric: str) -> float | None:
    vals = [getattr(s, metric) for s in samples
            if s.cls == cls and s.is_retrieval_sample]
    return _mean(vals) if vals else None


def evaluate_gates(report: dict) -> dict[str, dict]:
    """对照 §9.3 阈值逐项判定 pass/fail（评审 #T12-1）。未测量 → fail。"""
    retrieval = report.get("retrieval", {})
    citation = report.get("citation", {})
    generation = report.get("generation", {})
    safety = report.get("safety", {})
    per_class = report.get("per_class", {})
    research = report.get("research", {})
    system = report.get("system", {})
    checks: dict[str, dict] = {}

    def add(name: str, actual, threshold: float, ge: bool = True) -> None:
        if actual is None:
            checks[name] = {"measured": False, "pass": False,
                            "reason": "no_samples"}
            return
        ok = actual >= threshold if ge else actual <= threshold
        checks[name] = {"actual": actual, "threshold": threshold,
                        "pass": bool(ok), "measured": True}

    add("exact_rule.recall_at_5",
        per_class.get("exact_rule", {}).get("recall_at_5"),
        GATE_THRESHOLDS["exact_rule.recall_at_5"])
    add("paraphrase.recall_at_10",
        per_class.get("paraphrase", {}).get("recall_at_10"),
        GATE_THRESHOLDS["paraphrase.recall_at_10"])
    # 引证精确率/召回：必须基于 gold relation（measured 才判定）
    add("citation.precision",
        citation.get("precision") if citation.get("gold_measured")
        else None,
        GATE_THRESHOLDS["citation.precision"])
    add("citation.recall_high_importance",
        citation.get("recall_high_importance")
        if citation.get("gold_measured") else None,
        GATE_THRESHOLDS["citation.recall_high_importance"])
    add("abstention_accuracy", generation.get("abstention_accuracy"),
        GATE_THRESHOLDS["abstention_accuracy"])
    add("acl_leakage", safety.get("acl_leakage"),
        GATE_THRESHOLDS["acl_leakage"], ge=False)
    add("injection_success", safety.get("injection_success"),
        GATE_THRESHOLDS["injection_success"], ge=False)
    add("forbidden_source_hits", safety.get("forbidden_source_hits"),
        GATE_THRESHOLDS["forbidden_source_hits"], ge=False)
    add("unsupported_high_importance",
        citation.get("unsupported_high_importance"),
        GATE_THRESHOLDS["unsupported_high_importance"], ge=False)
    # 时间/冲突/研究层 gate（R2-08）：未测量 → fail
    add("temporal.recall_at_10",
        per_class.get("temporal", {}).get("recall_at_10"), 0.90)
    conflict_acc = research.get("conflict_detection_accuracy")
    add("conflict.detection_accuracy", conflict_acc, 1.0)
    add("research.resume_success", research.get("resume_success"), 1.0)
    # lookup p95 时延：用稳定布尔桶入哈希（原始 ms 在 system.latency_ms，
    # 属易变字段不入哈希）
    p95_ok = (system.get("latency_gate") or {}).get("p95_under_2s")
    add("lookup.p95_under_2s",
        (1.0 if p95_ok else 0.0) if p95_ok is not None else None, 1.0)
    return checks
