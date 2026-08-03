"""E0-strict-iou 基线（G5 门禁实现）：严格 one-to-one IoU + 业务 precision 口径。

与旧 e0_baseline（point-in-box，matched-conditional precision）的区别：
  1. 匹配口径：GT 由锚点 + SKU 比例盒（sku_box_frac / 未注册 UNREGISTERED_BOX_FRAC）
     生成像素框，预测框与 GT 框计算 IoU，贪心按 IoU 降序做严格 one-to-one 匹配
     （每个 GT 至多匹配一个 proposal，反之亦然）。
  2. 口径纠正：报告两种 precision——
     - matched_precision（旧口径，仅诊断用）= accepted_correct /
       (accepted_correct + accepted_wrong + unknown_accept)
     - business_accepted_precision（发布判断口径）= accepted_correct /
       (accepted_correct + accepted_wrong + unknown_accept + fp_accepted)
  3. 输出写入 `.eval/e0_iou/` 与独立报告，绝不覆盖旧 E0 产物。
  4. detector conf 显式记录在报告阈值区。

用法：python -m src.eval.e0_strict_iou [--set dev_v2] [--limit 0] [--conf 0.18] [--iou-thr 0.5]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT
from ..training.build_dataset_v7 import UNREGISTERED_BOX_FRAC

PROTOCOL_DIR = PROJECT_ROOT / ".data_protocol"
CLEAN_MANIFEST = PROJECT_ROOT / ".batch3_clean" / "clean_manifest.json"
CLEAN_BLOBS = PROJECT_ROOT / ".batch3_clean" / "blobs"
EVAL_OUT = PROJECT_ROOT / ".eval" / "e0_iou"
REPORT_MD = PROJECT_ROOT / "docs" / "experiments" / "E0-strict-iou-baseline.md"


def _iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _gt_boxes(pid, anns, registry, W, H):
    """GT 像素框：锚点 ± SKU 比例盒的一半（与 build_dataset_v7 同一生成规则）。"""
    boxes = []
    for a in anns.get(pid, []):
        name = a["name"]
        from ..training.ingest_train import sku_box_frac
        wf, hf = sku_box_frac(name) if name in registry else UNREGISTERED_BOX_FRAC
        bw, bh = wf * W, hf * H
        x, y = float(a["x"]), float(a["y"])
        boxes.append((max(0.0, x - bw / 2), max(0.0, y - bh / 2),
                      min(W, x + bw / 2), min(H, y + bh / 2), name))
    return boxes


def evaluate(set_name: str = "dev_v2", limit: int = 0, conf: float = 0.18,
             iou_thr: float = 0.5) -> dict:
    proto = json.loads((PROTOCOL_DIR / f"{set_name}.json").read_text(encoding="utf-8"))
    clean = json.loads(CLEAN_MANIFEST.read_text(encoding="utf-8"))
    from ..training.build_sku_v6_dataset import parse_batch3_annotations
    anns = parse_batch3_annotations()
    registry = json.loads((PROJECT_ROOT / "data" / "sku_registry.json").read_text(encoding="utf-8"))
    name_to_sku = {k: v["sku_id"] for k, v in registry.items()}

    from ..models import bundle as B
    from ..cascade.cascade_inference import CascadeRecognizer
    info = B.resolve_weights()  # verify=True，fail-closed
    kwargs = {}
    thr = info.get("threshold_values") or {}
    if isinstance(thr.get("conf"), (int, float)):
        kwargs["conf_thr"] = float(thr["conf"])
    if isinstance(thr.get("margin"), (int, float)):
        kwargs["margin_thr"] = float(thr["margin"])
    rec = CascadeRecognizer(yolo_weight=info["detector"], clf_weight=info["classifier"],
                            registry=info.get("registry") and json.loads(
                                Path(info["registry"]).read_text(encoding="utf-8")) or None,
                            **kwargs)
    thr_src = info.get("threshold_source") or {"conf": "code_default", "margin": "code_default"}

    photo_ids = proto["photo_ids"]
    if limit > 0:
        photo_ids = photo_ids[:limit]

    agg = Counter()
    err = Counter()
    details = []
    t0 = time.time()
    from PIL import Image
    for i, pid in enumerate(photo_ids):
        recd = clean.get(pid)
        blob = CLEAN_BLOBS / recd["sha256"][:2] / recd["sha256"] if recd else None
        if not blob or not blob.exists():
            agg["photo_missing"] += 1
            continue
        with Image.open(blob) as im:
            W, H = im.size
        gts = _gt_boxes(pid, anns, registry, W, H)
        preds = rec.recognize(blob.read_bytes(), conf=conf)

        # 严格 one-to-one IoU 匹配：候选对按 IoU 降序贪心，IoU ≥ iou_thr
        pairs = []
        for pi, pr in enumerate(preds):
            for gi, g in enumerate(gts):
                v = _iou(pr["box"], g[:4])
                if v >= iou_thr:
                    pairs.append((v, pi, gi))
        pairs.sort(reverse=True)
        used_p, used_g = set(), set()
        matched, fp = [], []
        # 同 IoU 时按 classifier_conf 优先（稳定排序）
        order = sorted(range(len(preds)), key=lambda k: -preds[k].get("classifier_conf", 0))
        conf_rank = {k: r for r, k in enumerate(order)}
        pairs.sort(key=lambda t: (-t[0], conf_rank.get(t[1], 10 ** 9)))
        for v, pi, gi in pairs:
            if pi in used_p or gi in used_g:
                continue
            used_p.add(pi)
            used_g.add(gi)
            matched.append((preds[pi], gi, round(v, 4)))
        fp = [pr for pi, pr in enumerate(preds) if pi not in used_p]

        n_accepted_correct = n_accepted_wrong = n_unknown_accept = 0
        n_review = 0
        for pr, gi, _v in matched:
            gt_sku = name_to_sku.get(gts[gi][4])
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
        gts_left = [gi for gi in range(len(gts)) if gi not in used_g]
        for _gi in gts_left:
            err["missed_detection"] += 1
        fp_accepted = 0
        for pr in fp:
            if pr["status"] == "accepted":
                err["fp_accepted"] += 1
                fp_accepted += 1
            else:
                err["fp_review"] += 1

        agg["photos"] += 1
        agg["gt_total"] += len(gts)
        agg["gt_covered"] += len(matched)
        agg["accepted_correct"] += n_accepted_correct
        agg["accepted_wrong"] += n_accepted_wrong
        agg["unknown_accept"] += n_unknown_accept
        agg["fp_accepted"] += fp_accepted
        agg["review_matched"] += n_review
        agg["missed"] += len(gts_left)
        agg["fp"] += len(fp)
        agg["n_accepted"] += sum(1 for pr in preds if pr["status"] == "accepted")
        exact = (len(gts_left) == 0 and n_accepted_wrong == 0 and n_unknown_accept == 0
                 and len(matched) == len(gts) and not any(p["status"] == "accepted" for p in fp))
        agg["photo_exact"] += int(exact)
        agg["count_ae"] += abs(sum(1 for pr in preds if pr["status"] == "accepted") - len(gts))
        details.append({"pid": pid, "n_gt": len(gts), "n_pred": len(preds),
                        "matched": len(matched), "accepted_correct": n_accepted_correct,
                        "accepted_wrong": n_accepted_wrong, "review": n_review,
                        "fp": len(fp), "missed": len(gts_left), "exact": exact})
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(photo_ids)}  耗时 {time.time() - t0:.0f}s", flush=True)

    p = agg["photos"] or 1
    cov = agg["gt_covered"] / max(1, agg["gt_total"])
    matched_den = agg["accepted_correct"] + agg["accepted_wrong"] + agg["unknown_accept"]
    biz_den = matched_den + agg["fp_accepted"]
    metrics = {
        "set": set_name, "bundle": info["bundle_id"],
        "matching": f"strict_one_to_one_iou>= {iou_thr}",
        "detector_conf": conf,
        "thresholds": {"conf": rec.conf_thr, "margin": rec.margin_thr, "source": thr_src},
        "n_photos": p, "elapsed_sec": round(time.time() - t0, 1),
        "detection_coverage_iou": round(cov, 4),
        "matched_precision_old_caliber": round(agg["accepted_correct"] / matched_den, 4) if matched_den else None,
        "business_accepted_precision": round(agg["accepted_correct"] / biz_den, 4) if biz_den else None,
        "end_to_end_recall": round(agg["accepted_correct"] / max(1, agg["gt_total"]), 4),
        "review_rate_matched": round(agg["review_matched"] / max(1, agg["gt_covered"]), 4),
        "fp_per_photo": round(agg["fp"] / p, 3),
        "photo_exact_set_accuracy": round(agg["photo_exact"] / p, 4),
        "count_mae": round(agg["count_ae"] / p, 3),
        "counts": {k: int(v) for k, v in agg.items()},
        "error_ledger": dict(err),
    }
    EVAL_OUT.mkdir(parents=True, exist_ok=True)
    (EVAL_OUT / f"{set_name}_details.json").write_text(
        json.dumps({"metrics": metrics, "details": details}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return metrics


def write_report(m: dict) -> None:
    import subprocess
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                            text=True, cwd=PROJECT_ROOT).stdout.strip() or "(未提交)"
    e = m["error_ledger"]
    md = f"""# E0 严格 IoU 基线（{m['set']}，G5 口径纠正版）

