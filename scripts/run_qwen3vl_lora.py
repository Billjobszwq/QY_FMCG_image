"""Qwen3-VL QLoRA 受治理入口（VLM-011，真实执行被门禁阻断）。

门禁：必须先通过 preflight（G-CURRENT/G-APPLE）且报告 ok=true；即使
通过，主环境也不执行真实 QLoRA（需独立环境 .venv_mlx_vlm、当日版本
lock 与独立授权；当前训练存在时一律 BLOCKED_BY_ACTIVE_TRAINING）。
本入口只输出冻结的 MLX-VLM 命令供隔离环境消费，禁止假装已训练。

用法：
  python3 -m scripts.run_qwen3vl_lora \
      --preflight-report .eval/vlm_preflight/<run_id>/preflight.json \
      --dataset .datasets/vlm_v1/hf --output-dir .models/qwen3vl_lora_r1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.training.vlm.train import (  # noqa: E402
    DEFAULT_BASE_MODEL, VLM_TRAINER_VERSION, VlmPlanError, build_mlx_command,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preflight-report", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--batch-size", type=int, default=1)
    ap.add_argument("--learning-rate", type=float, default=1e-5)
    ap.add_argument("--lora-rank", type=int, default=16)
    ap.add_argument("--lora-alpha", type=int, default=32)
    ap.add_argument("--gradient-accumulation-steps", type=int, default=1)
    ap.add_argument("--model-path", default=DEFAULT_BASE_MODEL)
    a = ap.parse_args()

    path = Path(a.preflight_report)
    if not path.is_file():
        print(f"preflight 报告不存在，fail-closed: {path}", file=sys.stderr)
        return 2
    preflight = json.loads(path.read_text(encoding="utf-8"))
    if not preflight.get("ok"):
        print("preflight 未通过（BLOCKED_BY_ACTIVE_TRAINING/未授权），"
              "拒绝生成真实 QLoRA 训练命令", file=sys.stderr)
        return 3

    spec = {
        "model_path": a.model_path, "dataset_path": a.dataset,
        "output_dir": a.output_dir, "epochs": a.epochs,
        "batch_size": a.batch_size, "learning_rate": a.learning_rate,
        "lora_rank": a.lora_rank, "lora_alpha": a.lora_alpha,
        "gradient_accumulation_steps": a.gradient_accumulation_steps,
        "train_vision": False,  # 第一轮 vision frozen，需独立授权另走治理
    }
    try:
        command = build_mlx_command(spec)
    except VlmPlanError as e:
        print(str(e), file=sys.stderr)
        return 2

    print(json.dumps({
        "trainer_version": VLM_TRAINER_VERSION,
        "command": command,
        "blocked": True,
        "reason": ("真实 QLoRA 必须在独立环境 .venv_mlx_vlm 执行并需独立"
                   "授权；主环境训练门禁生效，不加载权重、不发起训练，"
                   "禁止假装已训练"),
    }, ensure_ascii=False, indent=1))
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
