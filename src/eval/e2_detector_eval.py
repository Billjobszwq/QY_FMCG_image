"""E2 detector 严格评估（Phase C/D 指标口径，G5 实现）。

在给定数据集上以严格 one-to-one IoU 匹配评估 detector 权重：
  - PR 曲线数据（conf 扫描）：recall@固定FP/image、FP/image、precision
  - 指定 conf 下的检测覆盖、召回、FP/image
  - 吞吐与延迟：photos/s、p50/p95 单图推理延迟

GT 直接来自数据集 labels/<split>（YOLO 归一化坐标），pred 来自权重
在 images/<split> 上的推理（conf 低阈值扫描 + 单独 conf 定点）。

输出写入 .eval/e2/<tag>/，不覆盖任何历史评估。

用法：
  python -m src.eval.e2_detector_eval --weight .models/e2_p0_coco_s42/weights/best.pt \
      --data-yaml .datasets/e2_product_pilot_v1/data.yaml --tag e2_p0_coco_s42 \
      [--split val] [--imgsz 960] [--fixed-fp 3.0] [--conf 0.25] [--limit 0]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image

from ..common.config import PROJECT_ROOT

EVAL_OUT = PROJECT_ROOT / ".eval" / "e2"


def _load_protocol(set_name: str, limit: int):
    """协议集评估：图片来自 batch3 blobs，GT 为锚点+SKU 比例合成盒
    （与训练标签同源；dev_v2 无真实框，在报告中披露）。返回
    [(img_path, boxes_xyxy)] 元组列表，与 split 模式对齐。"""
    import json
    proto = json.loads((PROJECT_ROOT / ".data_protocol" / f"{set_name}.json").read_text(encoding="utf-8"))
    clean = json.loads((PROJECT_ROOT / ".batch3_clean" / "clean_manifest.json").read_text(encoding="utf-8"))
    blobs = PROJECT_ROOT / ".batch3_clean" / "blobs"
    registry = json.loads((PROJECT_ROOT / "data" / "sku_registry.json").read_text(encoding="utf-8"))
    from ..training.build_sku_v6_dataset import parse_batch3_annotations
    from ..training.build_dataset_v7 import UNREGISTERED_BOX_FRAC
    from ..training.ingest_train import sku_box_frac
    anns = parse_batch3_annotations()
    out = []
    for pid in proto["photo_ids"]:
        if limit > 0 and len(out) >= limit:
            break
        recd = clean.get(pid)
        blob = blobs / recd["sha256"][:2] / recd["sha256"] if recd else None
        if not blob or not blob.exists() or not anns.get(pid):
            continue
        with Image.open(blob) as im:
            W, H = im.size
        boxes = []
        for a in anns[pid]:
            wf, hf = sku_box_frac(a["name"]) if a["name"] in registry else UNREGISTERED_BOX_FRAC
            bw, bh = wf * W, hf * H
            x, y = float(a["x"]), float(a["y"])
            boxes.append((max(0.0, x - bw / 2), max(0.0, y - bh / 2),
                          min(W, x + bw / 2), min(H, y + bh / 2), 0))
        out.append((blob, boxes))
    return out


def _load_split(data_yaml: str, split: str):
    import yaml
    cfg = yaml.safe_load(Path(data_yaml).read_text(encoding="utf-8"))
    base = Path(cfg.get("path", Path(data_yaml).parent))
    if not base.is_absolute():
        base = (Path(data_yaml).parent / base).resolve()
    img_dir = (base / cfg.get(split, f"images/{split}"))
    lbl_dir = base / "labels" / split
    pairs = []
    for f in sorted(img_dir.iterdir()):
        if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp"):
            lf = lbl_dir / (f.stem + ".txt")
            if lf.exists():
                pairs.append((f, lf))
    return pairs


def _boxes_xyxy(px: list, W: int, H: int):
    out = []
    for (c, cx, cy, w, h) in px:
        x1, y1 = (cx - w / 2) * W, (cy - h / 2) * H
        x2, y2 = (cx + w / 2) * W, (cy + h / 2) * H
        out.append((x1, y1, x2, y2, int(c)))
    return out


def _iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _match_one_to_one(preds, gts, iou_thr):
    """preds: [(conf, x1,y1,x2,y2)]，gts: [(x1,y1,x2,y2,c)]。
    贪心按 conf 降序，每个 pred 取 IoU 最大且未占用的 GT（IoU≥thr）。
    返回 (tp_list_conf_order, n_fp, n_missed)。"""
    tp = []
    used = set()
    for (conf, *pb) in sorted(preds, key=lambda t: -t[0]):
        best_gi, best_v = None, iou_thr
        for gi, g in enumerate(gts):
            if gi in used:
                continue
            v = _iou(pb, g[:4])
            if v > best_v:
                best_v, best_gi = v, gi
        if best_gi is None:
            tp.append((conf, 0))
        else:
            used.add(best_gi)
            tp.append((conf, 1))
    n_fp = sum(1 for _, ok in tp if not ok)
    return tp, n_fp, len(gts) - len(used)


def evaluate(weight: str, data_yaml: str, tag: str, split: str = "val",
             imgsz: int = 960, fixed_fp: float = 3.0, conf: float = 0.25,
             iou_thr: float = 0.5, limit: int = 0,
             protocol_set: str | None = None) -> dict:
    from ultralytics import YOLO
    if protocol_set:
        pairs = _load_protocol(protocol_set, limit)
    else:
        pairs = _load_split(data_yaml, split)
        if limit > 0:
            pairs = pairs[:limit]
    model = YOLO(weight)
    # 低 conf 全量预测一次，得到 (conf, box) 列表，用于 PR 扫描与定点指标
    all_preds, all_gts, latencies = [], [], []
    t0 = time.time()
    for i, (img, gt) in enumerate(pairs):
        if protocol_set:
            gts = list(gt)  # 已是像素 xyxy 框
        else:
            lbl = gt
            with Image.open(img) as im:
                W, H = im.size
            gts = _boxes_xyxy([[float(v) for v in ln.split()] for ln in
                               lbl.read_text(encoding="utf-8").strip().splitlines() if ln.strip()], W, H)
        ts = time.time()
        if protocol_set:
            # blob 无图片扩展名，Ultralytics 拒绝路径；读成 numpy 数组推理
            import numpy as np
            with Image.open(img) as im:
                arr = np.asarray(im.convert("RGB"))
            src = arr
        else:
            src = str(img)
        r = model.predict(src, imgsz=imgsz, conf=0.001, iou=0.7,
                          device="mps", verbose=False)
        latencies.append(time.time() - ts)
        preds = []
        if r and r[0].boxes is not None:
            b = r[0].boxes
            for bi in range(len(b)):
                x1, y1, x2, y2 = b.xyxy[bi].tolist()
                preds.append((float(b.conf[bi]), x1, y1, x2, y2))
        all_preds.append(preds)
        all_gts.append(gts)
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(pairs)} 耗时 {time.time() - t0:.0f}s", flush=True)
    elapsed = time.time() - t0

    n_photos = len(pairs)
    n_gt = sum(len(g) for g in all_gts)

    # 1) PR 扫描：conf 阈值从高到低，严格 one-to-one
    conf_fixed = float(conf)  # 定点阈值（避免被循环变量遮蔽）
    events = []  # (conf, is_tp)
    for preds, gts in zip(all_preds, all_gts):
        tp_list, _, _ = _match_one_to_one(preds, gts, iou_thr)
        events.extend(tp_list)
    events.sort(key=lambda t: -t[0])
    pr_points, cum_tp, cum_det = [], 0, 0
    for ev_conf, ok in events:
        cum_det += 1
        cum_tp += ok
        pr_points.append({"conf": round(ev_conf, 4), "cum_det": cum_det, "cum_tp": cum_tp,
                          "precision": round(cum_tp / cum_det, 4),
                          "recall": round(cum_tp / n_gt, 4) if n_gt else 0.0,
                          "fp_per_photo": round((cum_det - cum_tp) / n_photos, 4)})

    # recall @ fixed FP/image（线性插值）
    recall_at_fixed_fp = None
    for i in range(len(pr_points)):
        if pr_points[i]["fp_per_photo"] >= fixed_fp:
            if i == 0:
                recall_at_fixed_fp = pr_points[0]["recall"]
            else:
                a, b = pr_points[i - 1], pr_points[i]
                w = (fixed_fp - a["fp_per_photo"]) / max(1e-9, b["fp_per_photo"] - a["fp_per_photo"])
                recall_at_fixed_fp = round(a["recall"] + w * (b["recall"] - a["recall"]), 4)
            break
    if recall_at_fixed_fp is None:
        recall_at_fixed_fp = pr_points[-1]["recall"] if pr_points else 0.0

    # 2) 定点 conf 指标（conf 为 CLI 传入的定点阈值，与 PR 扫描事件无关）
    fixed = {"conf": conf_fixed, "det": 0, "tp": 0, "missed": 0}
    for preds, gts in zip(all_preds, all_gts):
        kept = [p for p in preds if p[0] >= conf_fixed]
        tp_list, n_fp, missed = _match_one_to_one(kept, gts, iou_thr)
        fixed["det"] += len(kept)
        fixed["tp"] += sum(ok for _, ok in tp_list)
        fixed["missed"] += missed
    fixed["precision"] = round(fixed["tp"] / fixed["det"], 4) if fixed["det"] else None
    fixed["recall"] = round(fixed["tp"] / n_gt, 4) if n_gt else None
    fixed["fp_per_photo"] = round((fixed["det"] - fixed["tp"]) / n_photos, 3)

    lat = sorted(latencies)
    metrics = {
        "tag": tag, "weight": weight, "data_yaml": data_yaml, "split": split,
        "protocol_set": protocol_set,
        "imgsz": imgsz, "iou_thr": iou_thr, "matching": "strict_one_to_one",
        "n_photos": n_photos, "n_gt": n_gt, "elapsed_sec": round(elapsed, 1),
        "throughput_photos_per_s": round(n_photos / elapsed, 3),
        "latency_p50_s": round(lat[len(lat) // 2], 4),
        "latency_p95_s": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 4),
        "recall_at_fixed_fp": {"fp_per_photo": fixed_fp, "recall": recall_at_fixed_fp},
        "fixed_conf": fixed,
        "pr_points": pr_points[::max(1, len(pr_points) // 200)],  # 降采样存档
    }
    out_dir = EVAL_OUT / tag
    if (out_dir / "metrics.json").exists():
        raise RuntimeError(f"评估已存在，拒绝覆盖: {out_dir}（换 --tag）")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in metrics.items() if k != "pr_points"},
                     ensure_ascii=False, indent=2))
    return metrics


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--weight", required=True)
    ap.add_argument("--data-yaml", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--split", default="val")
    ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument("--fixed-fp", type=float, default=3.0)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--iou-thr", type=float, default=0.5)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--protocol-set", default=None,
                    help="在协议集（如 dev_v2）上评估：锚点合成盒 GT，与训练标签同源")
    a = ap.parse_args()
    evaluate(a.weight, a.data_yaml, a.tag, a.split, a.imgsz, a.fixed_fp,
             a.conf, a.iou_thr, a.limit, a.protocol_set)