- experiment_id: E0-strict-iou-baseline
- bundle: `{m['bundle']}`
- code_commit: `{commit}`
- 评估集: `.data_protocol/{m['set']}.json`（n={m['n_photos']}）
- 匹配口径: 严格 one-to-one IoU ≥ 0.5（GT 框 = 锚点 + SKU 比例盒，与训练标签同一生成规则）
- detector conf: {m['detector_conf']}
- 阈值: conf={m['thresholds']['conf']} / margin={m['thresholds']['margin']}（来源: {m['thresholds']['source']}）
- 耗时: {m['elapsed_sec']}s

## 指标（G5 口径）

| 指标 | 值 |
|---|---:|
| 检测覆盖（IoU≥0.5 匹配） | {m['detection_coverage_iou']:.1%} |
| business accepted precision（含 FP） | **{m['business_accepted_precision']:.1%}** |
| matched precision（旧口径，仅诊断） | {m['matched_precision_old_caliber']:.1%} |
| 端到端召回（accepted 且正确 / GT） | {m['end_to_end_recall']:.1%} |
| FP / 照片 | {m['fp_per_photo']} |
| 照片全对率（exact-set） | {m['photo_exact_set_accuracy']:.1%} |
| count MAE | {m['count_mae']} |

## 错误账本

{json.dumps(e, ensure_ascii=False, indent=2)}

## 口径说明（G5）

business accepted precision 分母 = accepted_correct + accepted_wrong +
unknown_false_accept + **fp_accepted**（旧口径漏掉 fp_accepted，会高估发布就绪度）。
本报告不覆盖旧 E0 产物，两份并存供对照。
"""
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(md, encoding="utf-8")
    print(f"报告已写入: {REPORT_MD}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="dev_v2")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--conf", type=float, default=0.18)
    ap.add_argument("--iou-thr", type=float, default=0.5)
    a = ap.parse_args()
    metrics = evaluate(a.set, a.limit, a.conf, a.iou_thr)
    write_report(metrics)
