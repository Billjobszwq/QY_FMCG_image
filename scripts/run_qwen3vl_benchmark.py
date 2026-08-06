"""Qwen3-VL 200–500 step 吞吐探针入口（VLM-010，真实执行被门禁阻断）。

门禁：必须传入 ok=true 的 preflight 报告；即使通过，主环境也不执行
真实探针（需独立环境 .venv_mlx_vlm 与安装当日版本 lock），本入口只
输出冻结的 benchmark matrix 供隔离环境消费，禁止假装已验证。

用法：
  python3 -m scripts.run_qwen3vl_benchmark \
      --preflight-report .eval/vlm_preflight/<run_id>/preflight.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.training.vlm.benchmark import (  # noqa: E402
    BENCHMARK_VERSION, benchmark_matrix,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preflight-report", required=True)
    a = ap.parse_args()

    path = Path(a.preflight_report)
    if not path.is_file():
        print(f"preflight 报告不存在，fail-closed: {path}", file=sys.stderr)
        return 2
    preflight = json.loads(path.read_text(encoding="utf-8"))
    if not preflight.get("ok"):
        print("preflight 未通过（BLOCKED_BY_ACTIVE_TRAINING/未授权），"
              "拒绝执行真实 benchmark", file=sys.stderr)
        return 3

    print(json.dumps({
        "benchmark_version": BENCHMARK_VERSION,
        "matrix": benchmark_matrix(),
        "blocked": True,
        "reason": ("真实探针必须在独立环境 .venv_mlx_vlm 执行，"
                   "主环境未安装 mlx，禁止假装已验证"),
    }, ensure_ascii=False, indent=1))
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
