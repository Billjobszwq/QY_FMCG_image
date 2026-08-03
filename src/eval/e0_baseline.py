"""E0-current-bundle-baseline：当前生产 bundle 在 dev_v1（未见门店）上的基线评估。

实验约束（训练方案 Task 3）：
  - bundle/数据/阈值固定：prod_20260804_v4_r2，conf/margin 以 bundle thresholds.json
    为准（缺失字段如实标注 code_default）
  - 一对一匹配（当前为 point-in-box，宽松口径；严格 IoU 评估为后续任务）
  - 逐样本错误账本：每个错误归且仅归一个主因
  - 结果只用于基线，不用于调参（调参看 dev 日常迭代）

用法：python -m src.eval.e0_baseline [--set dev_v1] [--limit 0]"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT

PROTOCOL_DIR = PROJECT_ROOT / ".data_protocol"
CLEAN_MANIFEST = PROJECT_ROOT / ".batch3_clean" / "clean_manifest.json"
CLEAN_BLOBS = PROJECT_ROOT / ".batch3_clean" / "blobs"
EVAL_OUT = PROJECT_ROOT / ".eval" / "e0"
REPORT_MD = PROJECT_ROOT / "docs" / "experiments" / "E0-current-bundle-baseline.md"


def _load_recognizer():
    """从当前生产 bundle 构建识别器（加载前逐文件哈希校验）。"""
    from ..models import bundle as B
    from ..cascade.cascade_inference import CascadeRecognizer
    info = B.resolve_weights()  # verify=True，fail-closed
    kwargs = {}
    thr = info.get("threshold_values") or {}
    if isinstance(thr.get("conf"), (int, float)):
        kwargs["conf_thr"] = float(thr["conf"])
    if isinstance(thr.get("margin"), (int, float)):
        kwargs["margin_thr"] = float(thr["margin"])
    registry = None
    if info.get("registry"):
        registry = json.loads(Path(info["registry"]).read_text(encoding="utf-8"))
    rec = CascadeRecognizer(yolo_weight=info["detector"], clf_weight=info["classifier"],
                            registry=registry, **kwargs)
    return rec, info


def evaluate(set_name: str = "dev_v1", limit: int = 0, conf: float = 0.18) -> dict:
    proto = json.loads((PROTOCOL_DIR / f"{set_name}.json").read_text(encoding="utf-8"))
    clean = json.loads(CLEAN_MANIFEST.read_text(encoding="utf-8"))
    from ..training.build_sku_v6_dataset import parse_batch3_annotations
    anns = parse_batch3_annotations()
    registry = json.loads((PROJECT_ROOT / "data" / "sku_registry.json").read_text(encoding="utf-8"))
    name_to_sku = {k: v["sku_id"] for k, v in registry.items()}

    rec, binfo = _load_recognizer()
    thr_src = binfo.get("threshold_source") or {"conf": "code_default", "margin": "code_default"}

    photo_ids = proto["photo_ids"]
    if limit > 0:
        photo_ids = photo_ids[:limit]

    agg = Counter()
    err = Counter()
    details = []
    t0 = time.time()
    for i, pid in enumerate(photo_ids):
        recd = clean.get(pid)
        blob = CLEAN_BLOBS / recd["sha256"][:2] / recd["sha256"] if recd else None
        if not blob or not blob.exists():
            agg["photo_missing"] += 1
            continue
        gts = [(float(a["x"]), float(a["y"]), a["name"]) for a in anns.get(pid, [])]
        preds = rec.recognize(blob.read_bytes(), conf=conf)
        # 一对一 point-in-box 匹配（预测按 classifier_conf 降序贪心）
        gts_left = list(range(len(gts)))
        matched, fp = [], []
        for pr in sorted(preds, key=lambda p: -p.get("classifier_conf", 0)):
            b = pr["box"]
            cands = [gi for gi in gts_left if b[0] <= gts[gi][0] <= b[2] and b[1] <= gts[gi][1] <= b[3]]
            if not cands:
                fp.append(pr)
                continue
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            gi = min(cands, key=lambda g: (gts[g][0] - cx) ** 2 + (gts[g][1] - cy) ** 2)
            matched.append((pr, gi))
            gts_left.remove(gi)

        n_accepted_correct = n_accepted_wrong = n_unknown_accept = 0
        n_review = 0
        for pr, gi in matched:
            gt_name = gts[gi][2]
            gt_sku = name_to_sku.get(gt_name)
            if pr["status"] == "accepted":
                if gt_sku is None:
                    n_unknown_accept += 1
                    err["unknown_false_accept"] += 1
                elif pr["sku_id"] == gt_sku:
                    n_accepted_correct += 1
                else:
                    n_accepted_wrong += 1
                    err["classifier_confusion"] += 1
            else:
                n_review += 1
                err["known_false_reject" if gt_sku else "unknown_review"] += 1
        for gi in gts_left:
            err["missed_detection"] += 1
        for pr in fp:
            if pr["status"] == "accepted":
                err["fp_accepted"] += 1
            else:
                err["fp_review"] += 1

        agg["photos"] += 1
        agg["gt_total"] += len(gts)
        agg["gt_covered"] += len(matched)
        agg["accepted_correct"] += n_accepted_correct
        agg["accepted_wrong"] += n_accepted_wrong
        agg["unknown_accept"] += n_unknown_accept
        agg["review_matched"] += n_review
        agg["missed"] += len(gts_left)
        agg["fp"] += len(fp)
        agg["n_accepted"] += sum(1 for pr in preds if pr["status"] == "accepted")
        exact = (len(gts_left) == 0 and n_accepted_wrong == 0 and n_unknown_accept == 0
                 and len(matched) == len(gts) and not any(p["status"] == "accepted" for p in fp))
        agg["photo_exact"] += int(exact)
        agg["count_ae"] += abs(agg_delta := (sum(1 for pr in preds if pr["status"] == "accepted") - len(gts)))
        details.append({"pid": pid, "n_gt": len(gts), "n_pred": len(preds),
                        "matched": len(matched), "accepted_correct": n_accepted_correct,
                        "accepted_wrong": n_accepted_wrong, "review": n_review,
                        "fp": len(fp), "missed": len(gts_left), "exact": exact})
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(photo_ids)}  耗时 {time.time() - t0:.0f}s", flush=True)

    p = agg["photos"] or 1
    cov = agg["gt_covered"] / max(1, agg["gt_total"])
    acc_total = agg["accepted_correct"] + agg["accepted_wrong"] + agg["unknown_accept"]
    metrics = {
        "set": set_name, "bundle": binfo["bundle_id"],
        "thresholds": {"conf": rec.conf_thr, "margin": rec.margin_thr, "source": thr_src},
        "n_photos": p, "elapsed_sec": round(time.time() - t0, 1),
        "detection_coverage": round(cov, 4),                     # GT 被至少一个 proposal 覆盖
        "accepted_precision": round(agg["accepted_correct"] / acc_total, 4) if acc_total else None,
        "end_to_end_recall": round(agg["accepted_correct"] / max(1, agg["gt_total"]), 4),
        "coverage_of_accepted": round(agg["accepted_correct"] / max(1, agg["gt_total"]), 4),
        "review_rate_matched": round(agg["review_matched"] / max(1, agg["gt_covered"]), 4),
        "fp_per_photo": round(agg["fp"] / p, 3),
        "photo_exact_set_accuracy": round(agg["photo_exact"] / p, 4),
        "count_mae": round(agg["count_ae"] / p, 3),
        "error_ledger": dict(err),
    }
    EVAL_OUT.mkdir(parents=True, exist_ok=True)
    (EVAL_OUT / f"{set_name}_details.json").write_text(
        json.dumps({"metrics": metrics, "details": details}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return metrics


def write_report(m: dict, set_name: str) -> None:
    import subprocess
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() or "(未提交)"
    e = m["error_ledger"]
    md = f"""# E0 当前 bundle 基线（{set_name}，未见门店）

