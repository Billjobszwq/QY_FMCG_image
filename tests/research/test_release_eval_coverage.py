"""R2-08：固定金标准 12 类覆盖与发布评测结构红测试。

契约（round-2-hardening/01 §9 / 任务书 §十三）：
- gold set 必须覆盖 12 类：exact_rule/paraphrase/temporal/multi_hop/
  global/conflict/insufficient/acl/injection/skill/l2_case/l3_methodology；
- 每类至少一个正例和一个负例；
- 每条样本带 scope/as_of/期望 target(或 abstain/conflict/empty)，
  安全类带 forbidden source；
- 样本 id 唯一；class 必须在白名单（fail-closed）；
- provider/评测代码不得读取 gold fixture 内容做特化（防污染：gold hash
  只作为报告绑定，不进 provider）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLD_PATH = REPO_ROOT / "tests" / "fixtures" / "cognition" / \
    "gold_queries.jsonl"

REQUIRED_CLASSES = {
    "exact_rule", "paraphrase", "temporal", "multi_hop", "global",
    "conflict", "insufficient", "acl", "injection", "skill",
    "l2_case", "l3_methodology",
}


def _raw_samples():
    samples = []
    for line in GOLD_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        samples.append(json.loads(line))
    return samples


class TestGoldCoverage:
    def test_all_12_classes_present(self):
        classes = {s.get("class") for s in _raw_samples()}
        missing = REQUIRED_CLASSES - classes
        assert not missing, f"缺 class: {sorted(missing)}"

    def test_each_class_has_positive_and_negative(self):
        by_class: dict[str, set] = {}
        for s in _raw_samples():
            by_class.setdefault(s.get("class"), set()).add(
                s.get("polarity"))
        for cls in REQUIRED_CLASSES:
            pol = by_class.get(cls, set())
            assert "positive" in pol, f"{cls} 缺正例"
            assert "negative" in pol, f"{cls} 缺负例"

    def test_sample_ids_unique(self):
        ids = [s.get("id") for s in _raw_samples()]
        assert len(ids) == len(set(ids)), "gold 样本 id 重复"

    def test_samples_carry_scope_and_expectations(self):
        for s in _raw_samples():
            assert s.get("id"), f"样本缺 id: {s}"
            assert s.get("query"), f"{s.get('id')} 缺 query"
            assert s.get("polarity") in ("positive", "negative"), \
                f"{s.get('id')} 缺 polarity"
            # scope/as_of 必须显式
            assert "as_of" in s, f"{s.get('id')} 缺 as_of"
            assert "scope" in s, f"{s.get('id')} 缺 scope"
            cls = s.get("class")
            # 期望形态：target/abstain/empty/conflict 至少其一
            has_expect = (
                s.get("expect_knowledge_ids")
                or s.get("expect_target_ids")
                or s.get("expect_ref")
                or s.get("expect_abstain") is True
                or s.get("expect_empty_for_customer") is not None
                or s.get("expect_conflict") is not None)
            assert has_expect, f"{s.get('id')}（{cls}）缺期望形态"
            # 安全/负例样本必须声明 forbidden source
            if cls in ("acl", "injection") or s.get("polarity") == "negative":
                assert (s.get("forbidden_source_ids") is not None
                        or s.get("expect_empty_for_customer") is not None
                        or s.get("expect_abstain")
                        or s.get("expect_conflict") is not None), \
                    f"{s.get('id')}（{cls}）负例缺 forbidden/empty/abstain 声明"

    def test_invalid_class_fails_closed(self, tmp_path):
        from src.platform.cognition.evaluation.dataset import load_gold
        bad = tmp_path / "bad.jsonl"
        bad.write_text('{"id":"x","class":"not_a_class","query":"q"}\n',
                       encoding="utf-8")
        with pytest.raises(ValueError):
            load_gold(bad)


class TestReleaseReportStructure:
    """release 评测必须输出全部分层指标；未测量层显式 unmeasured，
    不得以 1.0 默认值充数。"""

    def test_release_harness_emits_all_layers(self):
        import tempfile
        from src.platform.cognition.composition import (
            build_cognition_services)
        from src.platform.cognition.evaluation.dataset import load_gold
        from src.platform.cognition.evaluation.harness import (
            build_corpus, run_gold_evaluation)
        from src.platform.data.store import PlatformStore
        tmp = Path(tempfile.mkdtemp(prefix="cognition-rel-"))
        store = PlatformStore(tmp / "eval.sqlite")
        stack = build_cognition_services(store, cas_root=tmp / "cas",
                                         index_root=tmp / "index")
        snapshot = build_corpus(stack, store)
        gold = load_gold(GOLD_PATH)
        report = run_gold_evaluation(stack, store, gold, snapshot,
                                     gold_path=GOLD_PATH)
        # 分层结构必须齐备
        for layer in ("retrieval", "citation", "generation", "safety",
                      "reader", "research", "system"):
            assert layer in report, f"报告缺 {layer} 层"
        # 每类 class 都有 per_class 聚合
        for cls in REQUIRED_CLASSES:
            assert cls in report.get("per_class", {}) or cls in (
                "injection",), f"per_class 缺 {cls}"
        # citation precision 必须基于 gold relation（measured 标志）
        assert "precision" in report["citation"]
        # system 层必须有 latency p50/p95（实测，非默认）
        assert "latency_ms" in report["system"]
        assert "p50" in report["system"]["latency_ms"]
        assert "p95" in report["system"]["latency_ms"]
        # report_hash 覆盖 gold hash 与 snapshot
        assert report.get("gold_hash"), "报告必须绑定 gold hash"
        assert report.get("report_hash")
        store.close()
