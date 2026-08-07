"""V2 zero-shot 方法修正测试（分层采样 + 真实检索候选 + 真 top-k）。

红线条款（用户指令第十节）：
- 候选禁止注入 GT，必须来自真实检索链路；
- 采样必须按门店/session/照片/SKU 分层，不得只来自少数照片；
- top-k 指标必须基于真实 predicted ranking，候选不足不得伪造；
- 分母为 0 一律 None，不得伪造 1.0。
"""
from __future__ import annotations

import numpy as np
import pytest

from src.eval.zeroshot_v2 import (parse_photo_rows, stratified_sample,
                                  retrieve_candidates)
from src.training.vlm.evaluate import evaluate_records_v2


def _regions():
    """合成区域：3 门店、2 session、9 照片；照片 p1 有 20 个区域（诱使
    '排序取前 N' 采样全部落在 p1），其余照片各 2 区域。"""
    regions = []
    for i in range(20):
        regions.append({"photo_id": "p1", "cls": i % 4,
                        "gt": f"sku_{i % 4}", "box": [0, 0, 10, 10],
                        "region_index": i})
    for pi in range(2, 10):
        store_i = pi % 3
        for j in range(2):
            regions.append({"photo_id": f"p{pi}", "cls": (pi + j) % 4,
                            "gt": f"sku_{(pi + j) % 4}",
                            "box": [0, 0, 10, 10],
                            "region_index": j})
    return regions


def _meta():
    meta = {"p1": {"store": "S1", "session": "2026-04-15",
                   "photo_type": "shelf"}}
    for pi in range(2, 10):
        meta[f"p{pi}"] = {"store": f"S{pi % 3 + 1}",
                          "session": "2026-04-15" if pi < 6 else "2026-05-01",
                          "photo_type": "shelf"}
    return meta


def test_stratified_sample_covers_many_photos_and_stores():
    picked, report = stratified_sample(_regions(), _meta(), limit=24)
    photos = {r["photo_id"] for r in picked}
    # 分层采样不得像旧法一样全部落在 p1
    from_p1 = sum(1 for r in picked if r["photo_id"] == "p1")
    assert len(picked) == 24
    assert len(photos) >= 8, f"照片覆盖不足: {photos}"
    assert from_p1 <= 8, "单照片 cap 失效"
    assert report["n_stores"] >= 3
    assert report["n_sessions"] >= 2
    assert report["n_photos"] == len(photos)
    assert report["n_skus"] >= 4


def test_stratified_sample_deterministic():
    a, _ = stratified_sample(_regions(), _meta(), limit=20)
    b, _ = stratified_sample(_regions(), _meta(), limit=20)
    assert [(r["photo_id"], r["region_index"]) for r in a] == \
           [(r["photo_id"], r["region_index"]) for r in b]


def test_stratified_sample_missing_meta_fails_closed():
    regions = _regions()
    meta = _meta()
    del meta["p1"]
    # 缺元数据的照片不得静默混入未分组桶伪造分层
    picked, report = stratified_sample(regions, meta, limit=24)
    assert all(r["photo_id"] != "p1" for r in picked)
    assert report["photos_without_meta"] >= 1


def test_retrieve_candidates_signature_forbids_gt():
    """结构防线：候选检索函数不得接受任何 GT 参数。"""
    import inspect
    sig = inspect.signature(retrieve_candidates)
    for bad in ("gt", "gt_class", "gt_name", "answer", "label"):
        assert bad not in sig.parameters, f"候选检索不得接受 GT 参数: {bad}"


def test_retrieve_candidates_returns_true_ranking():
    ids = ["A", "B", "C"]
    vec = np.array([[1.0, 0, 0], [0.9, 0.1, 0], [0, 0, 1.0]],
                   dtype="float32")
    embed = lambda texts: [[1.0, 0.0, 0.0]] * len(texts)  # noqa: E731
    cands = retrieve_candidates("乌龙茶 500ml", embed_fn=embed,
                                kb_ids=ids, kb_vectors=vec, topk=3)
    # 真实余弦排序：A > B > C，不得打乱/注入
    assert cands == [("A", pytest.approx(1.0, abs=1e-3)),
                     ("B", pytest.approx(0.994, abs=1e-2)),
                     ("C", pytest.approx(0.0, abs=1e-3))]


