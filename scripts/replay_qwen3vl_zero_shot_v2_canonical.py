"""只读重放：用 canonical sku_id 分类器重新解读历史 zero-shot V2 记录。

任务书§十五证据脚本：读取既有 .eval/qwen3vl_zero_shot_v2/<run_id>/
records.jsonl，按新 canonical 映射链重放分类，输出拆分结果到 stdout。

红线：纯只读——不改写 records.jsonl / report.json 等任何历史证据文件；
不加载模型、不发起推理。

用法：
  python3 -m scripts.replay_qwen3vl_zero_shot_v2_canonical \
      --run-dir .eval/qwen3vl_zero_shot_v2/20260807_172812 \
      [--kb-root .kb] [--json-out /tmp/replay.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.training.vlm.evaluate import (  # noqa: E402
    ERROR_TAXONOMY,
    IDENTITY_MATCH,
    build_default_identity_index,
    classify_sku_identity,
    evaluate_records_v2,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--kb-root", default=".kb")
    ap.add_argument("--json-out", default=None,
                    help="可选：把重放报告写到 run 目录之外的新文件"
                         "（绝不写回 run 目录）")
    a = ap.parse_args()

    run_dir = Path(a.run_dir)
    rec_path = run_dir / "records.jsonl"
    if not rec_path.is_file():
        print(f"records.jsonl 不存在: {rec_path}", file=sys.stderr)
        return 2
    # 只读指纹：重放前后历史文件必须逐字节一致
    watch = [p for p in (rec_path, run_dir / "report.json") if p.is_file()]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in watch}

    records = [json.loads(l) for l in
               rec_path.read_text(encoding="utf-8").splitlines()
               if l.strip()]
    index = build_default_identity_index(ROOT, kb_root=a.kb_root)
    legacy_report_path = run_dir / "report.json"
    legacy = (json.loads(legacy_report_path.read_text(encoding="utf-8"))
              if legacy_report_path.is_file() else {})

    report = evaluate_records_v2(records, identity_index=index)
    per_record = [
        {"source": r.get("source"), "gt": r.get("gt"),
         "decision": r.get("decision"), "pred": r.get("pred"),
         "gt_sku_id": index.resolve_sku_identity(r.get("gt")).sku_id,
         "category": classify_sku_identity(r, index)}
        for r in records]

    print("=== 旧口径（展示名比较，历史 report.json） ===")
    for k in ("accepted_precision", "candidate_recall_at_1",
              "registry_escape", "kb_coverage_of_sample"):
        print(f"  {k}: {legacy.get(k)}")
    print("=== 新口径（canonical sku_id 映射链重放） ===")
    for k in ("accepted_precision", "candidate_recall_at_1",
              "candidate_recall_at_5", "candidate_recall_at_8",
              "registry_escape", "kb_coverage_of_sample"):
        print(f"  {k}: {report.get(k)}")
    print("=== 7 类错误分类拆分 ===")
    taxo = report.get("error_taxonomy", {})
    for cat in (*ERROR_TAXONOMY, IDENTITY_MATCH):
        print(f"  {cat}: {taxo.get(cat, 0)}")
    print("=== 逐条分类 ===")
    for pr in per_record:
        print(f"  [{pr['category']}] {pr['source']} gt={pr['gt']!r} "
              f"decision={pr['decision']} pred={pr['pred']!r} "
              f"sku_id={pr['gt_sku_id']}")

    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in watch}
    if before != after:
        print("严重错误：只读重放改动了历史证据文件", file=sys.stderr)
        return 3
    print("只读校验通过：历史 records.jsonl / report.json 未被改动")

    if a.json_out:
        out = Path(a.json_out)
        if run_dir in out.resolve().parents or out.parent == run_dir:
            print("拒绝把重放结果写回 run 目录（不可变证据）",
                  file=sys.stderr)
            return 4
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"report": report,
                                   "per_record": per_record},
                                  ensure_ascii=False, indent=1),
                       encoding="utf-8")
        print(f"重放报告 -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
