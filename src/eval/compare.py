"""识别结果对比分析：假设给定训练数据 100% 准确，将全量识别结果与真值对比。

匹配规则：真值点 (x,y) 落在预测框内即视为"检出"；取覆盖框中置信度最高者的 SKU 与真值比对。
输出：
  检测召回率、误检数、分类准确率、混淆矩阵 Top 错误、按置信度分桶准确率、漏检 SKU 分布。
  .eval/compare_report.json

用法：python -m src.eval.compare [--input .eval/full_recognize.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT

EVAL_DIR = PROJECT_ROOT / ".eval"


def _point_in_box(x, y, box):
    x1, y1, x2, y2 = box
    return x1 <= x <= x2 and y1 <= y <= y2


def analyze(records: list[dict]) -> dict:
    tot_gt = tot_covered = tot_correct = 0
    false_positives = 0
    confusion = Counter()  # (gt_name, pred_name) -> count
    missed_sku = Counter()  # gt_name -> 漏检次数
    wrong_sku = Counter()  # gt_name -> 分类错误次数
    conf_buckets = defaultdict(lambda: {"correct": 0, "total": 0})  # bucket -> stats

    for rec in records:
        preds = rec["predictions"]
        gts = rec["ground_truth"]
        # 标记每个预测框是否匹配到真值
        pred_matched = [False] * len(preds)

        for gt in gts:
            gx, gy, gname = gt["x"], gt["y"], gt.get("name")
            if gx is None or gy is None:
                continue
            tot_gt += 1
            # 找覆盖该点的预测框
            covering = [(i, p) for i, p in enumerate(preds) if _point_in_box(gx, gy, p["box"])]
            if not covering:
                missed_sku[gname or "?"] += 1
                continue
            tot_covered += 1
            # 取置信度最高的覆盖框
            bi, best = max(covering, key=lambda ip: ip[1]["conf"])
            pred_matched[bi] = True
            pname = best.get("name")
            conf = best.get("conf", 0)
            bucket = f"{int(conf*10)*10}-{int(conf*10)*10+10}%"
            conf_buckets[bucket]["total"] += 1
            if pname == gname:
                tot_correct += 1
                conf_buckets[bucket]["correct"] += 1
            else:
                confusion[(gname or "?", pname or "?")] += 1
                wrong_sku[gname or "?"] += 1

        # 误检：未匹配到任何真值的预测框
        for i, matched in enumerate(pred_matched):
            if not matched:
                false_positives += 1

    det_recall = tot_covered / tot_gt if tot_gt else 0
    cls_acc = tot_correct / tot_covered if tot_covered else 0
    precision = tot_correct / (tot_correct + false_positives) if (tot_correct + false_positives) else 0

    top_confusion = [{"gt": g, "pred": p, "count": c} for (g, p), c in confusion.most_common(30)]
    top_missed = [{"sku": s, "count": c} for s, c in missed_sku.most_common(20)]
    top_wrong = [{"sku": s, "count": c} for s, c in wrong_sku.most_common(20)]
    buckets = {k: {**v, "acc": round(v["correct"]/v["total"], 4) if v["total"] else 0} for k, v in sorted(conf_buckets.items())}

    return {
        "total_gt": tot_gt, "covered": tot_covered, "correct": tot_correct,
        "false_positives": false_positives,
        "detection_recall": round(det_recall, 4),
        "classification_accuracy_on_covered": round(cls_acc, 4),
        "precision": round(precision, 4),
        "overall_accuracy": round(tot_correct / tot_gt, 4) if tot_gt else 0,
        "top_confusion": top_confusion,
        "top_missed_sku": top_missed,
        "top_wrong_sku": top_wrong,
        "conf_buckets": buckets,
    }


def main(input_path: str | None = None):
    inp = Path(input_path) if input_path else EVAL_DIR / "full_recognize.json"
    data = json.loads(inp.read_text(encoding="utf-8"))
    records = data["records"]
    report = analyze(records)
    report["conf"] = data.get("conf")
    report["photos"] = len(records)

    out = EVAL_DIR / "compare_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== 识别对比报告（真值视为 100% 准确）===")
    print(f"  照片: {report['photos']} | 真值标注: {report['total_gt']}")
    print(f"  检测召回率: {report['detection_recall']*100:.1f}%  ({report['covered']}/{report['total_gt']})")
    print(f"  分类准确率(检出中): {report['classification_accuracy_on_covered']*100:.1f}%")
    print(f"  精确率: {report['precision']*100:.1f}%  | 误检框: {report['false_positives']}")
    print(f"  整体准确率: {report['overall_accuracy']*100:.1f}%")
    print(f"\n  Top 混淆（真值→误判）:")
    for c in report["top_confusion"][:8]:
        print(f"    {c['gt']}  →  {c['pred']}  ({c['count']}次)")
    print(f"\n  Top 漏检 SKU:")
    for m in report["top_missed_sku"][:8]:
        print(f"    {m['sku']}: {m['count']}次")
    print(f"\n  按置信度分桶准确率:")
    for k, v in report["conf_buckets"].items():
        print(f"    {k}: {v['acc']*100:.0f}% ({v['correct']}/{v['total']})")
    print(f"\n  报告: {out}")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=None)
    main(ap.parse_args().input)
