"""Qwen3-VL FMCG 数据集构建入口（VLM-008）。

输入：JSONL，每行一条候选样本行（字段见 src/training/vlm/builder._row 契约：
asset_id/photo_sha256/image_uri/image_width/image_height/box_px/sku_id/
package_version_id/target_type/label_source/review_status/split/
sample_kind/split_group/evidence_ids/frozen/active_protocol）。

红线：
- 输出目录已存在即拒绝（禁止覆盖旧数据集）；
- manual_pending/reject/frozen/model_provisional 无裁决不得进入 train；
- 划分防泄漏（SHA/near_dup/customer/store/session/package_version）。

用法：
  python3 -m scripts.build_qwen3vl_dataset \
      --input <rows.jsonl> --output <dir> --registry-version <ver>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.training.vlm.builder import BuilderError, build_dataset  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="候选样本 JSONL")
    ap.add_argument("--output", required=True, help="数据集输出目录（必须不存在）")
    ap.add_argument("--registry-version", required=True)
    a = ap.parse_args()

    input_path = Path(a.input)
    if not input_path.is_file():
        print(f"输入不存在，fail-closed: {input_path}", file=sys.stderr)
        return 2
    rows = [json.loads(line) for line in
            input_path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    try:
        report = build_dataset(rows, output_dir=Path(a.output),
                               registry_version=a.registry_version)
    except BuilderError as e:
        print(f"构建失败（fail-closed）: {e}", file=sys.stderr)
        return 3
    print(json.dumps({k: v for k, v in report.items() if k != "excluded"},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
