"""第二批训练数据评估：基准推理 + GT 比对 + 差异报告 + 混淆矩阵。

流程（先评估诊断，后调优）：
  1. 入库第二批照片（复用已有 blob，仅下载新增）
  2. 用最佳模型 best.pt 批量推理
  3. 与 GT 逐一比对，输出：漏检/误检/分类错误列表 + 混淆矩阵 + 按类别错误统计
  4. 区分「交叉旧照片」与「新增照片」分别统计（防数据泄露诊断）

用法：
  python -m src.eval.batch2_eval ingest [--workers 12]      # 仅入库下载
  python -m src.eval.batch2_eval eval [--conf 0.18] [--limit N]  # 推理+比对+报告
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT
from ..training.ingest_train import parse_xlsx, download_batch, sku_box_frac

XLSX2 = PROJECT_ROOT / "第二批训练数据.xlsx"
B2_DIR = PROJECT_ROOT / ".eval" / "batch2"
BLOBS = PROJECT_ROOT / ".training_data" / "blobs"  # 复用第一批 blob 目录（内容寻址，自动去重）
REGISTRY = PROJECT_ROOT / "data" / "sku_registry.json"
OVERLAP_IDS = PROJECT_ROOT / ".eval" / "overlap_photo_ids.json"
BEST_WEIGHT = PROJECT_ROOT / ".models" / "sku_v3" / "weights" / "best.pt"


def ingest(workers: int = 12, skip_download: bool = False, limit: int | None = None):
    """入库第二批：解析 xlsx → 下载照片（复用 blob）→ 保存 manifest。"""
    B2_DIR.mkdir(parents=True, exist_ok=True)
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    photos = parse_xlsx(XLSX2)
    keys = list(photos.keys())
    if limit:
        keys = keys[:limit]
        photos = {k: photos[k] for k in keys}
    n_ann = sum(len(p["annotations"]) for p in photos.values())
    print(f"[入库] 第二批: {len(photos)} 照片, {n_ann} 标注, {len(registry)} SKU 注册表")

    filenames = sorted({p["filename"] for p in photos.values() if p["filename"]})
    prog = B2_DIR / "download_progress.json"
    if skip_download and prog.exists():
        dl_info = json.loads(prog.read_text(encoding="utf-8"))
        print(f"[入库] 跳过下载, 已有 {sum(1 for v in dl_info.values() if v.get('ok'))} 张")
    else:
        print(f"[入库] 下载 {len(filenames)} 张照片 (复用已有 blob, workers={workers})...")
        dl_info = download_batch(filenames, BLOBS, workers=workers)
        prog.write_text(json.dumps(dl_info, ensure_ascii=False), encoding="utf-8")
        ok = sum(1 for v in dl_info.values() if v.get("ok"))
        print(f"[入库] 完成: {ok} 成功, {len(filenames)-ok} 失败")

    manifest = {
        "photos": {pid: {**p, "image": dl_info.get(p["filename"], {})} for pid, p in photos.items()},
        "created_at": time.time(),
    }
    (B2_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"[入库] manifest 已保存: {B2_DIR/'manifest.json'}")
    return manifest


def _load_detector(weight: str):
    """加载指定 YOLO 权重 + SKU 映射。"""
    import numpy as np
    from PIL import Image
    from ultralytics import YOLO
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    id_to_name = {v["class_id"]: k for k, v in reg.items()}
    m = YOLO(weight)

    def detect(image_bytes, conf=0.18, imgsz=960):
        arr = np.array(Image.open(__import__("io").BytesIO(image_bytes)).convert("RGB"))
        rs = m.predict(arr, conf=conf, imgsz=imgsz, verbose=False, device="cpu")
        out = []
        for r in rs:
            if r.boxes is None:
                continue
            for box, cls, sc in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist()):
                cid = int(cls)
                out.append({"box": box, "name": id_to_name.get(cid, f"unknown_{cid}"),
                            "class_id": cid, "confidence": float(sc)})
        return out
    return detect


def _gt_box(ann, W, H):
    """GT 点 → 框（用 sku_box_frac，与训练一致）。"""
    wf, hf = sku_box_frac(ann.get("name"))
    bw, bh = wf * W, hf * H
    x, y = ann["x"], ann["y"]
    return [max(0, x - bw/2), max(0, y - bh/2), min(W, x + bw/2), min(H, y + bh/2)]


def _point_in_box(x, y, box):
    x1, y1, x2, y2 = box
    return x1 <= x <= x2 and y1 <= y <= y2


def evaluate(weight: str = None, conf: float = 0.18, imgsz: int = 960, limit: int | None = None):
    """推理 + GT 比对 + 差异报告 + 混淆矩阵。"""
    weight = weight or str(BEST_WEIGHT)
    manifest = json.loads((B2_DIR / "manifest.json").read_text(encoding="utf-8"))
    photos = manifest["photos"]
    overlap_ids = set(json.loads(OVERLAP_IDS.read_text(encoding="utf-8"))) if OVERLAP_IDS.exists() else set()

    keys = list(photos.keys())
    if limit:
        keys = keys[:limit]

    print(f"[评估] 加载模型: {weight}")
    detect = _load_detector(weight)

    # 统计容器
    missed, false_det, misclassified = [], [], []
    confusion = Counter()           # (gt_name, pred_name) -> count
    per_sku = defaultdict(lambda: {"gt": 0, "detected": 0, "correct": 0, "missed": 0, "misclassified": 0})
    # 分交叉/新增
    split_stat = {"overlap": {"gt": 0, "detected": 0, "correct": 0}, "new": {"gt": 0, "detected": 0, "correct": 0}}
    tot = {"gt": 0, "detected": 0, "correct": 0, "missed": 0, "false": 0, "misclassified": 0, "photos": 0}

    n = len(keys)
    t0 = time.time()
    for i, k in enumerate(keys):
        p = photos[k]
        img = p.get("image", {})
        sha = img.get("sha256")
        W = img.get("width") or 1500
        H = img.get("height") or 2000
        if not sha:
            continue
        bp = BLOBS / sha[:2] / sha
        if not bp.exists():
            continue
        img_bytes = bp.read_bytes()
        try:
            preds = detect(img_bytes, conf=conf, imgsz=imgsz)
        except Exception:
            preds = []
        tot["photos"] += 1
        is_overlap = k in overlap_ids
        sk = "overlap" if is_overlap else "new"
        pred_matched = [False] * len(preds)

        for ann in p["annotations"]:
            gx, gy, gname = ann["x"], ann["y"], ann.get("name")
            if gx is None or gy is None or not gname:
                continue
            tot["gt"] += 1
            split_stat[sk]["gt"] += 1
            per_sku[gname]["gt"] += 1
            covering = [(j, pr) for j, pr in enumerate(preds) if _point_in_box(gx, gy, pr["box"])]
            if not covering:
                tot["missed"] += 1
                per_sku[gname]["missed"] += 1
                missed.append({"photo": k, "sku": gname, "x": gx, "y": gy, "split": sk})
                continue
            tot["detected"] += 1
            split_stat[sk]["detected"] += 1
            per_sku[gname]["detected"] += 1
            bj, best = max(covering, key=lambda jp: jp[1]["confidence"])
            pred_matched[bj] = True
            pname = best["name"]
            if pname == gname:
                tot["correct"] += 1
                split_stat[sk]["correct"] += 1
                per_sku[gname]["correct"] += 1
            else:
                tot["misclassified"] += 1
                per_sku[gname]["misclassified"] += 1
                confusion[(gname, pname)] += 1
                misclassified.append({"photo": k, "gt": gname, "pred": pname, "conf": round(best["confidence"], 3), "split": sk})

        for j, matched in enumerate(pred_matched):
            if not matched:
                tot["false"] += 1
                false_det.append({"photo": k, "pred": preds[j]["name"], "conf": round(preds[j]["confidence"], 3), "split": sk})

        if (i + 1) % 100 == 0 or i == n - 1:
            print(f"  进度 {i+1}/{n} ({(i+1)/n*100:.0f}%) 已用 {time.time()-t0:.0f}s", flush=True)

    # 汇总
    def rate(a, b): return round(a / b, 4) if b else 0
    report = {
        "weight": weight, "conf": conf, "imgsz": imgsz,
        "photos_evaluated": tot["photos"],
        "total_gt": tot["gt"], "total_pred": len(false_det) + tot["detected"],
        "detection_recall": rate(tot["detected"], tot["gt"]),
        "classification_accuracy": rate(tot["correct"], tot["detected"]),
        "overall_accuracy": rate(tot["correct"], tot["gt"]),
        "precision": rate(tot["correct"], tot["correct"] + tot["false"]),
        "missed_count": tot["missed"], "false_count": tot["false"], "misclassified_count": tot["misclassified"],
        "split": {
            "overlap": {**split_stat["overlap"], "recall": rate(split_stat["overlap"]["detected"], split_stat["overlap"]["gt"]),
                        "cls_acc": rate(split_stat["overlap"]["correct"], split_stat["overlap"]["detected"])},
            "new": {**split_stat["new"], "recall": rate(split_stat["new"]["detected"], split_stat["new"]["gt"]),
                    "cls_acc": rate(split_stat["new"]["correct"], split_stat["new"]["detected"])},
        },
        "top_confusion": [{"gt": g, "pred": p, "count": c} for (g, p), c in confusion.most_common(40)],
        "per_sku": {k: {**v, "recall": rate(v["detected"], v["gt"]), "cls_acc": rate(v["correct"], v["detected"])}
                    for k, v in per_sku.items()},
    }
    # 保存（列表可能很大，截断保存摘要 + 完整列表）
    report["missed_list_sample"] = missed[:500]
    report["false_list_sample"] = false_det[:500]
    report["misclassified_list_sample"] = misclassified[:500]
    (B2_DIR / "diff_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # 完整混淆矩阵
    cm = {"confusion": [{"gt": g, "pred": p, "count": c} for (g, p), c in confusion.most_common()]}
    (B2_DIR / "confusion_matrix.json").write_text(json.dumps(cm, ensure_ascii=False, indent=2), encoding="utf-8")
    # 完整差异列表
    (B2_DIR / "diff_lists.json").write_text(json.dumps(
        {"missed": missed, "false": false_det, "misclassified": misclassified}, ensure_ascii=False), encoding="utf-8")

    _print_report(report)
    return report


def prep_train(val_ratio: float = 0.15, seed: int = 42):
    """构建去重训练集（防数据泄露）。

    去重策略：
      - 训练集：第二批全部照片（含与第一批交叉部分，按 photo_id 天然去重）
      - 验证集：**仅从新增照片**（不与第一批交叉）中抽样，确保验证集是
        任何前序训练都未见过的数据，从根本上防止新旧交叉导致的评估泄露。
    标签用 SKU 自适应框（sku_box_frac）。
    """
    import random
    from ..common import paths as _paths
    manifest = json.loads((B2_DIR / "manifest.json").read_text(encoding="utf-8"))
    photos = manifest["photos"]
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    overlap_ids = set(json.loads(OVERLAP_IDS.read_text(encoding="utf-8"))) if OVERLAP_IDS.exists() else set()

    # 新增照片（不与第一批交叉）→ 从中抽验证集
    new_ids = sorted([pid for pid in photos if pid not in overlap_ids])
    rng = random.Random(seed)
    rng.shuffle(new_ids)
    n_val = max(1, int(len(new_ids) * val_ratio))
    val_ids = set(new_ids[:n_val])
    train_ids = [pid for pid in photos if pid not in val_ids]

    out_dir = PROJECT_ROOT / ".datasets" / "batch2_v4"
    img_dir = out_dir / "images"
    lbl_dir = out_dir / "labels"
    for split in ("train", "val"):
        (img_dir / split).mkdir(parents=True, exist_ok=True)
        (lbl_dir / split).mkdir(parents=True, exist_ok=True)

    stats = {"train": 0, "val": 0, "labels": 0, "skipped": 0}
    for split, ids in [("train", train_ids), ("val", sorted(val_ids))]:
        for pid in ids:
            p = photos[pid]
            img = p.get("image", {})
            sha = img.get("sha256")
            W = img.get("width") or 1500
            H = img.get("height") or 2000
            if not sha:
                continue
            bp = BLOBS / sha[:2] / sha
            if not bp.exists():
                stats["skipped"] += 1
                continue
            ext = ".jpg" if bp.read_bytes()[:3] == b"\xff\xd8\xff" else ".png"
            link = img_dir / split / f"{pid}{ext}"
            if not link.exists():
                link.symlink_to(bp.resolve())
            lines = []
            for ann in p["annotations"]:
                reg_entry = registry.get(ann.get("name"))
                if reg_entry is None or ann.get("x") is None:
                    stats["skipped"] += 1
                    continue
                cls_id = reg_entry["class_id"]
                wf, hf = sku_box_frac(ann.get("name"))
                bw, bh = wf * W, hf * H
                x, y = ann["x"], ann["y"]
                x1, y1 = max(0, x - bw/2), max(0, y - bh/2)
                x2, y2 = min(W, x + bw/2), min(H, y + bh/2)
                xc, yc = (x1+x2)/2/W, (y1+y2)/2/H
                lines.append(f"{cls_id} {xc:.6f} {yc:.6f} {(x2-x1)/W:.6f} {(y2-y1)/H:.6f}")
            if lines:
                (lbl_dir / split / f"{pid}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
                stats[split] += 1
                stats["labels"] += len(lines)

    nc = len(registry)
    names = sorted(registry.keys(), key=lambda n: registry[n]["class_id"])
    yaml = f"path: {out_dir.resolve()}\ntrain: images/train\nval: images/val\nnc: {nc}\nnames: {json.dumps(names, ensure_ascii=False)}\n"
    _paths.safe_write_text(out_dir / "data.yaml", yaml)
    stats["data_yaml"] = str(out_dir / "data.yaml")
    stats["val_from_new_photos"] = len(val_ids)
    stats["overlap_in_train"] = sum(1 for pid in train_ids if pid in overlap_ids)
    print(f"[构建训练集] train={stats['train']} val={stats['val']} labels={stats['labels']}")
    print(f"  验证集来自新增照片: {stats['val_from_new_photos']} 张（防泄露）")
    print(f"  训练集中含交叉旧照片: {stats['overlap_in_train']} 张")
    print(f"  data.yaml: {out_dir/'data.yaml'}")
    return stats


def _print_report(r):
    print("\n" + "="*60)
    print("第二批数据基准评估报告（最佳模型 best.pt）")
    print("="*60)
    print(f"  模型: {Path(r['weight']).parent.parent.name}/best.pt | conf={r['conf']} imgsz={r['imgsz']}")
    print(f"  评估照片: {r['photos_evaluated']} | GT标注: {r['total_gt']}")
    print(f"  检测召回率: {r['detection_recall']*100:.1f}%  ({r['total_gt']-r['missed_count']}/{r['total_gt']})")
    print(f"  分类准确率: {r['classification_accuracy']*100:.1f}%  (检出中)")
    print(f"  精确率: {r['precision']*100:.1f}%  | 整体准确率: {r['overall_accuracy']*100:.1f}%")
    print(f"  漏检: {r['missed_count']} | 误检: {r['false_count']} | 分类错误: {r['misclassified_count']}")
    print(f"\n  【交叉旧照片】召回 {r['split']['overlap']['recall']*100:.1f}% | 分类 {r['split']['overlap']['cls_acc']*100:.1f}% (GT {r['split']['overlap']['gt']})")
    print(f"  【新增照片】  召回 {r['split']['new']['recall']*100:.1f}% | 分类 {r['split']['new']['cls_acc']*100:.1f}% (GT {r['split']['new']['gt']})")
    print(f"\n  Top 混淆（GT→误判）:")
    for c in r["top_confusion"][:12]:
        print(f"    {c['gt']}  →  {c['pred']}  ({c['count']}次)")
    print(f"\n  报告: {B2_DIR/'diff_report.json'}")
    print(f"  混淆矩阵: {B2_DIR/'confusion_matrix.json'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    pi = sub.add_parser("ingest")
    pi.add_argument("--workers", type=int, default=12)
    pi.add_argument("--skip-download", action="store_true")
    pi.add_argument("--limit", type=int, default=None)
    pe = sub.add_parser("eval")
    pe.add_argument("--weight", default=None)
    pe.add_argument("--conf", type=float, default=0.18)
    pe.add_argument("--imgsz", type=int, default=960)
    pe.add_argument("--limit", type=int, default=None)
    pt = sub.add_parser("prep-train")
    pt.add_argument("--val-ratio", type=float, default=0.15)
    a = ap.parse_args()
    if a.cmd == "ingest":
        ingest(a.workers, a.skip_download, a.limit)
    elif a.cmd == "eval":
        evaluate(a.weight, a.conf, a.imgsz, a.limit)
    elif a.cmd == "prep-train":
        prep_train(a.val_ratio)
    else:
        ap.print_help()
