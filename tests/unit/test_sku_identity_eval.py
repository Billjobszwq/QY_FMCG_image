"""commit 10（任务书§十五）：zero-shot V2 评估必须按 canonical sku_id 判身份。

缺陷背景：GT 展示名（如 `1250ml茉莉乌龙（无糖）`）与 KB 展示名
（如 `茉莉乌龙无糖PET1250ML`）语义相同，旧实现用原始字符串比较
判身份，误统计为 registry escape / 判错。

本测试要求：
- identity 判定一律走 canonical sku_id（dataset_class → canonical_sku_id
  → package_version_id → KB vector_id 映射链）；
- 错误分类拆分为 7 类：true_kb_missing / alias_mapping_missing /
  package_version_mismatch / retrieval_miss / reranker_miss /
  registry_escape / unknown/new_packaging；
- 展示名完全不同但 canonical 相同必须判对（不存在展示名直接相等
  比较路径）；
- 不运行任何真实推理，纯确定性函数测试。
"""
from __future__ import annotations

import hashlib

import pytest

from src.training.vlm.evaluate import (
    ERROR_TAXONOMY,
    IDENTITY_MATCH,
    SkuIdentityIndex,
    classify_sku_identity,
    evaluate_records_v2,
)

# ---------- 合成映射链夹具（结构同 data/sku_registry.json、
# data/sku_aliases.json、.kb/vector_ids.json） ----------

REGISTRY = {
    "1250ml茉莉乌龙（无糖）": {"sku_id": "QY_YL_000001", "name": "1250ml茉莉乌龙（无糖）", "class_id": 1},
    "900ml茉莉乌龙（无糖）": {"sku_id": "QY_YL_000045", "name": "900ml茉莉乌龙（无糖）", "class_id": 45},
    "1250ml原味乌龙茶（无糖）": {"sku_id": "QY_YL_000000", "name": "1250ml原味乌龙茶（无糖）", "class_id": 0},
    "500ml蜂蜜乌龙（无糖）": {"sku_id": "QY_YL_000100", "name": "500ml蜂蜜乌龙（无糖）", "class_id": 100},
    "500ml橘皮乌龙（无糖）": {"sku_id": "QY_YL_000029", "name": "500ml橘皮乌龙（无糖）", "class_id": 29},
    "1L百事": {"sku_id": "QY_YL_000007", "name": "1L百事", "class_id": 7},
}

ALIAS_ENTRIES = [
    {"kb_folder": "茉莉乌龙无糖PET1250ML", "aliases": ["1250ml茉莉乌龙（无糖）"]},
    {"kb_folder": "茉莉乌龙无糖PET900ML", "aliases": ["900ml茉莉乌龙（无糖）"]},
    {"kb_folder": "乌龙茶无糖PET1250ML", "aliases": ["1250ml原味乌龙茶（无糖）"]},
    # 有 alias 映射但 KB 没有任何该产品的向量 → true_kb_missing
    {"kb_folder": "蜂蜜乌龙无糖PET500ML", "aliases": ["500ml蜂蜜乌龙（无糖）"]},
    # kb_missing 占位（真·新品/新包装）→ unknown/new_packaging
    {"kb_folder": None, "kb_missing": True, "display": "500ml橘皮乌龙（无糖）",
     "aliases": ["500ml橘皮乌龙（无糖）"]},
]

KB_VECTOR_IDS = [
    "茉莉乌龙无糖PET1250ML",
    "乌龙茶无糖PET1250ML",
    "500ml沁桃水",  # KB 文件夹名即展示名的 KB 条目
]


@pytest.fixture()
def index() -> SkuIdentityIndex:
    return SkuIdentityIndex(registry=REGISTRY, alias_entries=ALIAS_ENTRIES,
                            kb_vector_ids=KB_VECTOR_IDS)


def _rec(**kw) -> dict:
    base = {
        "gt": None, "decision": "abstain", "pred": None,
        "retrieval_ranking": [], "n_candidates": 0,
        "gt_in_registry": False, "target_type": "closed_set",
        "schema_ok": True, "candidate_escape": False,
        "attribute_correct": None, "latency_ms": 1.0,
        "prompt_tokens": 0, "completion_tokens": 0, "error": None,
        "source": "p1#r0", "photo_id": "p1", "store": "s", "session": "d",
    }
    base.update(kw)
    return base


