"""Cascade shadow 评估真实入口（计划 §Task 17）。

模式：
- evaluate：纯计算。读取 shadow 账本 JSON（{"arms", "runs"}），
  对每个对照臂计算指标并过晋级门，输出报告 JSON。
  不加载任何模型，可与训练并行。
- run：真实 shadow 批量推理。受 G-CURRENT/G-APPLE 门禁控制：
  存在活跃训练 → BLOCKED_BY_ACTIVE_TRAINING；未获明确授权 → 拒绝；
  本轮 Qwen/MLX 未安装，真实 runner 保持 fail-closed，绝不伪造结果。

用法：
  python3 -m scripts.run_cascade_shadow_eval --mode evaluate \
      --input ledger.json --output report.json
  python3 -m scripts.run_cascade_shadow_eval --mode run
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.eval.cascade_shadow import (  # noqa: E402
    EVAL_VERSION,
    evaluate_arm,
    promotion_gate,
    shadow_execution_gate,
    validate_arms,
)


def collect_process_commands() -> list[str]:
    """读取当前进程表命令行（只读操作）。"""
    try:
        out = subprocess.run(["ps", "-axo", "command"],
                             capture_output=True, text=True, timeout=10)
        return [line.strip() for line in out.stdout.splitlines() if line.strip()]
    except Exception:
        return []


def _evaluate(args: argparse.Namespace) -> int:
    ledger = json.loads(Path(args.input).read_text(encoding="utf-8"))
    arms = ledger["arms"]
    validate_arms(arms)
    metrics: dict[str, dict] = {}
    gate: dict[str, dict] = {}
    for arm_id, records in ledger.get("runs", {}).items():
        m = evaluate_arm(arms[arm_id], records)
        metrics[arm_id] = m
        gate[arm_id] = promotion_gate(
            m, thresholds=ledger.get("thresholds"),
            min_evaluable_truths=int(ledger.get(
                "min_evaluable_truths", 20)))
    report = {"eval_version": EVAL_VERSION, "arms": arms,
              "metrics": metrics, "gate": gate}
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"报告已写入: {out}")
    for arm_id, verdict in gate.items():
        m = metrics[arm_id]
        print(f"  {arm_id}: precision={m['accepted_precision']} "
              f"coverage={m['coverage']} → {verdict['status']}")
    return 0


def _run(args: argparse.Namespace) -> int:
    if args.simulate_processes is not None:
        processes = [p for p in args.simulate_processes.split(",") if p]
    else:
        processes = collect_process_commands()
    gate = shadow_execution_gate(processes=processes,
                                 active_training_leases=args.training_leases)
    if not gate["ok"]:
        print("BLOCKED_BY_ACTIVE_TRAINING: 存在活跃训练进程/租约，"
              "真实 shadow 运行被门禁拒绝（G-CURRENT）。", file=sys.stderr)
        return 2
    if not args.authorized:
        print("真实 shadow 运行未获用户明确授权，拒绝执行（G-SHADOW 前置）。",
              file=sys.stderr)
        return 3
    # 诚实 fail-closed：本轮未安装 MLX/Qwen 权重，真实 runner 不存在。
    print("G-APPLE 未通过：MLX/Qwen3-VL 未安装、权重未下载；"
          "真实 shadow runner 保持阻断，不得伪造运行结果。", file=sys.stderr)
    return 4


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Cascade shadow 评估入口")
    ap.add_argument("--mode", choices=("evaluate", "run"), required=True)
    ap.add_argument("--input", help="evaluate 模式：账本 JSON 路径")
    ap.add_argument("--output", help="evaluate 模式：报告 JSON 输出路径")
    ap.add_argument("--authorized", action="store_true",
                    help="run 模式：已获得用户对真实运行的明确授权")
    ap.add_argument("--training-leases", type=int, default=0,
                    help="当前活跃训练租约数（由平台提供）")
    ap.add_argument("--simulate-processes", default=None,
                    help="测试注入：逗号分隔的进程命令行（空串=无进程）")
    args = ap.parse_args(argv)
    if args.mode == "evaluate":
        if not args.input:
            print("evaluate 模式必须提供 --input", file=sys.stderr)
            return 1
        return _evaluate(args)
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
