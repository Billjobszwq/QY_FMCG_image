"""Apple/MLX preflight 真实入口（VLM-009）。

真实执行被门禁阻断：当前训练存在时进程表检查会直接
active_training_conflict；MLX/模型相关探针在未安装、未授权时
fail-closed，不会下载任何权重。证据写入新目录
.eval/vlm_preflight/<run_id>/，不覆盖历史。

用法：
  python3 -m scripts.run_qwen3vl_preflight [--authorized]
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.training.vlm.preflight import REQUIRED_PROBES, run_preflight  # noqa: E402

MODEL_ID = "mlx-community/Qwen3-VL-4B-Instruct-4bit"
SWAP_STOP_MB = 8192  # 当前训练停止线


def _process_list() -> list[str]:
    out = subprocess.run(["ps", "-eo", "command="], capture_output=True,
                         text=True, timeout=30)
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def _probe_arm64():
    machine = platform.machine()
    return (machine == "arm64"), f"platform.machine={machine}"


def _probe_apple_silicon():
    proc = platform.processor()
    ok = "arm" in proc.lower() or platform.machine() == "arm64"
    return ok, f"processor={proc}"


def _probe_not_installed(name: str):
    def probe():
        try:
            import mlx  # noqa: F401
        except ImportError:
            return False, f"mlx 未安装（{name} fail-closed，禁止假装已验证）"
        return False, f"{name} 需要真实授权与隔离环境 .venv_mlx_vlm"
    return probe


def _probe_ac_power():
    try:
        out = subprocess.run(["pmset", "-g", "ps"], capture_output=True,
                             text=True, timeout=10).stdout
        ok = "AC" in out and "Battery" not in out.split("\n")[0]
        return ok, out.strip().splitlines()[0] if out.strip() else "unknown"
    except Exception as e:
        return False, f"电源检查失败: {e}"


def _probe_disk():
    usage = shutil.disk_usage(ROOT)
    free_gb = usage.free / (1 << 30)
    return free_gb >= 30, f"剩余 {free_gb:.1f} GB"


def _probe_memory():
    try:
        out = subprocess.run(["sysctl", "-n", "hw.memsize"],
                             capture_output=True, text=True, timeout=10).stdout
        gb = int(out.strip()) / (1 << 30)
        return gb >= 16, f"物理内存 {gb:.0f} GB"
    except Exception as e:
        return False, f"内存检查失败: {e}"


def _probe_swap():
    try:
        out = subprocess.run(["sysctl", "-n", "vm.swapusage"],
                             capture_output=True, text=True, timeout=10).stdout
        return True, out.strip()  # 具体阈值由训练停止线另行裁决
    except Exception as e:
        return False, f"swap 检查失败: {e}"


def _probe_thermal():
    try:
        out = subprocess.run(["pmset", "-g", "therm"], capture_output=True,
                             text=True, timeout=10).stdout
        ok = "CPU_Scheduler_Limit" in out
        return ok, out.strip().replace("\n", " | ") or "unknown"
    except Exception as e:
        return False, f"热状态检查失败: {e}"


def _probe_service_health():
    import urllib.request

    for port in (8091, 8092):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz",
                                        timeout=3):
                pass
        except Exception as e:
            return False, f"服务 {port} 不可达: {e}"
    return True, "8091/8092 健康"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--authorized", action="store_true",
                    help="声明已获得用户对下载模型与安装依赖的明确授权")
    a = ap.parse_args()

    probes = {
        "arm64": _probe_arm64,
        "apple_silicon": _probe_apple_silicon,
        "mlx_metal_device": _probe_not_installed("mlx_metal_device"),
        "model_loadable": _probe_not_installed("model_loadable"),
        "processor_image": _probe_not_installed("processor_image"),
        "bounded_forward": _probe_not_installed("bounded_forward"),
        "ac_power": _probe_ac_power,
        "disk_space": _probe_disk,
        "memory": _probe_memory,
        "swap": _probe_swap,
        "thermal": _probe_thermal,
        "service_health": _probe_service_health,
    }
    report = run_preflight(
        probes=probes,
        processes=_process_list(),
        active_training_leases=0,
        download_authorized=bool(a.authorized),
    )
    report["run_at"] = datetime.now().isoformat()
    report["model_id"] = MODEL_ID
    report["swap_stop_mb"] = SWAP_STOP_MB
    report["env_note"] = ("真实安装必须使用独立环境 .venv_mlx_vlm"
                          "（mlx-vlm[train]/datasets/Pillow），"
                          "版本以安装当日 pip freeze lock 为准")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    ev_dir = ROOT / ".eval" / "vlm_preflight" / run_id
    ev_dir.mkdir(parents=True)  # 新目录，不覆盖历史
    (ev_dir / "preflight.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "blockers": report["blockers"],
                      "evidence": str(ev_dir / "preflight.json")},
                     ensure_ascii=False, indent=1))
    assert set(REQUIRED_PROBES) <= {c["name"] for c in report["checks"]}
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
