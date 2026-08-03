"""用 YOLO 预测框重新裁剪分类数据（修复 train-test 抠图不匹配）。

背景：分类器此前在 GT 启发式框（sku_box_frac）裁剪上训练，但推理时收到的是
YOLO 预测框裁剪，二者尺寸/构图不同，导致级联分类准确从 92.9% 掉到 60%。
本脚本用 YOLO 实际预测框裁剪（**标签取框内匹配到的 GT 真实 SKU**），
让分类器在微调时见到与推理一致的抠图。

流程：
  1. 对训练照片跑 YOLO v4（conf=0.15）得预测框（gold holdout 照片强制排除，RA-002）
  2. 每个预测框匹配框内 GT 点 → 取该 GT 的 SKU 名作标签（多 GT 取最靠近框中心者）
  3. 裁剪预测框 → 等比缩放 224x224 → 存 crop_dataset_yolo/{train,val}/<sku_id>/
  4. 按照片 ID 沿用与 crop_dataset 相同的 8:2 切分（seed 42），保证可比

RA-009/RA-011：未匹配框与未注册标签不再丢弃：
  - GT 名未注册（other/百事other 等）→ 裁剪进 __unknown__ 负样本类
  - 无任何 GT 的预测框 → 按 --unknown-ratio 抽样进 __unknown__（线上误检分布）
  __unknown__ 与正式 SKU 严格隔离，供拒识/OOD 训练，不混入闭集分类。

用法：python -m src.cascade.build_yolo_crop_dataset [--conf 0.15] [--size 224] [--limit N]
        [--unknown-ratio 0.3]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
import uuid
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT
from ..data import gold_holdout as gold
from .build_crop_dataset import resize_keep_ratio

B2_MANIFEST = PROJECT_ROOT / ".eval" / "batch2" / "manifest.json"
BLOBS = PROJECT_ROOT / ".training_data" / "blobs"
REGISTRY = PROJECT_ROOT / "data" / "sku_registry.json"
YOLO_WEIGHT = PROJECT_ROOT / ".models" / "sku_v4" / "weights" / "best.pt"
OUT_DIR = PROJECT_ROOT / "crop_dataset_yolo"
UNKNOWN_CLASS = "__unknown__"  # RA-009/011：未注册/未匹配负样本类，与正式 SKU 严格隔离
# ISSUE-013：每次在 staging 全新构建，校验通过后原子切换，旧版本归档不删除
STAGING_ROOT = PROJECT_ROOT / ".datasets" / "staging"
ARCHIVE_ROOT = PROJECT_ROOT / ".datasets" / "archive"


def match_gt_in_box(box, annotations):
    """返回框内 GT 点中最靠近框中心的标注；无则 None。"""
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    best, best_d = None, float("inf")
    for ann in annotations:
        gx, gy, gname = ann.get("x"), ann.get("y"), ann.get("name")
        if gx is None or gy is None or not gname:
            continue
        if x1 <= gx <= x2 and y1 <= gy <= y2:
            d = (gx - cx) ** 2 + (gy - cy) ** 2
            if d < best_d:
                best_d, best = d, ann
    return best


def build(conf: float = 0.15, size: int = 224, limit: int | None = None,
          unknown_ratio: float = 0.3):
    from ultralytics import YOLO

    manifest = json.loads(B2_MANIFEST.read_text(encoding="utf-8"))
    photos = manifest["photos"]
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    # RA-002：gold holdout 照片永不进训练裁剪
    gold_ids = gold.gold_photo_ids()

    # ISSUE-013：全新 staging 目录，禁止写入旧版本目录
    dataset_id = f"crop_yolo_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    stage_dir = STAGING_ROOT / dataset_id
    print(f"[YOLO裁剪] staging 构建: {stage_dir}")

    # 与 crop_dataset 相同的照片切分（seed 42, val 20%）
    rng = random.Random(42)
    photo_ids = list(photos.keys())
    rng.shuffle(photo_ids)
    n_val = max(1, int(len(photo_ids) * 0.2))
    val_photo_ids = set(photo_ids[:n_val])

    for split in ("train", "val"):
        for info in registry.values():
            (stage_dir / split / info["sku_id"]).mkdir(parents=True, exist_ok=True)
        (stage_dir / split / UNKNOWN_CLASS).mkdir(parents=True, exist_ok=True)

    print(f"[YOLO裁剪] 加载画框器 {YOLO_WEIGHT.name}, conf={conf}")
    yolo = YOLO(str(YOLO_WEIGHT))

    keys = list(photos.keys())
    if limit:
        keys = keys[:limit]
    n_gold_skipped = sum(1 for k in keys if str(k) in gold_ids)
    keys = [k for k in keys if str(k) not in gold_ids]
    if gold_ids:
        print(f"[YOLO裁剪] RA-002: 已排除 gold holdout 照片 {n_gold_skipped} 张，参与构建 {len(keys)} 张")

    stats = {"train": 0, "val": 0, "boxes": 0, "matched": 0, "noimg": 0,
             "unknown_unregistered": 0, "unknown_unmatched": 0}
    class_count = {info["sku_id"]: {"train": 0, "val": 0} for info in registry.values()}
    class_count[UNKNOWN_CLASS] = {"train": 0, "val": 0}
    unk_rng = random.Random(1234)  # 未匹配框抽样独立固定种子，构建可复现
    # ISSUE-013：记录各 split 的照片 ID，构建后校验 train/val 隔离
    split_photo_ids = {"train": set(), "val": set()}
    t0 = time.time()

    for i, pid in enumerate(keys):
        p = photos[pid]
        img_info = p.get("image", {})
        sha = img_info.get("sha256")
        if not sha:
            continue
        bp = BLOBS / sha[:2] / sha
        if not bp.exists():
            stats["noimg"] += 1
            continue
        try:
            img = Image.open(bp).convert("RGB")
        except Exception:
            stats["noimg"] += 1
            continue
        W, H = img.size
        arr = np.array(img)
        # YOLO 预测框
        rs = yolo.predict(arr, conf=conf, imgsz=960, verbose=False, device="mps")
        split = "val" if pid in val_photo_ids else "train"
        split_photo_ids[split].add(str(pid))
        anns = p.get("annotations", [])
        box_idx = 0
        for r in rs:
            if r.boxes is None:
                continue
            for box in r.boxes.xyxy.tolist():
                box_idx += 1
                stats["boxes"] += 1
                gt = match_gt_in_box(box, anns)
                if gt is None:
                    # RA-011：未匹配提议按抽样比例进 __unknown__（线上误检分布）
                    if unknown_ratio > 0 and unk_rng.random() < unknown_ratio:
                        sku_id = UNKNOWN_CLASS
                        stats["unknown_unmatched"] += 1
                    else:
                        continue
                else:
                    reg_entry = registry.get(gt["name"])
                    if reg_entry is None:
                        # RA-009：未注册标签（other 等）转 __unknown__，不再丢弃
                        sku_id = UNKNOWN_CLASS
                        stats["unknown_unregistered"] += 1
                    else:
                        stats["matched"] += 1
                        sku_id = reg_entry["sku_id"]
                x1, y1, x2, y2 = box
                x1, y1 = max(0, int(x1)), max(0, int(y1))
                x2, y2 = min(W, int(x2)), min(H, int(y2))
                if x2 - x1 < 4 or y2 - y1 < 4:
                    continue
                crop = img.crop((x1, y1, x2, y2))
                out_img = resize_keep_ratio(crop, size)
                # ISSUE-013：文件名含框序号 + 完整坐标哈希，彻底消除碰撞
                box_hash = hashlib.sha256(
                    f"{pid}|{box_idx}|{x1},{y1},{x2},{y2}".encode()).hexdigest()[:10]
                fn = f"{pid}_{box_idx}_{box_hash}.jpg"
                out_img.save(stage_dir / split / sku_id / fn, "JPEG", quality=92)
                stats[split] += 1
                class_count[sku_id][split] += 1
        if (i + 1) % 200 == 0 or i == len(keys) - 1:
            print(f"  进度 {i+1}/{len(keys)} | 框{stats['boxes']} 匹配{stats['matched']} "
                  f"train{stats['train']} val{stats['val']} | {time.time()-t0:.0f}s", flush=True)

    # ISSUE-013：构建后磁盘核对 —— 汇总数/每类数/train-val 隔离
    disk = {"train": 0, "val": 0}
    disk_class = {sid: {"train": 0, "val": 0} for sid in class_count}
    disk_pids = {"train": set(), "val": set()}
    for split in ("train", "val"):
        for sid_dir in (stage_dir / split).iterdir():
            if not sid_dir.is_dir():
                continue
            files = [f for f in sid_dir.iterdir() if f.suffix.lower() == ".jpg"]
            disk[split] += len(files)
            if sid_dir.name in disk_class:
                disk_class[sid_dir.name][split] = len(files)
            for f in files:
                disk_pids[split].add(f.stem.split("_")[0])
    problems = []
    for split in ("train", "val"):
        if disk[split] != stats[split]:
            problems.append(f"{split} 磁盘文件数 {disk[split]} != 计数 {stats[split]}")
    for sid, cc in class_count.items():
        for split in ("train", "val"):
            if disk_class.get(sid, {}).get(split, 0) != cc[split]:
                problems.append(f"类别 {sid}/{split} 磁盘 {disk_class.get(sid, {}).get(split, 0)} != 计数 {cc[split]}")
    leak = disk_pids["train"] & split_photo_ids["val"]
    leak |= disk_pids["val"] & split_photo_ids["train"]
    if leak:
        problems.append(f"train/val 照片隔离失败: {sorted(leak)[:5]}")
    if problems:
        raise RuntimeError("数据集校验失败，staging 保留不切换: " + "; ".join(problems[:10]))

    # ISSUE-013：校验通过 → 旧版本归档 → 原子切换 current
    if OUT_DIR.exists():
        ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
        archive_path = ARCHIVE_ROOT / f"crop_dataset_yolo_{time.strftime('%Y%m%d_%H%M%S')}"
        os.replace(OUT_DIR, archive_path)
        print(f"  旧版本已归档: {archive_path}")
    os.replace(stage_dir, OUT_DIR)

    minority = {sid: c["train"] for sid, c in class_count.items()
                if c["train"] < 50 and sid != UNKNOWN_CLASS}
    summary = {
        "dataset_id": dataset_id,
        "conf": conf, "size": size, "unknown_ratio": unknown_ratio,
        "train_crops": stats["train"], "val_crops": stats["val"],
        "total_boxes": stats["boxes"], "matched_boxes": stats["matched"],
        "unknown_unregistered": stats["unknown_unregistered"],
        "unknown_unmatched": stats["unknown_unmatched"],
        "gold_skipped": n_gold_skipped,
        "n_classes": len(registry), "minority_classes_lt50": len(minority),
        "disk_verified": True,
        "per_class": class_count,
    }
    (OUT_DIR / "dataset_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== crop_dataset_yolo 构建完成 ({time.time()-t0:.0f}s) ===")
    print(f"  dataset_id: {dataset_id}（磁盘核对通过）")
    print(f"  YOLO 框: {stats['boxes']} | 匹配GT: {stats['matched']}")
    print(f"  __unknown__ 负样本: 未注册{stats['unknown_unregistered']} + 未匹配抽样{stats['unknown_unmatched']} (RA-009/011)")
    print(f"  gold holdout 排除: {n_gold_skipped} 张 (RA-002)")
    print(f"  训练裁剪: {stats['train']} | 验证裁剪: {stats['val']}")
    print(f"  少数类(<50): {len(minority)} 个")
    print(f"  输出: {OUT_DIR}/{{train,val}}/<sku_id>/")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--conf", type=float, default=0.15)
    ap.add_argument("--size", type=int, default=224)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--unknown-ratio", type=float, default=0.3,
                    help="未匹配预测框抽样进 __unknown__ 的比例（0=关闭，RA-011）")
    a = ap.parse_args()
    build(a.conf, a.size, a.limit, a.unknown_ratio)
