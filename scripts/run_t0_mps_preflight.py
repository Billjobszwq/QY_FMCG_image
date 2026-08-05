"""T0 Apple MPS 预检真实执行脚本（只读照片，不训练、不删除任何制品）。

手册 §T0 口径：
- /Users/zhangweiqi/miniconda3/bin/python，device=mps；
- 拒绝 PYTORCH_ENABLE_MPS_FALLBACK=1（检测到即终止）；
- 复用 run_mps_g0 出 G0 证据（arm64/MPS/矩阵/前向/AC/内存/磁盘/swap）；
- 照片池：照片1106 等间隔采样 160 张（≤200，不移动/覆盖原件）；
- 768/960/1024 三档 YOLO 前向 benchmark：images/s、MPS 峰值内存、
  swap/热状态前后对比；出现热限流立即停止；
- pick_resolution 选优（禁止默认 1280）+ budget_estimate 预算与停止线；
- 8091/8092/8400 服务健康（前后各一次）；
- 证据写 .eval/t0/t0_preflight_evidence_<ts>.json。

建议用法（caffeinate 由外层负责，脚本只检测并记录）：
  caffeinate -i /Users/zhangweiqi/miniconda3/bin/python3 -m \
      scripts.run_t0_mps_preflight
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOLUTIONS = (768, 960, 1024)   # 禁止 1280
N_SAMPLES = 160                  # 手册：100–200 张
BATCH = 16
WARMUP = 2
SERVICES = {"8091": "/v2/health", "8092": "/api/live",
            "8400": "/api/v1/health"}
PHOTO_DIR = ROOT / "照片1106"


def thermal_snapshot() -> dict:
    from src.training.t0_preflight import parse_thermal
    try:
        out = subprocess.run(["pmset", "-g", "therm"], capture_output=True,
                             text=True, timeout=5)
        txt = out.stdout or ""
    except Exception as e:
        return {"raw": "", "throttled": True, "detail": repr(e)}
    info = parse_thermal(txt)
    info["raw"] = txt.strip()
    return info


def service_health() -> dict[str, bool]:
    res: dict[str, bool] = {}
    for port, path in SERVICES.items():
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}{path}", timeout=3) as r:
                res[port] = r.status < 500
        except Exception:
            res[port] = False
    return res


def sample_photos() -> list[Path]:
    files = sorted(p for p in PHOTO_DIR.glob("*.jpg") if p.is_file())
    if not files:
        raise RuntimeError(f"照片池为空：{PHOTO_DIR}")
    if len(files) <= N_SAMPLES:
        return files
    step = len(files) / N_SAMPLES
    return [files[int(i * step)] for i in range(N_SAMPLES)]


def benchmark_one(model, files: list[Path], res: int) -> dict:
    import torch
    torch.mps.empty_cache()
    # warmup
    for i in range(0, WARMUP * BATCH, BATCH):
        model.predict([str(p) for p in files[i:i + BATCH]], imgsz=res,
                      device="mps", verbose=False)
    torch.mps.synchronize()
    t0 = time.perf_counter()
    n = 0
    peak_bytes = 0
    for i in range(0, len(files), BATCH):
        model.predict([str(p) for p in files[i:i + BATCH]], imgsz=res,
                      device="mps", verbose=False)
        n += min(BATCH, len(files) - i)
        torch.mps.synchronize()
        peak_bytes = max(peak_bytes, torch.mps.current_allocated_memory())
        # 停止线：热限流立即终止本档
        if thermal_snapshot()["throttled"]:
            raise RuntimeError(f"res={res} benchmark 中出现热限流，停止")
    torch.mps.synchronize()
    dt = time.perf_counter() - t0
    peak_gb = peak_bytes / 1e9
    return {"resolution": res, "n_images": n, "wall_seconds": round(dt, 2),
            "images_per_s": round(n / dt, 2),
            "peak_mem_gb": round(peak_gb, 3)}


def main() -> None:
    fb = os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK")
    if fb == "1":
        raise SystemExit("拒绝执行：PYTORCH_ENABLE_MPS_FALLBACK=1")

    from src.modules.training_gov.mps_gate import memory_info, run_mps_g0
    from src.training.t0_preflight import budget_estimate, pick_resolution

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / ".eval" / "t0"
    out_dir.mkdir(parents=True, exist_ok=True)

    evidence: dict = {"ts": ts, "python": __import__("sys").executable,
                      "caffeinate_in_env": "CAFFEINATE" in os.environ}

    # 1) G0 门禁
    g0 = run_mps_g0(disk_root=ROOT)
    evidence["g0"] = g0
    print("G0 ok:", g0["ok"])
    if not g0["ok"]:
        failed = [c["name"] for c in g0["checks"] if not c["ok"]]
        evidence["abort"] = f"G0 未通过：{failed}"
        path = out_dir / f"t0_preflight_evidence_{ts}.json"
        path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print("abort:", evidence["abort"], "| evidence:", path)
        raise SystemExit(1)

    # 2) 服务健康（前）
    evidence["services_before"] = service_health()
    evidence["thermal_before"] = thermal_snapshot()
    evidence["swap_before"] = memory_info()["swap"]

    # 3) 照片池采样（只读）
    files = sample_photos()
    evidence["photo_pool"] = {"dir": str(PHOTO_DIR), "sampled": len(files)}

    # 4) 三档 benchmark
    from ultralytics import YOLO
    model = YOLO(str(ROOT / "yolo11n.pt"))
    rows = []
    err = None
    try:
        for res in RESOLUTIONS:
            row = benchmark_one(model, files, res)
            rows.append(row)
            print(f"res={res}: {row['images_per_s']} img/s, "
                  f"peak={row['peak_mem_gb']} GB, wall={row['wall_seconds']}s")
    except Exception as e:
        err = repr(e)
        print("benchmark 中断:", err)
    evidence["benchmark_rows"] = rows
    if err:
        evidence["benchmark_error"] = err

    # 5) 选优 + 预算估算 + 停止线
    if rows:
        best = pick_resolution(rows)
        ips = next(r["images_per_s"] for r in rows
                   if r["resolution"] == best)
        evidence["chosen_resolution"] = best
        evidence["budget"] = {
            "t1_smoke_1ep": budget_estimate(n_images=len(files), epochs=1,
                                            images_per_s=ips),
            "t2_pilot_3ep_full_eligible": budget_estimate(
                n_images=1000, epochs=3, images_per_s=ips),
            "note": "T2 以全部 eligible 货架照估算；实际张数以数据集快照为准",
        }
    evidence["thermal_after"] = thermal_snapshot()
    evidence["swap_after"] = memory_info()["swap"]
    evidence["services_after"] = service_health()
    # 停止线诚实判定：swap 用量超过停止线必须如实报告（训练启动前需处置）
    swap_used = (evidence["swap_after"] or {}).get("used_mb")
    evidence["swap_status"] = {
        "used_mb": swap_used,
        "stop_line_mb": 8192.0,
        "exceeds_stop_line": (swap_used is not None
                              and swap_used > 8192.0),
        "note": "系统级 swap（含其他进程）；benchmark 不因此停止，"
                "但训练启动授权前必须如实报告并处置",
    }
    evidence["stop_lines"] = {"max_wall_hours": 6.0,
                              "max_swap_used_mb": 8192.0,
                              "thermal_event": "stop",
                              "run_dir_overwrite_guard":
                              "tests/unit/test_run_overwrite_guard.py"}
    evidence["no_training_executed"] = True

    path = out_dir / f"t0_preflight_evidence_{ts}.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print("chosen:", evidence.get("chosen_resolution"),
          "| evidence:", path)


if __name__ == "__main__":
    main()
