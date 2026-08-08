"""SLTF P0-5：统一 ResourceLease 契约。

四类：apple_mps_heavy / apple_mlx_exclusive / cpu_io / service_reserved_memory。
规则：MPS heavy 并发 1；MLX 永远独占（与任何 heavy 互斥）；cpu_io 可并行；
service_reserved 不可被训练占用。并发 2 需 benchmark 证明 ≥25% 且停止线全过。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.modules.training_control.leases import (
    LeaseConflict,
    LeaseManager,
)
from src.platform.data.store import PlatformStore


@pytest.fixture()
def mgr(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield LeaseManager(s)
    s.close()


def test_mps_heavy_concurrency_one(mgr):
    mgr.acquire("runA", "apple_mps_heavy")
    with pytest.raises(LeaseConflict):
        mgr.acquire("runB", "apple_mps_heavy")
    mgr.release("runA", "apple_mps_heavy")
    mgr.acquire("runB", "apple_mps_heavy")  # 释放后可再获取


def test_mlx_exclusive_blocks_and_is_blocked(mgr):
    mgr.acquire("runA", "apple_mps_heavy")
    with pytest.raises(LeaseConflict):
        mgr.acquire("runQ", "apple_mlx_exclusive")
    mgr.release("runA", "apple_mps_heavy")
    mgr.acquire("runQ", "apple_mlx_exclusive")
    with pytest.raises(LeaseConflict):
        mgr.acquire("runB", "apple_mps_heavy")


def test_cpu_io_parallel_with_heavy(mgr):
    mgr.acquire("runA", "apple_mps_heavy")
    mgr.acquire("runC", "cpu_io")
    mgr.acquire("runD", "cpu_io")  # cpu_io 可并行


def test_service_reserved_not_acquirable_by_training(mgr):
    with pytest.raises(LeaseConflict):
        mgr.acquire("runA", "service_reserved_memory")


def test_benchmark_gate_for_concurrency_two(mgr):
    """并发 2 必须 benchmark 证明 ≥25% 提升且停止线全过。"""
    assert mgr.max_mps_concurrency() == 1
    mgr.record_benchmark({"combo": "detector+classifier",
                          "throughput_gain": 0.31,
                          "stop_lines_passed": True})
    assert mgr.max_mps_concurrency() == 2
    mgr.record_benchmark({"combo": "segmenter+classifier",
                          "throughput_gain": 0.10,
                          "stop_lines_passed": True})
    assert mgr.max_mps_concurrency() == 2  # 已有合格 benchmark
    mgr.record_benchmark({"combo": "x+y", "throughput_gain": 0.31,
                          "stop_lines_passed": False})  # 停止线不过不计数
    assert mgr.max_mps_concurrency() == 2
