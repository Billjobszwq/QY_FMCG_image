"""UMT-005：MPS G0 真实门禁（禁止 `sys.platform == "darwin"` 假判）。

实测项（任一失败 → ok=False，训练按钮保持禁用，输出具体失败项）：
- arm64 架构；torch MPS built / available；
- 1024² 矩阵运算（mps 设备，结果有限）；
- 模型一轮前向（Conv2d，mps 设备）；
- 无 CPU fallback（禁止 PYTORCH_ENABLE_MPS_FALLBACK=1）；
- AC 电源；内存容量；磁盘剩余；swap 用量（报告，不阻断）。
证据（checks+evidence）写入 run 的 plan_json（由 service.dry_run 注入）。
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

GATE_VERSION = "mps_g0_v1"


def power_source() -> str:
    """返回 'AC Power' / 'Battery Power' / 'unknown'（macOS pmset）。"""
    try:
        out = subprocess.run(
            ["pmset", "-g", "ps"], capture_output=True, text=True, timeout=5)
        head = (out.stdout or "").splitlines()[0]
        if "AC Power" in head:
            return "AC Power"
        if "Battery Power" in head:
            return "Battery Power"
        return "unknown"
    except Exception:
        return "unknown"


def parse_swap_usage(text: str) -> dict[str, float | None]:
    """解析 vm.swapusage 输出（兼容 `total = 1.00M`/`total=1.00M` 与 M/G 单位）。

    真实 macOS 15 格式：
    "total = 12288.00M  used = 10867.44M  free = 1420.56M  (encrypted)"
    不可解析时返回全 None（fail-closed，不得伪造 0）。
    """
    import re
    out: dict[str, float | None] = {"total_mb": None, "used_mb": None,
                                    "free_mb": None}
    for key in ("total", "used", "free"):
        m = re.search(rf"{key}\s*=\s*([\d.]+)\s*([MmGg])", text or "")
        if m:
            val = float(m.group(1))
            if m.group(2).upper() == "G":
                val *= 1024.0
            out[f"{key}_mb"] = round(val, 2)
    return out


def memory_info() -> dict[str, Any]:
    """hw.memsize 与 vm.swapusage（macOS sysctl，绝对路径防 PATH 缺失）。"""
    mem_gb: float | None = None
    swap: dict[str, Any] | None = None
    try:
        out = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.memsize"],
                             capture_output=True, text=True, timeout=5)
        mem_gb = int(out.stdout.strip()) / 1e9
    except Exception:
        pass
    try:
        out = subprocess.run(["/usr/sbin/sysctl", "-n", "vm.swapusage"],
                             capture_output=True, text=True, timeout=5)
        swap = parse_swap_usage(out.stdout)
    except Exception:
        pass
    return {"mem_gb": mem_gb, "swap": swap}


def _check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}


def run_mps_g0(
    *,
    disk_root: str | Path = ".",
    min_disk_free_gb: float = 20.0,
    min_mem_gb: float = 16.0,
) -> dict[str, Any]:
    """执行全部实测并返回 {gate_version, ok, checks, evidence}。"""
    checks: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {}

    arm64 = platform.machine() == "arm64"
    checks.append(_check(
        "arch_arm64", arm64,
        f"platform.machine()={platform.machine()}"))

    built = available = False
    torch_err = ""
    try:
        import torch
        built = bool(torch.backends.mps.is_built())
        available = bool(torch.backends.mps.is_available())
    except Exception as e:  # torch 缺失同样 fail-closed
        torch_err = repr(e)
    checks.append(_check("torch_mps_built", built, torch_err or "ok"))
    checks.append(_check(
        "torch_mps_available", available, torch_err or "ok"))

    fb = os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK")
    checks.append(_check(
        "no_cpu_fallback", fb != "1",
        f"PYTORCH_ENABLE_MPS_FALLBACK={fb!r}（不得为 '1'）"))

    def _device_checks() -> None:
        import torch
        dev = torch.device("mps")
        a = torch.randn(1024, 1024, device=dev)
        b = torch.randn(1024, 1024, device=dev)
        c = a @ b
        torch.mps.synchronize()
        finite = torch.isfinite(c).all().item()
        checks.append(_check(
            "matrix_1024x1024", finite,
            f"mps matmul 1024x1024 finite={finite}"))
        conv = torch.nn.Conv2d(3, 8, 3, padding=1).to(dev)
        x = torch.randn(1, 3, 64, 64, device=dev)
        y = conv(x)
        torch.mps.synchronize()
        fwd = torch.isfinite(y).all().item()
        checks.append(_check(
            "model_forward", fwd,
            f"Conv2d 前向 finite={fwd}，device={y.device}"))

    if built and available and sys.platform == "darwin":
        try:
            _device_checks()
        except Exception as e:
            checks.append(_check("matrix_1024x1024", False, repr(e)))
            checks.append(_check("model_forward", False, "前置失败"))
    else:
        checks.append(_check(
            "matrix_1024x1024", False, "MPS 不可用或非 darwin，未实测"))
        checks.append(_check(
            "model_forward", False, "MPS 不可用或非 darwin，未实测"))

    ps = power_source() if sys.platform == "darwin" else "unknown"
    evidence["power_source"] = ps
    checks.append(_check(
        "power_ac", ps == "AC Power",
        "训练要求 AC 电源（caffeinate 由执行命令负责）"))

    mem = memory_info()
    evidence["memory"] = mem
    mem_gb = mem.get("mem_gb")
    checks.append(_check(
        "memory", mem_gb is not None and mem_gb >= min_mem_gb,
        f"hw.memsize={mem_gb} GB，要求≥{min_mem_gb}"))

    du = shutil.disk_usage(str(disk_root))
    free_gb = du.free / 1e9
    evidence["disk"] = {"root": str(disk_root), "free_gb": round(free_gb, 1),
                        "total_gb": round(du.total / 1e9, 1)}
    checks.append(_check(
        "disk_free", free_gb >= min_disk_free_gb,
        f"free={free_gb:.1f} GB，要求≥{min_disk_free_gb}"))

    sw = (mem.get("swap") or {}).get("used_mb")
    checks.append(_check(
        "swap_report", True,
        f"swap used={sw} MB（报告项，不阻断）"))

    return {
        "gate_version": GATE_VERSION,
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
        "evidence": evidence,
    }
