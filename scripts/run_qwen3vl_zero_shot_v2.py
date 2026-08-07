"""Qwen3-VL 零样本 V2 汇总入口（确定性，不加载权重）。

消费 run_qwen3vl_zero_shot_v2_infer 产出的 records.jsonl，按
evaluate_records_v2 口径出报告：candidate recall@1/5/8（真实检索
ranking 前 k，不伪造）、accepted precision、auto coverage、abstain
率、unknown/new packaging、Registry escape、p50/p95、每区域成本。

用法：
  python3 -m scripts.run_qwen3vl_zero_shot_v2 \
      --preflight-report .eval/vlm_preflight/<run_id>/preflight.json \
      --run-dir .eval/qwen3vl_zero_shot_v2/<run_id>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.training.vlm.evaluate import (  # noqa: E402
    build_default_identity_index,
    evaluate_records_v2,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preflight-report", required=True)
    ap.add_argument("--run-dir", required=True)
    a = ap.parse_args()

    pf_path = Path(a.preflight_report)
    if not pf_path.is_file():
        print(f"preflight 报告不存在，fail-closed: {pf_path}",
              file=sys.stderr)
        return 2
    if not json.loads(pf_path.read_text(encoding="utf-8")).get("ok"):
        print("preflight 未通过，拒绝汇总", file=sys.stderr)
        return 3

    run_dir = Path(a.run_dir)
    rec_path = run_dir / "records.jsonl"
    if not rec_path.is_file():
        print(f"评估记录不存在，fail-closed: {rec_path}", file=sys.stderr)
        return 2
    records = [json.loads(line) for line in
               rec_path.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    meta_path = run_dir / "meta.json"
    meta = (json.loads(meta_path.read_text(encoding="utf-8"))
            if meta_path.is_file() else {})
    # 任务书§十五：identity 判定走 canonical sku_id 映射链
    kb_root = ROOT / str(meta.get("kb_root") or ".kb")
    identity_index = build_default_identity_index(ROOT, kb_root=kb_root)
    report = evaluate_records_v2(
        records, wall_seconds=meta.get("wall_seconds"),
        identity_index=identity_index)
    report["sampling_report"] = meta.get("sampling_report")
    report["infer_version"] = meta.get("infer_version")
    report["evidence_level"] = meta.get("evidence_level",
                                         "sam_refined_interim")
    report["kb_sku_count"] = meta.get("kb_sku_count")
    report["preflight_report"] = str(pf_path)
    out = run_dir / "report.json"
    if out.exists():
        print(f"报告已存在，拒绝覆盖（不可变证据）: {out}", file=sys.stderr)
        return 4
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"报告 -> {out}")
    return 0 if report["gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
