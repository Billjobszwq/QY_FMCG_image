"""VLM-010：Qwen3-VL 零样本/评估契约（确定性纯函数）。

红线：
- 高 precision 不能掩盖零 coverage：全 abstain 时 accepted_precision=None
  且 gate_pass=False；
- candidate escape（accepted 给出候选外 SKU）必须为 0；
- schema 不合规不得过 gate；
- 分母为 0 的指标一律 None，不得伪造 1.0；
- identity 判定一律走 canonical sku_id（任务书§十五）：GT 展示名与
  KB 展示名禁止原始字符串比较；别名/包装差异经
  dataset_class → canonical_sku_id → package_version_id → KB vector_id
  映射链归一后比较；映射缺失按类别落账（见 ERROR_TAXONOMY）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ...catalog import naming

EVALUATION_VERSION = "vlm-evaluation.v1"
EVALUATION_V2_VERSION = "vlm-evaluation.v2"

# 任务书§十五：zero-shot V2 评估报告错误分类（7 类，逐条落账）
ERROR_TAXONOMY = (
    "true_kb_missing",          # canonical 有映射但 KB 无该产品任何向量
    "alias_mapping_missing",    # Registry 有该 SKU 但缺 alias→KB 映射
    "package_version_mismatch", # 同产品不同包装版本（GT 版本不在 KB 或 pred 版本≠GT）
    "retrieval_miss",           # GT 在 KB，但检索 ranking 未召回 GT 向量
    "reranker_miss",            # 检索已召回 GT，但重排后判错/弃答
    "registry_escape",          # Registry 也没有该 SKU（真·未登记）
    "unknown/new_packaging",    # GT 标注为 kb_missing/新包装，不参与正确率分母
)
IDENTITY_MATCH = "identity_match"  # canonical sku_id 判对（非错误类别）


# ---------- canonical sku identity 解析层（确定性纯函数） ----------

@dataclass(frozen=True)
class SkuIdentity:
    """一个名称经映射链归一后的 canonical 身份。

    链：dataset_class 展示名 → sku_id（data/sku_registry.json）→
    package_version_id（data/sku_aliases.json 的 kb_folder）→
    KB vector_id（.kb/vector_ids.json，等于 kb_folder）。
    """

    raw: str
    sku_id: str | None = None            # canonical sku id（Registry）
    package_version_id: str | None = None  # kb_folder（KB 向量主键）
    kb_vector_id: str | None = None      # package_version 在 KB 中才有
    product_key: tuple | None = None     # (糖度, 风味核)：版本无关产品身份
    kb_missing: bool = False             # 别名表标注的新品/新包装占位
    method: str = "none"                 # exact / norm / kb_id / none


class SkuIdentityIndex:
    """映射链索引：registry + alias 表 + KB vector id 三路合并。

    数据来源（先读代码确认的实际结构，不得凭空发明字段）：
    - registry: data/sku_registry.json 的 {展示名: {sku_id, class_id}}；
    - alias_entries: data/sku_aliases.json 的 canonicals 列表，字段
      kb_folder / aliases / kb_missing / display；
    - kb_vector_ids: .kb/vector_ids.json（= KB 各 SKU 的 kb_folder）。
    """

    def __init__(self, *, registry: Mapping[str, Mapping] | None = None,
                 alias_entries: Sequence[Mapping] | None = None,
                 kb_vector_ids: Sequence[str] | None = None):
        self._registry: dict[str, str] = {
            str(name): str(info.get("sku_id"))
            for name, info in (registry or {}).items()
            if isinstance(info, Mapping) and info.get("sku_id")}
        self._kb_ids: set[str] = {str(v) for v in (kb_vector_ids or [])}
        self._name_to_pv: dict[str, str] = {}   # 别名/展示名/kb_folder → kb_folder
        self._pv_to_sku: dict[str, str] = {}    # kb_folder → canonical sku_id
        self._kb_missing_names: set[str] = set()
        for entry in alias_entries or []:
            kb = entry.get("kb_folder")
            aliases = [str(a) for a in (entry.get("aliases") or [])]
            display = entry.get("display")
            if entry.get("kb_missing") or not kb:
                for a in aliases + ([str(display)] if display else []):
                    self._kb_missing_names.add(a)
                continue
            kb = str(kb)
            for a in aliases + [kb] + ([str(display)] if display else []):
                self._name_to_pv[a] = kb
            for a in aliases:
                if a in self._registry:
                    self._pv_to_sku[kb] = self._registry[a]
                    break
        # 归一兜底索引（naming.match_key 唯一命中才采用，避免静默错配）
        self._norm_sku: dict[tuple, str] = {}
        for name, sku in self._registry.items():
            self._norm_sku.setdefault(naming.match_key(name), sku)
        self._norm_pv: dict[tuple, str] = {}
        for name, pv in self._name_to_pv.items():
            self._norm_pv.setdefault(naming.match_key(name), pv)
        for kb in self._kb_ids:
            self._norm_pv.setdefault(naming.match_key(kb), kb)
        # 产品身份（版本无关）→ KB 中实际存在的包装版本集合
        self._product_versions: dict[tuple, set] = {}
        for kb in self._kb_ids:
            key = self._product_key(kb)
            self._product_versions.setdefault(key, set()).add(kb)

    @staticmethod
    def _product_key(name: str) -> tuple:
        """版本无关产品身份 = (糖度, 风味核)，剔除容量/PET 等包装信息。"""
        mk = naming.match_key(name)
        return (mk[1], mk[2])

    def resolve_sku_identity(self, name: str | None) -> SkuIdentity:
        """任意展示名 → canonical 身份；无法解析时各字段为 None。"""
        raw = "" if name is None else str(name)
        if not raw:
            return SkuIdentity(raw=raw)
        if raw in self._kb_missing_names:
            return SkuIdentity(raw=raw,
                               sku_id=self._registry.get(raw),
                               product_key=self._product_key(raw),
                               kb_missing=True, method="exact")
        sku = self._registry.get(raw)
        pv = self._name_to_pv.get(raw)
        method = "exact" if (sku or pv) else "none"
        if pv is None and raw in self._kb_ids:
            pv, method = raw, "kb_id"
        if sku is None and pv is None:  # 归一兜底：唯一命中才采用
            mk = naming.match_key(raw)
            hit_sku = [v for k, v in self._norm_sku.items() if k == mk]
            hit_pv = [v for k, v in self._norm_pv.items() if k == mk]
            if len(hit_sku) == 1 or len(hit_pv) == 1:
                sku = sku or (hit_sku[0] if len(hit_sku) == 1 else None)
                pv = pv or (hit_pv[0] if len(hit_pv) == 1 else None)
                method = "norm"
        if sku is None and pv is not None:
            sku = self._pv_to_sku.get(pv)
        return SkuIdentity(
            raw=raw, sku_id=sku, package_version_id=pv,
            kb_vector_id=pv if pv in self._kb_ids else None,
            product_key=self._product_key(raw),
            kb_missing=False, method=method)

    def product_versions_in_kb(self, product_key: tuple | None) -> set:
        if product_key is None:
            return set()
        return set(self._product_versions.get(product_key, set()))

    def ranking_has_gt(self, gt_id: SkuIdentity,
                       ranking: Sequence[str] | None) -> bool:
        """检索 ranking 是否召回 GT（canonical 口径：同 sku_id 即召回）。"""
        for cand in ranking or []:
            cid = self.resolve_sku_identity(cand)
            if gt_id.kb_vector_id and cid.kb_vector_id == gt_id.kb_vector_id:
                return True
            if gt_id.sku_id and cid.sku_id == gt_id.sku_id:
                return True
        return False


def build_default_identity_index(project_root, kb_root=None) -> SkuIdentityIndex:
    """从项目默认数据源构建映射链索引（文件缺失时该路为空，不抛错）。"""
    root = Path(project_root)
    registry: dict = {}
    reg_path = root / "data" / "sku_registry.json"
    if reg_path.is_file():
        registry = json.loads(reg_path.read_text(encoding="utf-8"))
        registry.pop("_doc", None)
    alias_entries: list = []
    alias_path = root / "data" / "sku_aliases.json"
    if alias_path.is_file():
        alias_entries = json.loads(
            alias_path.read_text(encoding="utf-8")).get("canonicals", [])
    kb_dir = Path(kb_root) if kb_root else root / ".kb"
    kb_vector_ids: list = []
    vid_path = kb_dir / "vector_ids.json"
    if vid_path.is_file():
        kb_vector_ids = json.loads(vid_path.read_text(encoding="utf-8"))
    return SkuIdentityIndex(registry=registry, alias_entries=alias_entries,
                            kb_vector_ids=kb_vector_ids)


def resolve_sku_identity(name, *, registry=None, alias_entries=None,
                         kb_vector_ids=None) -> SkuIdentity:
    """便捷入口：一次性构建索引解析单个名称（批量请用 SkuIdentityIndex）。"""
    idx = SkuIdentityIndex(registry=registry, alias_entries=alias_entries,
                           kb_vector_ids=kb_vector_ids)
    return idx.resolve_sku_identity(name)


def classify_sku_identity(record: Mapping[str, Any],
                          index: SkuIdentityIndex) -> str:
    """单条记录的 canonical 身份分类（ERROR_TAXONOMY ∪ IDENTITY_MATCH）。

    判定顺序：unknown/new_packaging → registry_escape →
    alias_mapping_missing → package_version_mismatch / true_kb_missing →
    （GT 已在 KB）identity_match / package_version_mismatch /
    reranker_miss / retrieval_miss。
    """
    gt_id = index.resolve_sku_identity(record.get("gt"))
    decision = record.get("decision")
    if decision in ("unknown", "new_package", "new_packaging") \
            or gt_id.kb_missing:
        return "unknown/new_packaging"
    if gt_id.sku_id is None:
        return "registry_escape"
    if gt_id.package_version_id is None:
        return "alias_mapping_missing"
    if gt_id.kb_vector_id is None:
        if index.product_versions_in_kb(gt_id.product_key):
            return "package_version_mismatch"
        return "true_kb_missing"
    # GT 的包装版本在 KB：比较 pred 的 canonical 身份
    if decision == "accepted" and record.get("pred") is not None:
        pred_id = index.resolve_sku_identity(record["pred"])
        if pred_id.sku_id is not None and pred_id.sku_id == gt_id.sku_id:
            if pred_id.package_version_id != gt_id.package_version_id:
                return "package_version_mismatch"
            return IDENTITY_MATCH
        if pred_id.product_key == gt_id.product_key:
            return "package_version_mismatch"
        if index.ranking_has_gt(gt_id, record.get("retrieval_ranking")):
            return "reranker_miss"
        return "retrieval_miss"
    if index.ranking_has_gt(gt_id, record.get("retrieval_ranking")):
        return "reranker_miss"
    return "retrieval_miss"


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


def evaluate_records_v2(
    records: Iterable[Mapping[str, Any]],
    *,
    min_accepted_precision: float = 0.9,
    wall_seconds: float | None = None,
    identity_index: SkuIdentityIndex | None = None,
) -> dict[str, Any]:
    """V2 评估（方法修正版，用户指令第十节 + 任务书§十五）。

    与 V1 的区别：
    - candidate_recall_at_1/5/8 基于 retrieval_ranking 的真实前 k 个
      （predicted ranking），不再是 'gt ∈ 完整 K 列表'；候选不足 k
      自然截断，不得伪造；分母为 GT 已在 KB 的记录；
    - 新增 registry_escape（GT 不在 KB/Registry）、kb_coverage_of_sample、
      abstain_rate、auto_coverage、每区域成本；
    - 分母为 0 的指标一律 None（不得伪造 1.0）。

    任务书§十五（canonical 口径）：传入 identity_index 时，identity
    判定一律走 canonical sku_id（禁止展示名字符串比较）：
    accepted_precision / recall@k / registry_escape /
    kb_coverage_of_sample 均按映射链重算，并输出逐条 error_taxonomy
    （7 类）；不传 identity_index 时保持旧口径（兼容性）。

    记录必需字段：gt/decision/pred/retrieval_ranking/n_candidates/
    gt_in_registry/schema_ok/candidate_escape/latency_ms/
    prompt_tokens/completion_tokens/error/source/photo_id/store/session。
    """
    recs = list(records)
    total = len(recs)
    if total == 0:
        return {"evaluation_version": EVALUATION_V2_VERSION, "total": 0,
                "auto_coverage": 0.0, "accepted_precision": None,
                "candidate_recall_at_1": None,
                "candidate_recall_at_5": None,
                "candidate_recall_at_8": None,
                "gate_pass": False, "reason": "no_records"}

    # ---- canonical identity 分类（任务书§十五）----
    if identity_index is not None:
        cats = [classify_sku_identity(r, identity_index) for r in recs]
        taxonomy = {cat: sum(1 for c in cats if c == cat)
                    for cat in (*ERROR_TAXONOMY, IDENTITY_MATCH)}
        gt_idents = [identity_index.resolve_sku_identity(r.get("gt"))
                     for r in recs]
        in_kb = [g.kb_vector_id is not None for g in gt_idents]

        def _recall_at(k: int) -> float | None:
            eligible = [i for i, r in enumerate(recs) if in_kb[i]]
            if not eligible:
                return None
            hits = 0
            for i in eligible:
                topk = list(recs[i].get("retrieval_ranking") or [])[:k]
                if identity_index.ranking_has_gt(gt_idents[i], topk):
                    hits += 1
            return hits / len(eligible)

        accepted = [r for r in recs if r["decision"] == "accepted"]
        accepted_correct = sum(
            1 for i, r in enumerate(recs)
            if r["decision"] == "accepted" and cats[i] == IDENTITY_MATCH)
        accepted_precision = _ratio(accepted_correct, len(accepted))
        registry_escape = taxonomy["registry_escape"]
        kb_coverage = _ratio(sum(in_kb), total)
        identity_mode = "canonical_sku_id"
    else:
        cats, taxonomy, identity_mode = None, None, "legacy_display_name"

        def _recall_at(k: int) -> float | None:
            eligible = [r for r in recs if r["gt_in_registry"]]
            if not eligible:
                return None
            hits = sum(1 for r in eligible
                       if r["gt"] in list(r["retrieval_ranking"])[:k])
            return hits / len(eligible)

        accepted = [r for r in recs if r["decision"] == "accepted"]
        accepted_correct = sum(1 for r in accepted if r["pred"] == r["gt"])
        accepted_precision = _ratio(accepted_correct, len(accepted))
        registry_escape = sum(1 for r in recs if not r["gt_in_registry"])
        kb_coverage = _ratio(total - registry_escape, total)

    auto_coverage = len(accepted) / total
    abstain_rate = sum(1 for r in recs
                       if r["decision"] == "abstain") / total
    unknown_cnt = sum(1 for r in recs if r["decision"] in
                      ("unknown", "new_package", "new_packaging"))
    if taxonomy is not None:
        unknown_cnt += taxonomy["unknown/new_packaging"]

    schema_compliance = sum(1 for r in recs if r["schema_ok"]) / total
    escapes = sum(1 for r in recs if r["candidate_escape"])
    latencies = sorted(float(r["latency_ms"]) for r in recs)
    total_tokens = sum(int(r["prompt_tokens"]) + int(r["completion_tokens"])
                       for r in recs)
    cost_per_region = {
        "avg_latency_ms": sum(latencies) / total,
        "avg_tokens": total_tokens / total,
        "wall_seconds_per_region": (wall_seconds / total
                                    if wall_seconds else None),
    }

    error_ledger = [{"index": i, "source": r.get("source"),
                     "photo_id": r.get("photo_id"),
                     "error": r["error"], "decision": r["decision"]}
                    for i, r in enumerate(recs) if r["error"]]

    gate_pass = (
        auto_coverage > 0.0
        and accepted_precision is not None
        and accepted_precision >= min_accepted_precision
        and escapes == 0
        and schema_compliance == 1.0
    )

    report = {
        "evaluation_version": EVALUATION_V2_VERSION,
        "total": total,
        "photos": len({r.get("photo_id") for r in recs}),
        "stores": len({r.get("store") for r in recs}),
        "sessions": len({r.get("session") for r in recs}),
        "candidate_recall_at_1": _recall_at(1),
        "candidate_recall_at_5": _recall_at(5),
        "candidate_recall_at_8": _recall_at(8),
        "accepted_precision": accepted_precision,
        "auto_coverage": auto_coverage,
        "abstain_rate": abstain_rate,
        "unknown_or_new_packaging_count": unknown_cnt,
        "registry_escape": registry_escape,
        "kb_coverage_of_sample": kb_coverage,
        "schema_compliance": schema_compliance,
        "candidate_escape": escapes,
        "p50_latency_ms": _percentile(latencies, 0.50),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "cost_per_region": cost_per_region,
        "error_ledger": error_ledger,
        "min_accepted_precision": min_accepted_precision,
        "gate_pass": gate_pass,
        "note": "recall@k 基于真实检索 ranking 前 k；候选不得注入 GT；"
                "分母为 0 的指标为 None，不得伪造",
    }
    # 任务书§十五：canonical 模式追加字段（不破坏既有报告结构）
    report["identity_mode"] = identity_mode
    if taxonomy is not None:
        report["error_taxonomy"] = taxonomy
    return report
