"""VLM-009：Apple/MLX 硬预检（G-CURRENT / G-APPLE）。

红线（计划 §Task 9）：
- 进程表存在 src.training.train_v1、mlx_vlm.lora 或存在 active training
  lease → active_training_conflict，ok=false，不得继续（G-CURRENT）；
- 真实权重下载/依赖安装必须获得用户明确授权（G-APPLE），
  未授权 → download_authorization_required；
- 任一必需 probe 缺失/失败/崩溃 → fail-closed；
- 输出目录已存在 → output_dir_exists（防覆盖证据）。

probe 为可注入的 () -> (ok: bool, detail: str)；测试全部使用 fake，
不下载模型、不运行真实前向。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

# 门禁维度冻结（不得删减）
REQUIRED_PROBES: tuple[str, ...] = (
    "arm64",              # 架构
    "apple_silicon",      # Apple Silicon
    "mlx_metal_device",   # MLX Metal device 可用
    "model_loadable",     # 模型可加载
    "processor_image",    # processor 可处理图像
    "bounded_forward",    # 有限前向（小样本）
    "ac_power",           # AC 电源
    "disk_space",         # 磁盘
    "memory",             # 内存
    "swap",               # swap（训练停止线）
    "thermal",            # 热状态
    "service_health",     # 8091/8092 等服务健康
)

_CONFLICT_MARKERS = ("src.training.train_v1", "mlx_vlm.lora")


class PreflightError(Exception):
    """preflight 配置/状态错误（fail-closed，如必需 probe 缺失）。"""


def run_preflight(
    *,
    probes: Mapping[str, Callable[[], tuple[bool, str]]],
    processes: Sequence[str],
    active_training_leases: int,
    download_authorized: bool = False,
    output_dir: Path | str | None = None,
) -> dict[str, Any]:
    """运行全部硬门禁检查，返回报告 {ok, checks, blockers}。

    任何一项失败 → ok=false；调用方在 ok=true 之前不得执行真实
    下载/安装/前向/训练。
    """
    missing = [name for name in REQUIRED_PROBES if name not in probes]
    if missing:
        raise PreflightError(f"缺少必需 probe（fail-closed）: {sorted(missing)}")

    checks: list[dict[str, Any]] = []
    blockers: list[str] = []

    # G-CURRENT：当前训练冲突（进程表 + 租约），最高优先级
    conflicts = [cmd for cmd in processes
                 if any(marker in cmd for marker in _CONFLICT_MARKERS)]
    if conflicts or active_training_leases > 0:
        detail = ("存在活跃训练租约；" if active_training_leases > 0 else "") + (
            "进程表检出训练进程: " + "; ".join(conflicts) if conflicts else "")
        checks.append({"name": "active_training_conflict", "ok": False,
                       "detail": detail or "active training lease/process"})
        blockers.append("active_training_conflict")
    else:
        checks.append({"name": "active_training_conflict", "ok": True,
                       "detail": "无活跃训练进程/租约"})

    # G-APPLE：权重下载/依赖安装授权
    if not download_authorized:
        checks.append({"name": "download_authorization", "ok": False,
                       "detail": "未获得用户对下载模型与安装依赖的明确授权"})
        blockers.append("download_authorization_required")
    else:
        checks.append({"name": "download_authorization", "ok": True,
                       "detail": "已获得明确授权"})

    # 输出目录防覆盖
    if output_dir is not None:
        out = Path(output_dir)
        if out.exists():
            checks.append({"name": "output_dir_guard", "ok": False,
                           "detail": f"输出目录已存在，禁止覆盖: {out}"})
            blockers.append("output_dir_exists")
        else:
            checks.append({"name": "output_dir_guard", "ok": True,
                           "detail": f"输出目录可用: {out}"})

    # 逐项 probe（崩溃也 fail-closed）
    for name in REQUIRED_PROBES:
        try:
            ok, detail = probes[name]()
            ok = bool(ok)
        except Exception as e:
            ok, detail = False, f"probe 异常: {e}"
        checks.append({"name": name, "ok": ok, "detail": str(detail)})
        if not ok:
            blockers.append(name)

    return {"ok": len(blockers) == 0, "checks": checks,
            "blockers": blockers}