# ---------- 映射链：dataset_class → sku_id → package_version → KB ----------

def test_resolve_display_and_kb_name_share_canonical_sku_id(index):
    gt_id = index.resolve_sku_identity("1250ml茉莉乌龙（无糖）")
    kb_id = index.resolve_sku_identity("茉莉乌龙无糖PET1250ML")
    assert gt_id.sku_id == kb_id.sku_id == "QY_YL_000001"
    assert gt_id.package_version_id == "茉莉乌龙无糖PET1250ML"
    assert gt_id.kb_vector_id == "茉莉乌龙无糖PET1250ML"


def test_alias_normalizes_dataset_class_to_canonical(index):
    # dataset_class 经 alias → canonical_sku_id
    rid = index.resolve_sku_identity("1250ml茉莉乌龙（无糖）")
    assert rid.sku_id == "QY_YL_000001"
    assert rid.package_version_id == "茉莉乌龙无糖PET1250ML"


def test_kb_folder_named_entry_resolves_without_alias(index):
    # KB 文件夹名即展示名（如 500ml沁桃水）也必须可解析
    rid = index.resolve_sku_identity("500ml沁桃水")
    assert rid.kb_vector_id == "500ml沁桃水"


# ---------- 核心红线：展示名不同但 canonical 相同必须判对 ----------

def test_identity_match_despite_different_display_names(index):
    rec = _rec(gt="1250ml茉莉乌龙（无糖）", decision="accepted",
               pred="茉莉乌龙无糖PET1250ML")
    assert rec["pred"] != rec["gt"]  # 展示名完全不同
    assert classify_sku_identity(rec, index) == IDENTITY_MATCH
    report = evaluate_records_v2([rec], identity_index=index)
    assert report["accepted_precision"] == 1.0
    assert report["error_taxonomy"]["registry_escape"] == 0


# ---------- 7 类错误分类 ----------

def test_package_version_mismatch_not_escape(index):
    # pred 同产品不同包装版本 → package_version_mismatch
    rec = _rec(gt="1250ml茉莉乌龙（无糖）", decision="accepted",
               pred="茉莉乌龙无糖PET900ML")
    assert classify_sku_identity(rec, index) == "package_version_mismatch"
    # GT 的包装版本不在 KB 但同产品其他版本在 KB → 同样归类
    rec2 = _rec(gt="900ml茉莉乌龙（无糖）")
    assert classify_sku_identity(rec2, index) == "package_version_mismatch"


def test_true_kb_missing(index):
    # canonical 有映射但 KB 完全没有该产品向量
    rec = _rec(gt="500ml蜂蜜乌龙（无糖）")
    assert classify_sku_identity(rec, index) == "true_kb_missing"


def test_alias_mapping_missing_vs_registry_escape(index):
    # Registry 有但缺 alias 映射 → alias_mapping_missing
    assert classify_sku_identity(_rec(gt="1L百事"), index) == \
        "alias_mapping_missing"
    # Registry 也没有 → registry_escape
    assert classify_sku_identity(_rec(gt="果粒橙1.8L"), index) == \
        "registry_escape"


def test_unknown_new_packaging_excluded_from_recall_denominator(index):
    rec = _rec(gt="500ml橘皮乌龙（无糖）")
    assert classify_sku_identity(rec, index) == "unknown/new_packaging"
    report = evaluate_records_v2([rec], identity_index=index)
    assert report["error_taxonomy"]["unknown/new_packaging"] == 1
    # 与现有口径一致：不参与 recall 分母（分母为 0 → None）
    assert report["candidate_recall_at_1"] is None


