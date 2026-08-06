"""VLM-010：Qwen3-VL 零样本评估契约与 benchmark matrix（确定性测试）。

红线：
- 高 precision 不能掩盖零 coverage（全 abstain 不得通过 gate）；
- candidate escape（accepted 候选外 SKU）必须为 0 才能过 gate；
- benchmark 记录实际 sample/region/token 数，不得用照片数估时；
- 每个 probe 独立 run 目录，已存在即拒绝。
全部为确定性/纯函数测试，不运行真实推理。
"""

from __future__ import annotations

import json

import pytest

from src.training.vlm.benchmark import (
    BenchmarkError,
    benchmark_matrix,
    run_benchmark,
)
from src.training.vlm.evaluate import evaluate_records, record


# ---------- 零 coverage 红线（计划原文测试） ----------

def test_high_precision_cannot_hide_zero_coverage() -> None:
    report = evaluate_records([
        record(gt="SKU-A", decision="needs_review", pred=None),
        record(gt="SKU-B", decision="needs_review", pred=None),
    ])
    assert report["coverage"] == 0.0
    assert report["accepted_precision"] is None
    assert report["gate_pass"] is False


# ---------- accepted precision / coverage ----------

def test_accepted_precision_and_coverage() -> None:
    records = [
        record(gt="SKU-A", decision="accepted", pred="SKU-A"),
        record(gt="SKU-B", decision="accepted", pred="SKU-B"),
        record(gt="SKU-C", decision="accepted", pred="SKU-A"),   # 错
        record(gt="SKU-D", decision="unknown", pred=None),
    ]
    report = evaluate_records(records)
    assert report["coverage"] == 0.75
    assert report["accepted_precision"] == pytest.approx(2 / 3)


def test_top1_top5_accuracy() -> None:
    records = [
        record(gt="A", decision="accepted", pred="A", topk=["A", "B"]),
        record(gt="B", decision="accepted", pred="A", topk=["A", "B"]),
        record(gt="C", decision="accepted", pred="X", topk=["X", "Y"]),
        record(gt="D", decision="needs_review", pred=None),
    ]
    report = evaluate_records(records)
    assert report["top1_accuracy"] == pytest.approx(1 / 3)
    assert report["top5_accuracy"] == pytest.approx(2 / 3)


# ---------- unknown / new_package ----------

def test_unknown_precision_recall() -> None:
    records = [
        record(gt=None, target_type="unknown", decision="unknown", pred=None),
        record(gt=None, target_type="unknown", decision="accepted", pred="A"),
        record(gt="A", decision="unknown", pred=None),  # 误报 unknown
    ]
    report = evaluate_records(records)
    assert report["unknown_precision"] == pytest.approx(0.5)
    assert report["unknown_recall"] == pytest.approx(0.5)


def test_new_package_precision_recall() -> None:
    records = [
        record(gt="A", target_type="new_package", decision="new_package",
               pred="A"),
        record(gt="B", target_type="new_package", decision="accepted",
               pred="B"),
    ]
    report = evaluate_records(records)
    assert report["new_package_precision"] == pytest.approx(1.0)
    assert report["new_package_recall"] == pytest.approx(0.5)


def test_zero_denominator_is_none() -> None:
    report = evaluate_records(
        [record(gt="A", decision="accepted", pred="A")])
    assert report["unknown_precision"] is None
    assert report["new_package_recall"] is None


# ---------- schema / candidate escape / gate ----------

def test_candidate_escape_blocks_gate() -> None:
    records = [
        record(gt="A", decision="accepted", pred="A"),
        record(gt="B", decision="accepted", pred="SKU-X",
               candidate_escape=True),
    ]
    report = evaluate_records(records)
    assert report["candidate_escape"] == 1
    assert report["gate_pass"] is False