- experiment_id: E0-current-bundle-baseline
- bundle: `{m['bundle']}`
- code_commit: `{commit}`
- 评估集: `.data_protocol/{set_name}.json`（n={m['n_photos']}，与训练门店/SHA 零交集，seen_by_current_model=false）
- 阈值: conf={m['thresholds']['conf']} / margin={m['thresholds']['margin']}（来源: {m['thresholds']['source']}）
- 匹配口径: 一对一 point-in-box（宽松诊断口径，正式 IoU 评估为后续任务）
- 耗时: {m['elapsed_sec']}s

## 指标

| 指标 | 值 |
|---|---:|
| 检测覆盖（GT 被 proposal 覆盖） | {m['detection_coverage']:.1%} |
| accepted precision | {m['accepted_precision']:.1%} |
| 端到端召回（accepted 且正确 / GT） | {m['end_to_end_recall']:.1%} |
| 已匹配中进入 review 比例 | {m['review_rate_matched']:.1%} |
| FP / 照片 | {m['fp_per_photo']} |
| 照片全对率（exact-set） | {m['photo_exact_set_accuracy']:.1%} |
| count MAE | {m['count_mae']} |

## 错误账本

{json.dumps(e, ensure_ascii=False, indent=2)}

## 决策

promote / iterate / stop：见报告讨论（本文件由脚本生成，结论人工补充）。
"""
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(md, encoding="utf-8")
    print(f"报告已写入: {REPORT_MD}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="dev_v1")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    metrics = evaluate(a.set, a.limit)
    write_report(metrics, a.set)
