"""T0 Apple MPS 预检：分辨率选优、预算估算、热状态解析（纯函数）。

口径（手册 §T0）：
- benchmark 仅允许 768/960/1024 三档，禁止默认 1280；
- pick_resolution：images/s 高者胜，平局峰值内存低者胜；
- budget_estimate：预计耗时 + 停止线（墙钟/swap/热状态），超限 fail-closed；
- parse_thermal：解析 `pmset -g therm`，无法解析视为受限（fail-closed）。
硬件实测（G0、benchmark）由 scripts/run_t0_mps_preflight.py 负责。
"""
from __future__ import annotations

from typing import Any

ALLOWED_RESOLUTIONS: tuple[int, ...] = (768, 960, 1024)

# 停止线（T0 预算口径）：单次预检/benchmark 阶段的上限。
STOP_WALL_HOURS = 6.0        # 墙钟超过即停（pilot 另行授权）
STOP_SWAP_USED_MB = 8192.0   # swap 用量超过即停
STOP_THERMAL = "stop"        # 出现热限流立即停止


def pick_resolution(rows: list[dict[str, Any]]) -> int:
    """从 benchmark 结果中选择训练分辨率。

    rows: [{resolution, images_per_s, peak_mem_gb}, ...]
    规则：images/s 高者胜；平局峰值内存低者胜；仅接受 ALLOWED_RESOLUTIONS。
    """
    if not rows:
        raise ValueError("benchmark 结果为空，无法选择分辨率")
    for r in rows:
        res = r.get("resolution")
        if res not in ALLOWED_RESOLUTIONS:
            raise ValueError(
                f"分辨率 {res} 不在允许集合 {ALLOWED_RESOLUTIONS}"
                f"（禁止默认 1280）")
    best = sorted(rows, key=lambda r: (-float(r["images_per_s"]),
                                       float(r["peak_mem_gb"])))[0]
    return int(best["resolution"])


def budget_estimate(
    *,
    n_images: int,
    epochs: int,
    images_per_s: float,
    max_wall_hours: float = STOP_WALL_HOURS,
) -> dict[str, Any]:
    """估算训练预算：每 epoch 耗时、总耗时、停止线与是否超限。"""
    if images_per_s <= 0:
        raise ValueError("images_per_s 必须为正")
    if n_images <= 0 or epochs <= 0:
        raise ValueError("n_images 与 epochs 必须为正")
    seconds_per_epoch = n_images / images_per_s
    total = seconds_per_epoch * epochs
    stop_lines = {
        "max_wall_hours": max_wall_hours,
        "max_swap_used_mb": STOP_SWAP_USED_MB,
        "thermal_event": STOP_THERMAL,
    }
    return {
        "n_images": n_images,
        "n_epochs": epochs,
        "images_per_s": images_per_s,
        "seconds_per_epoch": seconds_per_epoch,
        "total_seconds": total,
        "stop_lines": stop_lines,
        "exceeds_budget": total > max_wall_hours * 3600,
    }


def parse_thermal(text: str) -> dict[str, Any]:
    """解析 `pmset -g therm` 输出；无法解析或缺字段 → throttled=True。"""
    vals: dict[str, int] = {}
    for line in (text or "").splitlines():
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        try:
            vals[k] = int(v.strip())
        except ValueError:
            continue
    limit = vals.get("CPU_Scheduler_Limit")
    avail = vals.get("CPU_Scheduler_Avail")
    halt_limit = vals.get("CPU_Halting_Limit", 0)
    if limit is None or avail is None:
        # 真实 macOS 无限流时 pmset -g therm 只输出三条 Note（无 key=value）
        txt = text or ""
        if ("No thermal warning level" in txt
                and "No performance warning level" in txt):
            return {"throttled": False, "cpu_limit": None, "cpu_avail": None,
                    "detail": "pmset -g therm 无任何 warning 记录"}
        return {"throttled": True, "cpu_limit": None, "cpu_avail": None,
                "detail": "pmset -g therm 输出不可解析（fail-closed）"}
    throttled = avail < limit or halt_limit > 0
    return {"throttled": throttled, "cpu_limit": limit, "cpu_avail": avail,
            "detail": (f"limit={limit} avail={avail} "
                       f"halting_limit={halt_limit}")}
