"""T0 MPS 预检纯函数（红测试先行，无需 MPS 硬件）。

口径（手册 §T0）：
- 只允许 768/960/1024 三档 benchmark，禁止默认 1280；
- pick_resolution 按 images/s 选优，平局比峰值内存（低者胜）；
- budget_estimate 给出预计耗时与停止线（超时/swap/热状态）；
- parse_thermal 解析 `pmset -g therm` 输出。
"""
from __future__ import annotations

import pytest

from src.training.t0_preflight import (ALLOWED_RESOLUTIONS, budget_estimate,
                                       parse_thermal, pick_resolution)


class TestPickResolution:
    def test_picks_highest_throughput(self):
        rows = [
            {"resolution": 768, "images_per_s": 30.0, "peak_mem_gb": 6.0},
            {"resolution": 960, "images_per_s": 40.0, "peak_mem_gb": 8.0},
            {"resolution": 1024, "images_per_s": 35.0, "peak_mem_gb": 9.0},
        ]
        assert pick_resolution(rows) == 960

    def test_tie_prefers_lower_peak_memory(self):
        rows = [
            {"resolution": 768, "images_per_s": 40.0, "peak_mem_gb": 6.0},
            {"resolution": 1024, "images_per_s": 40.0, "peak_mem_gb": 9.0},
        ]
        assert pick_resolution(rows) == 768

    def test_rejects_non_allowed_resolution(self):
        rows = [{"resolution": 1280, "images_per_s": 10.0,
                 "peak_mem_gb": 12.0}]
        with pytest.raises(ValueError):
            pick_resolution(rows)

    def test_empty_rows_rejected(self):
        with pytest.raises(ValueError):
            pick_resolution([])

    def test_allowed_resolutions_exact(self):
        assert ALLOWED_RESOLUTIONS == (768, 960, 1024)


class TestBudgetEstimate:
    def test_estimates_wall_clock(self):
        est = budget_estimate(n_images=1000, epochs=1, images_per_s=25.0)
        # 1000 / 25 = 40 s/epoch
        assert est["seconds_per_epoch"] == pytest.approx(40.0)
        assert est["total_seconds"] == pytest.approx(40.0)
        assert est["n_epochs"] == 1

    def test_stop_lines_present(self):
        est = budget_estimate(n_images=2000, epochs=3, images_per_s=20.0)
        sl = est["stop_lines"]
        assert sl["max_wall_hours"] > 0
        assert sl["max_swap_used_mb"] > 0
        assert sl["thermal_event"] == "stop"
        # 预算超限判定：300 s 超过停止线则为 budget_exceeded
        assert est["total_seconds"] == pytest.approx(300.0)
        assert est["exceeds_budget"] is False

    def test_exceeds_budget_when_over_stop_line(self):
        est = budget_estimate(n_images=10_000_000, epochs=3,
                              images_per_s=1.0)
        assert est["exceeds_budget"] is True

    def test_zero_throughput_rejected(self):
        with pytest.raises(ValueError):
            budget_estimate(n_images=100, epochs=1, images_per_s=0.0)


class TestParseThermal:
    def test_parses_no_pressure(self):
        txt = ("CPU_Scheduler_Limit = 100\n"
               "CPU_Scheduler_Avail = 100\n"
               "CPU_Interrupt_Level_Limit = 30\n"
               "CPU_Interrupt_Level_Avail = 30\n"
               "CPU_Halting_Limit = 0\n"
               "CPU_Halting_Avail = 0\n")
        info = parse_thermal(txt)
        assert info["cpu_limit"] == 100
        assert info["cpu_avail"] == 100
        assert info["throttled"] is False

    def test_parses_throttled(self):
        txt = ("CPU_Scheduler_Limit = 60\n"
               "CPU_Scheduler_Avail = 40\n"
               "CPU_Interrupt_Level_Limit = 30\n"
               "CPU_Interrupt_Level_Avail = 30\n"
               "CPU_Halting_Limit = 50\n"
               "CPU_Halting_Avail = 50\n")
        info = parse_thermal(txt)
        assert info["throttled"] is True
        assert info["cpu_limit"] == 60

    def test_real_no_warning_format(self):
        # 真实机器无 throttling 时 pmset -g therm 只输出 Note 行（无 key=value）
        txt = ("Note: No thermal warning level has been recorded\n"
               "Note: No performance warning level has been recorded\n"
               "Note: No CPU power status has been recorded\n")
        info = parse_thermal(txt)
        assert info["throttled"] is False

    def test_empty_or_garbage_fails_closed(self):
        info = parse_thermal("")
        assert info["throttled"] is True  # fail-closed：无法解析即视为受限
        info2 = parse_thermal("garbage")
        assert info2["throttled"] is True
