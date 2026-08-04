"""SAM 辅助标注 Worker（手册§一.8：隔离环境，不污染主 Python 环境）。

两部分：
- SAMWorkerClient（主环境调用）：以子进程方式用 `.venv_sam/bin/python`
  执行本模块 `--worker` 入口；请求/响应均为 JSON，mask 以 PNG 落盘并计算 SHA256。
- worker 入口（隔离 venv 内运行）：加载 SAM 2.1，执行 MPS 门禁，
  每图只算一次 image embedding（同图所有坐标共享），输出候选元数据。

worker 绝不写业务事实：只返回 mask/得分/计时；硬约束筛选、评分与
证据链由主环境的 candidates/scoring/evidence 承担。"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAM_PYTHON = PROJECT_ROOT / ".venv_sam" / "bin" / "python"


class SAMWorkerError(RuntimeError):
    pass


class SAMWorkerClient:
    """主环境 → 隔离 venv 的子进程调用。"""

    def __init__(self, python: Path = SAM_PYTHON, timeout: int = 1800):
        self.python = Path(python)
        self.timeout = timeout
        if not self.python.exists():
            raise SAMWorkerError(f"隔离 SAM 环境不存在: {self.python}（先建 .venv_sam）")

    def invoke(self, request: dict) -> dict:
        req_path = Path(request["_request_path"])
        req_path.parent.mkdir(parents=True, exist_ok=True)
        req_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        cmd = [str(self.python), "-m", "src.sam_assist.service",
               "--worker", "--request", str(req_path)]
        t0 = time.time()
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True,
                              timeout=self.timeout)
        elapsed = time.time() - t0
        if proc.returncode != 0:
            raise SAMWorkerError(
                f"SAM worker 失败 (exit={proc.returncode}, {elapsed:.1f}s):\n"
                f"{proc.stderr[-3000:]}")
        try:
            resp = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise SAMWorkerError(f"SAM worker 输出非 JSON: {e}\n{proc.stdout[-2000:]}")
        if not resp.get("ok"):
            raise SAMWorkerError(f"SAM worker 报告失败: {resp.get('error')}")
        resp["wall_time_sec"] = round(elapsed, 2)
        return resp


def _swap_usage() -> str:
    try:
        out = subprocess.run(["sysctl", "vm.swapusage"], capture_output=True,
                             text=True, timeout=10).stdout.strip()
        return out
    except Exception:
        return "(unavailable)"


def _run_worker(request: dict) -> dict:
    """隔离 venv 内执行：SAM 2.1 推理。fail-closed：任何 MPS 异常直接报错。"""
    import hashlib
    import os
    import platform
    import resource

    import numpy as np
    import torch

    if os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK"):
        return {"ok": False, "error": "PYTORCH_ENABLE_MPS_FALLBACK 被禁止（手册§一.7）"}
    if not (torch.backends.mps.is_built() and torch.backends.mps.is_available()):
        return {"ok": False, "error": "MPS 不可用，禁止 CPU fallback（手册§一.7）"}

    import cv2
    from sam2.build_sam import build_sam2
    from sam2.sam2_image_predictor import SAM2ImagePredictor

    model = request["model"]
    ckpt = Path(request["checkpoint"])
    if not ckpt.exists():
        return {"ok": False, "error": f"checkpoint 不存在: {ckpt}"}

    device = torch.device("mps")
    t_load0 = time.time()
    sam = build_sam2(request["config"], str(ckpt), device=device)
    predictor = SAM2ImagePredictor(sam)
    load_sec = time.time() - t_load0

    out_dir = Path(request["out_dir"])
    masks_dir = out_dir / "masks"
    masks_dir.mkdir(parents=True, exist_ok=True)

    env_report = {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "machine": platform.machine(),
        "device": str(device),
        "model": model,
        "checkpoint_sha256": request.get("checkpoint_sha256", ""),
        "load_sec": round(load_sec, 2),
        "swap_before": _swap_usage(),
    }

    results = []
    for img_req in request["images"]:
        blob = Path(img_req["image_path"])
        img_bgr = cv2.imread(str(blob), cv2.IMREAD_COLOR)
        if img_bgr is None:
            return {"ok": False, "error": f"图片解码失败: {blob}"}
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

        torch.mps.reset_peak_memory_stats()
        t0 = time.time()
        predictor.set_image(img_rgb)          # image embedding：每图一次
        enc_sec = time.time() - t0

        inst_out = []
        for inst in img_req["instances"]:
            pts = np.array([inst["positive"]] + list(inst.get("negatives", [])),
                           dtype=np.float32)
            labels = np.array([1] + [0] * len(inst.get("negatives", [])), dtype=np.int32)
            box = np.array(inst["coarse_box"], dtype=np.float32) if inst.get("coarse_box") else None

            t1 = time.time()
            masks, scores, logits = predictor.predict(
                point_coords=pts, point_labels=labels,
                box=box, multimask_output=True)
            dec_sec = time.time() - t1

            cands = []
            for ci, (m, s) in enumerate(zip(masks, scores)):
                m_u8 = (m > 0).astype(np.uint8) * 255
                mp = masks_dir / f"{img_req['image_sha'][:12]}_{inst['instance_id']}_{ci}.png"
                cv2.imwrite(str(mp), m_u8)
                sha = hashlib.sha256(mp.read_bytes()).hexdigest()
                ys, xs = np.nonzero(m > 0)
                cands.append({
                    "candidate_id": f"c{ci}",
                    "mask_path": str(mp),
                    "mask_sha256": sha,
                    "iou_score": float(s),
                    "stability_score": float(s),
                    "area_px": int(len(xs)),
                    "bbox": [int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)]
                            if len(xs) else None,
                })
            inst_out.append({"instance_id": inst["instance_id"],
                             "decoder_sec": round(dec_sec, 4), "candidates": cands})
        results.append({
            "image_sha": img_req["image_sha"],
            "encoder_sec": round(enc_sec, 4),
            "mps_peak_mem_bytes": int(torch.mps.driver_allocated_memory() or 0),
            "instances": inst_out,
        })

    env_report["swap_after"] = _swap_usage()
    env_report["peak_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 1)
    return {"ok": True, "env": env_report, "results": results}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", action="store_true")
    ap.add_argument("--request", required=True)
    a = ap.parse_args()
    if not a.worker:
        print("本模块仅支持 --worker 模式（由 SAMWorkerClient 子进程调用）", file=sys.stderr)
        sys.exit(2)
    request = json.loads(Path(a.request).read_text(encoding="utf-8"))
    resp = _run_worker(request)
    print(json.dumps(resp, ensure_ascii=False))
    sys.exit(0 if resp.get("ok") else 1)


if __name__ == "__main__":
    main()
