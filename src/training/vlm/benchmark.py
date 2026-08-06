"""VLM-010：200–500 step 吞吐探针 benchmark matrix。

红线：
- 比较 batch 1/2/4、两档视觉 token/分辨率、QLoRA/BF16 可用配置；
- 每个 probe 使用独立 run 目录，已存在即拒绝（防覆盖证据）；
- 记录实际 sample/region/token 数与实测耗时；
- 不得用照片数代替训练实例数估时（estimation_basis="measured"）。
真实执行被门禁阻断：executor 由调用方注入（测试用 fake）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

BENCHMARK_VERSION = "vlm-benchmark.v1"
BATCH_SIZES: tuple[int, ...] = (1, 2, 4)
VISION_TIERS: tuple[str, ...] = ("low_tokens", "high_tokens")
MODES: tuple[str, ...] = ("qlora", "bf16")
_REQUIRED_MEASUREMENTS = ("sample_count", "region_count", "token_count",
                          "wall_seconds")


class BenchmarkError(Exception):
    """benchmark 状态/测量错误（fail-closed）。"""


def benchmark_matrix(
    *,
    batch_sizes: Sequence[int] = BATCH_SIZES,
    vision_tiers: Sequence[str] = VISION_TIERS,
    modes: Sequence[str] = MODES,
) -> list[dict[str, Any]]:
    """冻结的探针矩阵：batch × 视觉 token 档位 × QLoRA/BF16。"""
    matrix = []
    for batch in batch_sizes:
        for tier in vision_tiers:
            for mode in modes:
                matrix.append({
                    "probe_id": f"b{batch}-{tier}-{mode}",
                    "batch_size": int(batch),
                    "vision_tier": tier,
                    "mode": mode,
                })
    return matrix


def run_benchmark(
    executor: Callable[[Mapping[str, Any], Sequence[Mapping]], dict],
    *,
    output_root: Path | str,
    samples: Iterable[Mapping[str, Any]],
    matrix: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """逐 probe 执行 executor(probe, samples)，每个 probe 独立目录，
    测量字段不完整即 fail-closed。返回报告（estimation_basis=measured）。"""
    output_root = Path(output_root)
    probes = list(matrix or benchmark_matrix())
    samples = list(samples)

    run_dirs: dict[str, Path] = {}
    for probe in probes:
        run_dir = output_root / f"probe-{probe['probe_id']}"
        if run_dir.exists():
            raise BenchmarkError(f"probe run 目录已存在，禁止覆盖: {run_dir}")
        run_dirs[probe["probe_id"]] = run_dir

    results: list[dict[str, Any]] = []
    for probe in probes:
        measured = executor(probe, samples)
        missing = [k for k in _REQUIRED_MEASUREMENTS if k not in measured]
        if missing:
            raise BenchmarkError(
                f"probe {probe['probe_id']} 缺少实测字段: {missing}"
                "（不得用照片数外推）")
        run_dir = run_dirs[probe["probe_id"]]
        run_dir.mkdir(parents=True)
        entry = {"probe": dict(probe), "run_dir": run_dir.name,
                 "measured": dict(measured)}
        (run_dir / "result.json").write_text(
            json.dumps(entry, ensure_ascii=False, indent=1, default=str),
            encoding="utf-8")
        results.append(entry)

    return {
        "benchmark_version": BENCHMARK_VERSION,
        "estimation_basis": "measured",  # 禁止用照片数估时
        "sample_total": len(samples),
        "probes": results,
    }
