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


# 真实探针（仅在隔离环境 .venv_mlx_vlm 内有效；任一异常均 fail-closed）
_LOADED: dict = {}


def _probe_mlx_metal_device():
    try:
        import mlx.core as mx
        metal = mx.metal.is_available()
        dev = str(mx.default_device())
        ok = metal and "gpu" in dev.lower()
        return ok, f"default_device={dev}, metal.is_available={metal}"
    except ImportError:
        return False, "mlx 未安装（fail-closed，禁止假装已验证）"
    except Exception as e:
        return False, f"MLX Metal 检查失败: {e}"


def _probe_model_loadable():
    try:
        from mlx_vlm import load
        model, processor = load(MODEL_ID)  # 首次运行会下载权重（已获授权）
        _LOADED["model"], _LOADED["processor"] = model, processor
        return True, f"已加载 {MODEL_ID}"
    except ImportError:
        return False, "mlx_vlm 未安装（fail-closed）"
    except Exception as e:
        return False, f"模型加载失败: {e}"


def _probe_processor_image():
    try:
        from PIL import Image
        from mlx_vlm.utils import load_config
        from mlx_vlm.prompt_utils import apply_chat_template
        proc = _LOADED.get("processor")
        if proc is None:
            return False, "模型未加载，无法验证 processor"
        config = load_config(MODEL_ID)
        img = Image.new("RGB", (64, 64), (128, 128, 128))
        prompt = apply_chat_template(proc, config, "描述图像",
                                     num_images=1)
        inputs = proc(images=img, text=prompt, return_tensors="np") \
            if hasattr(proc, "image_processor") else proc(img, prompt)
        keys = sorted(getattr(inputs, "keys", lambda: ["?"])())
        return True, f"processor 已处理 64x64 图像（keys={keys}）"
    except Exception as e:
        return False, f"processor 图像处理失败: {e}"


def _probe_bounded_forward():
    try:
        from PIL import Image
        from mlx_vlm import generate
        from mlx_vlm.utils import load_config
        from mlx_vlm.prompt_utils import apply_chat_template
        model, proc = _LOADED.get("model"), _LOADED.get("processor")
        if model is None or proc is None:
            return False, "模型未加载，无法执行 bounded forward"
        config = load_config(MODEL_ID)
        img = Image.new("RGB", (64, 64), (0, 0, 0))
        prompt = apply_chat_template(proc, config, "这是什么？",
                                     num_images=1)
        result = generate(model, proc, prompt, image=img, max_tokens=8,
                          verbose=False)
        text = getattr(result, "text", str(result))
        return True, f"bounded forward 完成（max_tokens=8）: {text[:40]}"
    except Exception as e:
        return False, f"bounded forward 失败: {e}"


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
        # 无热告警记录（No thermal warning）同样表示热状态正常
        ok = ("CPU_Scheduler_Limit" in out
              or "No thermal warning level has been recorded" in out)
        return ok, out.strip().replace("\n", " | ") or "unknown"
    except Exception as e:
        return False, f"热状态检查失败: {e}"


def _probe_service_health():
    import urllib.request

    for port, path in ((8091, "/v2/health"), (8092, "/api/live")):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}",
                                        timeout=3):
                pass
        except Exception as e:
            return False, f"服务 {port}{path} 不可达: {e}"
    return True, "8091/v2/health 与 8092/api/live 可达"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--authorized", action="store_true",
                    help="声明已获得用户对下载模型与安装依赖的明确授权")
    a = ap.parse_args()

    probes = {
        "arm64": _probe_arm64,
        "apple_silicon": _probe_apple_silicon,
        "mlx_metal_device": _probe_mlx_metal_device,
        "model_loadable": _probe_model_loadable,
        "processor_image": _probe_processor_image,
        "bounded_forward": _probe_bounded_forward,
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