def test_recall_at_k_uses_true_ranking_prefix():
    """gt 在完整候选列表中但位于第 6 位：recall@5 必须 miss，
    recall@8 才 hit（旧实现 'gt in topk(全 K 列表)' 会虚高）。"""
    ranking = [f"s{i}" for i in range(8)]
    rec = {"gt": "s5", "decision": "accepted", "pred": "s0",
           "retrieval_ranking": ranking, "n_candidates": 8,
           "gt_in_registry": True, "target_type": "closed_set",
           "schema_ok": True, "candidate_escape": False,
           "latency_ms": 100.0, "prompt_tokens": 1, "completion_tokens": 1,
           "error": None, "source": "x", "photo_id": "p",
           "store": "S", "session": "D"}
    rep = evaluate_records_v2([rec])
    assert rep["candidate_recall_at_1"] == 0.0
    assert rep["candidate_recall_at_5"] == 0.0
    assert rep["candidate_recall_at_8"] == 1.0


def test_recall_not_fabricated_when_candidates_short():
    """检索只返回 2 个候选、gt 不在其中：recall@5 不得伪造为命中。"""
    rec = {"gt": "missing_sku", "decision": "abstain", "pred": None,
           "retrieval_ranking": ["a", "b"], "n_candidates": 2,
           "gt_in_registry": True, "target_type": "closed_set",
           "schema_ok": True, "candidate_escape": False,
           "latency_ms": 50.0, "prompt_tokens": 0, "completion_tokens": 0,
           "error": None, "source": "x", "photo_id": "p",
           "store": "S", "session": "D"}
    rep = evaluate_records_v2([rec])
    assert rep["candidate_recall_at_5"] == 0.0
    assert rep["abstain_rate"] == 1.0


def test_evaluate_v2_registry_escape_and_coverage():
    def mk(gt, decision, pred, in_reg):
        return {"gt": gt, "decision": decision, "pred": pred,
                "retrieval_ranking": [gt] if in_reg else [],
                "n_candidates": 1 if in_reg else 0,
                "gt_in_registry": in_reg, "target_type": "closed_set",
                "schema_ok": True, "candidate_escape": False,
                "latency_ms": 100.0, "prompt_tokens": 2,
                "completion_tokens": 3, "error": None, "source": "x",
                "photo_id": "p", "store": "S", "session": "D"}
    recs = [mk("a", "accepted", "a", True),
            mk("b", "accepted", "wrong", True),
            mk("new_sku", "abstain", None, False),
            mk("c", "unknown", None, True)]
    rep = evaluate_records_v2(recs)
    assert rep["registry_escape"] == 1
    assert rep["kb_coverage_of_sample"] == pytest.approx(0.75)
    assert rep["accepted_precision"] == pytest.approx(0.5)
    assert rep["auto_coverage"] == pytest.approx(0.5)
    assert rep["abstain_rate"] == pytest.approx(0.25)
    assert rep["unknown_or_new_packaging_count"] >= 1
    assert rep["p50_latency_ms"] == pytest.approx(100.0)
    assert rep["cost_per_region"]["avg_tokens"] == pytest.approx(5.0)


def test_evaluate_v2_empty_denominators_are_none():
    rec = {"gt": "a", "decision": "abstain", "pred": None,
           "retrieval_ranking": [], "n_candidates": 0,
           "gt_in_registry": False, "target_type": "closed_set",
           "schema_ok": True, "candidate_escape": False,
           "latency_ms": 10.0, "prompt_tokens": 0, "completion_tokens": 0,
           "error": None, "source": "x", "photo_id": "p",
           "store": "S", "session": "D"}
    rep = evaluate_records_v2([rec])
    assert rep["accepted_precision"] is None
    assert rep["candidate_recall_at_1"] is None
    assert rep["gate_pass"] is False


def test_parse_photo_rows_builds_store_session():
    import datetime
    rows = [(1, "SDL-1", "润尚", datetime.datetime(2026, 4, 15),
             "三得利", "shelf", "f.jpg", "http://u", 0.03,
             "500ml乌龙茶", 1, 2, 0, 0, 0)]
    meta = parse_photo_rows(rows)
    assert meta["1"]["store"] == "润尚"
    assert meta["1"]["store_code"] == "SDL-1"
    assert meta["1"]["session"] == "2026-04-15"
