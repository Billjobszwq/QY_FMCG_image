"""Task 12（G9）测试：固定评测可复现性 + 安全负例。

要求（05 计划 Task 12）：
- 评测可复现：相同语料 + 金标准 → 相同检索指标与报告哈希；
- 安全负例：ACL 泄漏=0、注入命中=0；
- 分层指标（retrieval/citation/safety），无单一总分。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.platform.cognition.composition import build_cognition_services
from src.platform.cognition.evaluation.dataset import load_gold
from src.platform.cognition.evaluation.harness import (
    build_corpus, run_gold_evaluation)
from src.platform.data.store import PlatformStore

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLD = REPO_ROOT / "tests" / "fixtures" / "cognition" / "gold_queries.jsonl"


@pytest.fixture()
def stack_and_snapshot():
    tmp = Path(tempfile.mkdtemp(prefix="cognition-eval-"))
    store = PlatformStore(tmp / "eval.sqlite")
    stack = build_cognition_services(store, cas_root=tmp / "cas",
                                    index_root=tmp / "index")
    snapshot = build_corpus(stack, store)
    yield stack, store, snapshot
    store.close()


class TestEvalReproducibility:
    def test_gold_loads_expected_classes(self):
        gold = load_gold(GOLD)
        classes = {g.cls for g in gold}
        assert "exact_rule" in classes
        assert "paraphrase" in classes
        assert "insufficient" in classes
        assert "acl" in classes

    def test_retrieval_metrics_reproducible(self, stack_and_snapshot):
        stack, store, snapshot = stack_and_snapshot
        gold = load_gold(GOLD)
        r1 = run_gold_evaluation(stack, store, gold, snapshot)
        r2 = run_gold_evaluation(stack, store, gold, snapshot)
        assert r1["retrieval"] == r2["retrieval"]
        assert r1["report_hash"] == r2["report_hash"]

    def test_exact_rule_hits_right_doc(self, stack_and_snapshot):
        stack, store, snapshot = stack_and_snapshot
        gold = [g for g in load_gold(GOLD) if g.id == "g-exact-rule"]
        r = run_gold_evaluation(stack, store, gold, snapshot)
        sample = r["samples"][0]
        assert sample["recall_at_5"] == 1.0
        assert sample["mrr"] == 1.0

    def test_safety_negatives_zero(self, stack_and_snapshot):
        stack, store, snapshot = stack_and_snapshot
        gold = load_gold(GOLD)
        r = run_gold_evaluation(stack, store, gold, snapshot)
        assert r["safety"]["acl_leakage"] == 0
        assert r["safety"]["injection_success"] == 0

    def test_insufficient_abstains(self, stack_and_snapshot):
        stack, store, snapshot = stack_and_snapshot
        gold = [g for g in load_gold(GOLD) if g.id == "g-insufficient"]
        r = run_gold_evaluation(stack, store, gold, snapshot)
        assert r["samples"][0]["abstained"] is True
        assert r["generation"]["abstention_accuracy"] == 1.0

    def test_layered_metrics_present(self, stack_and_snapshot):
        stack, store, snapshot = stack_and_snapshot
        gold = load_gold(GOLD)
        r = run_gold_evaluation(stack, store, gold, snapshot)
        # 分层指标（禁止单一总分）
        for layer in ("retrieval", "citation", "generation", "safety"):
            assert layer in r
        assert "report_hash" in r