def test_retrieval_miss_vs_reranker_miss(index):
    # GT 在 KB，但检索 ranking 未含 GT 向量 → retrieval_miss
    rec = _rec(gt="1250ml茉莉乌龙（无糖）", decision="abstain",
               retrieval_ranking=["500ml沁桃水", "乌龙茶无糖PET1250ML"])
    assert classify_sku_identity(rec, index) == "retrieval_miss"
    # 检索命中但重排后判错/弃答 → reranker_miss
    rec2 = _rec(gt="1250ml茉莉乌龙（无糖）", decision="abstain",
                retrieval_ranking=["茉莉乌龙无糖PET1250ML", "500ml沁桃水"])
    assert classify_sku_identity(rec2, index) == "reranker_miss"


def test_taxonomy_covers_required_categories(index):
    assert set(ERROR_TAXONOMY) == {
        "true_kb_missing", "alias_mapping_missing",
        "package_version_mismatch", "retrieval_miss", "reranker_miss",
        "registry_escape", "unknown/new_packaging"}
    recs = [
        _rec(gt="1250ml茉莉乌龙（无糖）", decision="accepted",
             pred="茉莉乌龙无糖PET1250ML"),
        _rec(gt="果粒橙1.8L"),
        _rec(gt="500ml橘皮乌龙（无糖）"),
    ]
    report = evaluate_records_v2(recs, identity_index=index)
    taxo = report["error_taxonomy"]
    for cat in ERROR_TAXONOMY:
        assert cat in taxo
    assert sum(taxo[c] for c in ERROR_TAXONOMY) + taxo[IDENTITY_MATCH] == 3


def test_canonical_report_keeps_legacy_fields(index):
    recs = [
        _rec(gt="1250ml茉莉乌龙（无糖）", decision="accepted",
             pred="茉莉乌龙无糖PET1250ML", gt_in_registry=False,
             retrieval_ranking=["茉莉乌龙无糖PET1250ML"]),
        _rec(gt="果粒橙1.8L", gt_in_registry=False),
    ]
    report = evaluate_records_v2(recs, identity_index=index)
    for key in ("total", "coverage" if False else "auto_coverage",
                "accepted_precision", "candidate_recall_at_1",
                "registry_escape", "kb_coverage_of_sample",
                "schema_compliance", "candidate_escape", "gate_pass"):
        assert key in report
    # canonical 修正：GT 实际可解析进 KB，kb 覆盖不再被展示名差异抹零
    assert report["kb_coverage_of_sample"] == 0.5
    assert report["candidate_recall_at_1"] == 1.0
    assert report["accepted_precision"] == 1.0
    # 旧字段保持存在（报告结构兼容）
    assert report["evaluation_version"]


def test_legacy_mode_without_index_unchanged():
    # 不提供 identity_index 时保持旧口径（兼容性）
    recs = [_rec(gt="sku_0", decision="accepted", pred="sku_0",
                 gt_in_registry=True,
                 retrieval_ranking=["sku_0"])]
    report = evaluate_records_v2(recs)
    assert report["accepted_precision"] == 1.0
    assert report["candidate_recall_at_1"] == 1.0


# ---------- 历史 report 只读重放（存在时生效） ----------

def _hist_run_dir():
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[2]
    return root / ".eval" / "qwen3vl_zero_shot_v2" / "20260807_172812"


@pytest.mark.skipif(not _hist_run_dir().joinpath("records.jsonl").exists(),
                    reason="历史 zero-shot V2 记录不存在")
def test_replay_historical_records_readonly():
    import json
    from src.training.vlm.evaluate import build_default_identity_index
    run_dir = _hist_run_dir()
    report_path = run_dir / "report.json"
    before = hashlib.sha256(report_path.read_bytes()).hexdigest()
    records = [json.loads(l) for l in
               run_dir.joinpath("records.jsonl").read_text(
                   "utf-8").splitlines() if l.strip()]
    index = build_default_identity_index(
        run_dir.parents[2], kb_root=run_dir.parents[2] / ".kb")
    report = evaluate_records_v2(records, identity_index=index)
    assert set(ERROR_TAXONOMY) <= set(report["error_taxonomy"])
    # 只读重放：历史 report.json 不得被改动
    after = hashlib.sha256(report_path.read_bytes()).hexdigest()
    assert before == after