def test_schema_compliance_recorded() -> None:
    records = [
        record(gt="A", decision="accepted", pred="A"),
        record(gt="B", decision="accepted", pred="B", schema_ok=False),
    ]
    report = evaluate_records(records)
    assert report["schema_compliance"] == pytest.approx(0.5)
    assert report["gate_pass"] is False


def test_clean_report_passes_gate() -> None:
    records = [record(gt="A", decision="accepted", pred="A", latency_ms=10.0)]
    report = evaluate_records(records, min_accepted_precision=0.9)
    assert report["gate_pass"] is True


# ---------- 延迟 / 错误账本 ----------

def test_latency_percentiles_and_tokens() -> None:
    records = [
        record(gt="A", decision="accepted", pred="A", latency_ms=float(i),
               prompt_tokens=100, completion_tokens=20)
        for i in range(1, 101)
    ]
    report = evaluate_records(records, wall_seconds=12.0)
    assert report["p50_latency_ms"] == pytest.approx(50.5)
    assert report["p95_latency_ms"] == pytest.approx(95.05, rel=0.01)
    assert report["tokens_per_second"] == pytest.approx(12000 / 12.0)


def test_error_ledger_keeps_instances() -> None:
    records = [
        record(gt="A", decision="accepted", pred="A"),
        record(gt="B", decision="needs_review", pred=None,
               error="invalid_model_output"),
    ]
    report = evaluate_records(records)
    assert len(report["error_ledger"]) == 1
    assert report["error_ledger"][0]["error"] == "invalid_model_output"


def test_attribute_accuracy_optional() -> None:
    records = [
        record(gt="A", decision="accepted", pred="A", attribute_correct=True),
        record(gt="B", decision="accepted", pred="B", attribute_correct=False),
    ]
    report = evaluate_records(records)
    assert report["attribute_accuracy"] == pytest.approx(0.5)


# ---------- benchmark matrix ----------

def test_benchmark_matrix_covers_batches_and_tiers() -> None:
    matrix = benchmark_matrix()
    batches = {p["batch_size"] for p in matrix}
    assert batches == {1, 2, 4}
    tiers = {p["vision_tier"] for p in matrix}
    assert len(tiers) == 2
    modes = {p["mode"] for p in matrix}
    assert "qlora" in modes and "bf16" in modes


def _fake_executor(probe, samples):
    return {"sample_count": len(samples), "region_count": len(samples),
            "token_count": 120 * len(samples), "wall_seconds": 1.0,
            "latency_ms": [10.0] * len(samples)}


def test_run_benchmark_records_measured_numbers(tmp_path) -> None:
    samples = [{"sample_id": f"s{i}"} for i in range(4)]
    report = run_benchmark(_fake_executor, output_root=tmp_path,
                           samples=samples)
    for probe in report["probes"]:
        assert probe["measured"]["sample_count"] == 4
        assert probe["measured"]["token_count"] == 480
        assert (tmp_path / probe["run_dir"]).is_dir()
    # 估时必须基于实测，不允许用照片数外推
    assert report["estimation_basis"] == "measured"


def test_probe_run_dir_reuse_rejected(tmp_path) -> None:
    samples = [{"sample_id": "s1"}]
    run_benchmark(_fake_executor, output_root=tmp_path, samples=samples)
    with pytest.raises(BenchmarkError):
        run_benchmark(_fake_executor, output_root=tmp_path, samples=samples)


def test_executor_missing_measurements_fail_closed(tmp_path) -> None:
    def bad_executor(probe, samples):
        return {"sample_count": len(samples)}  # 缺 token_count/wall_seconds
    with pytest.raises(BenchmarkError):
        run_benchmark(bad_executor, output_root=tmp_path,
                      samples=[{"sample_id": "s1"}])


def test_probe_result_written_as_json(tmp_path) -> None:
    run_benchmark(_fake_executor, output_root=tmp_path,
                  samples=[{"sample_id": "s1"}])
    files = list(tmp_path.glob("probe-*/result.json"))
    assert files
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["measured"]["sample_count"] == 1
