"""参数修正：基于识别对比报告，自动诊断问题并给出训练参数修正建议。

诊断逻辑（真值视为 100% 准确）：
  - 检测召回低（漏检多）→ 降 conf 阈值、增 imgsz、增 epochs、增 mosaic/scale 增强
  - 分类混淆高（误判多）→ 增 cls 损失权重、增 epochs、考虑增大模型
  - 精确率低（误检多）→ 增 epochs 让分类更稳、适度增 conf
  - 高置信仍错 → 数据层面问题（标注/类别不平衡），建议增样本
输出修正后的训练配置 JSON（供再训练使用）+ 人类可读建议。

用法：python -m src.eval.param_tune [--report .eval/compare_report.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT

EVAL_DIR = PROJECT_ROOT / ".eval"

# 当前基线训练参数
BASELINE = {"epochs": 80, "imgsz": 640, "batch": 8, "conf": 0.25, "cls_weight": 0.5, "lr0": 0.01}


def diagnose(report: dict) -> dict:
    rec_recall = report.get("detection_recall", 0)
    cls_acc = report.get("classification_accuracy_on_covered", 0)
    precision = report.get("precision", 0)
    fp = report.get("false_positives", 0)
    covered = report.get("covered", 0)

    issues = []
    params = dict(BASELINE)
    advice = []

    # 1. 检测召回
    if rec_recall < 0.85:
        issues.append("low_recall")
        params["imgsz"] = 960 if rec_recall < 0.6 else 768
        params["epochs"] = max(params["epochs"], 120)
        params["conf"] = 0.18
        advice.append(f"检测召回 {rec_recall*100:.0f}% 偏低（漏检多）：增大 imgsz 至 {params['imgsz']}、epochs 至 {params['epochs']}、降 conf 至 {params['conf']}，并增强 mosaic/scale 以覆盖更多尺度。")
    # 2. 分类准确率
    if cls_acc < 0.80 and covered > 0:
        issues.append("low_classification")
        params["cls_weight"] = 0.8 if cls_acc < 0.6 else 0.65
        params["epochs"] = max(params["epochs"], 120)
        advice.append(f"分类准确率 {cls_acc*100:.0f}% 不足（混淆多）：增大 cls 损失权重至 {params['cls_weight']}、epochs 至 {params['epochs']}，让模型更充分学习 208 类细粒度差异。")
    # 3. 精确率 / 误检
    if precision < 0.70:
        issues.append("low_precision")
        params["epochs"] = max(params["epochs"], 100)
        advice.append(f"精确率 {precision*100:.0f}% 偏低（误检 {fp} 个）：增加训练轮次稳定分类，必要时适度上调 conf。")
    # 4. 高置信错误（数据层面）
    buckets = report.get("conf_buckets", {})
    high_conf_wrong = 0
    for k, v in buckets.items():
        if k.startswith(("7", "8", "9", "10")):
            high_conf_wrong += v["total"] - v["correct"]
    if high_conf_wrong > 20:
        issues.append("high_conf_errors")
        advice.append(f"高置信区间仍有 {high_conf_wrong} 个错误：多为同品牌相似 SKU 混淆或类别样本不平衡，建议对 Top 混淆/漏检 SKU 补充标注样本后重新训练。")

    if not issues:
        advice.append("各项指标良好，维持当前参数，可继续增加数据巩固。")

    return {"issues": issues, "corrected_params": params, "advice": advice}


def main(report_path: str | None = None):
    rp = Path(report_path) if report_path else EVAL_DIR / "compare_report.json"
    report = json.loads(rp.read_text(encoding="utf-8"))
    result = diagnose(report)
    result["baseline"] = BASELINE
    result["source_report"] = str(rp)

    out = EVAL_DIR / "param_tune.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== 参数修正建议 ===")
    print(f"  诊断问题: {result['issues'] or '无'}")
    print(f"  基线参数: {BASELINE}")
    print(f"  修正参数: {result['corrected_params']}")
    print(f"\n  建议:")
    for a in result["advice"]:
        print(f"    - {a}")
    print(f"\n  输出: {out}")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=None)
    main(ap.parse_args().report)
