"""Qwen3-VL 零样本评估入口（VLM-010，真实执行被门禁阻断）。

必须先通过 preflight（G-CURRENT/G-APPLE）：本脚本要求传入一份
ok=true 的 preflight 报告，否则拒绝执行；评估记录由上游推理产出，
本入口只做确定性汇总，不加载权重、不发起真实前向。

用法：
  python3 -m scripts.run_qwen3vl_zero_shot \
      --preflight-report .eval/vlm_preflight/<run_id>/preflight.json \
      --records records.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.training.vlm.evaluate import evaluate_records  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preflight-report", required=True)
    ap.add_argument("--records", required=True,
                    help="评估记录 JSONL（evaluate.record 字段）")
    a = ap.parse_args()

    preflight_path = Path(a.preflight_report)
    if not preflight_path.is_file():
        print(f"preflight 报告不存在，fail-closed: {preflight_path}",
              file=sys.stderr)
        return 2
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if not preflight.get("ok"):
        print("preflight 未通过（BLOCKED_BY_ACTIVE_TRAINING/未授权），"
              "拒绝执行真实零样本推理", file=sys.stderr)
        return 3

    records_path = Path(a.records)
    if not records_path.is_file():
        print(f"评估记录不存在，fail-closed: {records_path}", file=sys.stderr)
        return 2
    records = [json.loads(line) for line in
               records_path.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    report = evaluate_records(records)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if report["gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
