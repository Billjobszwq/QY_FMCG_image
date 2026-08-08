"""SLTF P0-5：统一 ResourceLease 管理（持久化，append-only 释放）。

四类租约：
- apple_mps_heavy：MPS 重训练，默认并发 1（benchmark 合格才 2）；
- apple_mlx_exclusive：Qwen/MLX 永远独占，与任何 heavy 互斥；
- cpu_io：CPU/IO 轻任务，可并行；
- service_reserved_memory：在线服务保留内存，训练不可占用。

benchmark 记录：throughput_gain ≥0.25 且 stop_lines_passed 才允许并发 2。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

HEAVY_TYPES = ("apple_mps_heavy", "apple_mlx_exclusive")
LEASE_TYPES = HEAVY_TYPES + ("cpu_io", "service_reserved_memory")
MIN_GAIN_FOR_TWO = 0.25


class LeaseConflict(RuntimeError):
    """租约冲突（fail-closed）。"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class LeaseManager:
    def __init__(self, store: Any) -> None:
        self.store = store

    # ---- 查询 ----

    def _active(self) -> list[dict[str, Any]]:
        rows = self.store._conn.execute(
            "SELECT * FROM resource_lease_v1 WHERE released_at IS NULL"
        ).fetchall()
        return [dict(r) for r in rows]

    def max_mps_concurrency(self) -> int:
        rows = self.store._conn.execute(
            "SELECT metrics_json FROM resource_benchmark_v1"
        ).fetchall()
        for r in rows:
            m = json.loads(r["metrics_json"])
            if m.get("throughput_gain", 0) >= MIN_GAIN_FOR_TWO and \
                    m.get("stop_lines_passed"):
                return 2
        return 1

    # ---- 获取/释放 ----

    def acquire(self, run_id: str, lease_type: str) -> None:
        if lease_type not in LEASE_TYPES:
            raise LeaseConflict(f"未知租约类型: {lease_type}")
        if lease_type == "service_reserved_memory":
            raise LeaseConflict(
                "service_reserved_memory 为在线服务保留，训练不可占用")
        active = self._active()
        active_heavy = [a for a in active if a["resource"] in HEAVY_TYPES]
        if lease_type in HEAVY_TYPES:
            if lease_type == "apple_mlx_exclusive" and active_heavy:
                raise LeaseConflict(
                    f"MLX 独占：已有 heavy 租约 "
                    f"{[a['run_id'] for a in active_heavy]}")
            if lease_type == "apple_mps_heavy":
                mps = [a for a in active_heavy
                       if a["resource"] == "apple_mps_heavy"]
                if len(mps) >= self.max_mps_concurrency():
                    raise LeaseConflict(
                        f"MPS heavy 并发上限 {self.max_mps_concurrency()}")
                if any(a["resource"] == "apple_mlx_exclusive"
                       for a in active_heavy):
                    raise LeaseConflict("MLX 独占期间禁止 MPS heavy")
        self.store._conn.execute(
            "INSERT INTO resource_lease_v1 (run_id, resource, mode,"
            " acquired_at) VALUES (?,?,?,?)",
            (run_id, lease_type,
             "exclusive" if lease_type in HEAVY_TYPES else "shared",
             _utcnow()))
        self.store._conn.commit()

    def release(self, run_id: str, lease_type: str) -> None:
        self.store._conn.execute(
            "UPDATE resource_lease_v1 SET released_at=?"
            " WHERE run_id=? AND resource=? AND released_at IS NULL",
            (_utcnow(), run_id, lease_type))
        self.store._conn.commit()

    def record_benchmark(self, metrics: dict[str, Any]) -> None:
        self.store._conn.execute(
            "INSERT INTO resource_benchmark_v1 (scenario, lane_combo,"
            " metrics_json, verdict, created_at) VALUES (?,?,?,?,?)",
            (metrics.get("combo", ""), metrics.get("combo", ""),
             json.dumps(metrics, ensure_ascii=False),
             "qualified_for_2" if (
                 metrics.get("throughput_gain", 0) >= MIN_GAIN_FOR_TWO
                 and metrics.get("stop_lines_passed")) else "not_qualified",
             _utcnow()))
        self.store._conn.commit()
