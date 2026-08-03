"""构建分类器裁剪数据集 crop_dataset。

流程：
  1. 读取第二批混合数据集的 GT（点标注 + SKU 名称），点→框（sku_box_frac，与检测一致）
  2. 按坐标从原始大图裁剪目标小图（**防越界**：框超出图片边界强制 clamp 到 [0,W]/[0,H]）
  3. 等比缩放至 224x224（长边缩到 224，短边居中填充空白，**严禁拉伸畸变**）
  4. 按照片 ID 8:2 切分 train/val（同一照片的裁剪不跨集，防泄露）
  5. 输出 ./crop_dataset/{train,val}/<sku_id>/*.jpg 标准分类目录
  6. 统计各类样本数，标记 <50 张的少数类（供训练时过采样）

用法：python -m src.cascade.build_crop_dataset [--size 224] [--val-ratio 0.2]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT
from ..data import gold_holdout as gold
from ..training.ingest_train import sku_box_frac

B2_MANIFEST = PROJECT_ROOT / ".eval" / "batch2" / "manifest.json"
BLOBS = PROJECT_ROOT / ".training_data" / "blobs"
REGISTRY = PROJECT_ROOT / "data" / "sku_registry.json"
OUT_DIR = PROJECT_ROOT / "crop_dataset"
PAD_COLOR = (114, 114, 114)  # 填充灰（YOLO 惯例，避免引入纯色背景偏置）


def resize_keep_ratio(img: Image.Image, size: int = 224) -> Image.Image:
    """等比缩放：长边缩到 size，短边居中填充至 size×size（不拉伸）。"""
    w, h = img.size
    scale = size / max(w, h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    img = img.resize((nw, nh), Image.BILINEAR)
    canvas = Image.new("RGB", (size, size), PAD_COLOR)
    canvas.paste(img, ((size - nw) // 2, (size - nh) // 2))
    return canvas


def crop_with_boundary(img: Image.Image, box, W, H) -> Image.Image | None:
    """按框裁剪，防越界：坐标 clamp 到图片边界。返回裁剪小图（太小则返回 None）。"""
    x1, y1, x2, y2 = box
    x1 = max(0, min(int(x1), W - 1))
    y1 = max(0, min(int(y1), H - 1))
    x2 = max(0, min(int(x2), W))
    y2 = max(0, min(int(y2), H))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    return img.crop((x1, y1, x2, y2))


def build(size: int = 224, val_ratio: float = 0.2, seed: int = 42):
    manifest = json.loads(B2_MANIFEST.read_text(encoding="utf-8"))
    photos = manifest["photos"]
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    # RA-002：gold holdout 照片永不进训练裁剪
    gold_ids = gold.gold_photo_ids()
    if gold_ids:
        before = len(photos)
        photos = {k: v for k, v in photos.items() if str(k) not in gold_ids}
        print(f"[GT裁剪] RA-002: 已排除 gold holdout 照片 {before - len(photos)} 张")

    # 按照片 ID 切分 train/val（防泄露：同照片裁剪不跨集）
    rng = random.Random(seed)
    photo_ids = list(photos.keys())
    rng.shuffle(photo_ids)
    n_val = max(1, int(len(photo_ids) * val_ratio))
    val_photo_ids = set(photo_ids[:n_val])

    # 创建目录
    for split in ("train", "val"):
        for info in registry.values():
            (OUT_DIR / split / info["sku_id"]).mkdir(parents=True, exist_ok=True)

    stats = {"train": 0, "val": 0, "skipped_small": 0, "skipped_noreg": 0, "skipped_noimg": 0}
    class_count = {info["sku_id"]: {"train": 0, "val": 0} for info in registry.values()}

    for pid, p in photos.items():
        img_info = p.get("image", {})
        sha = img_info.get("sha256")
        W = img_info.get("width") or 1500
        H = img_info.get("height") or 2000
        if not sha:
            continue
        bp = BLOBS / sha[:2] / sha
        if not bp.exists():
            stats["skipped_noimg"] += len(p.get("annotations", []))
            continue
        try:
            img = Image.open(bp).convert("RGB")
            W, H = img.size  # 用真实尺寸
        except Exception:
            stats["skipped_noimg"] += len(p.get("annotations", []))
            continue

        split = "val" if pid in val_photo_ids else "train"
        for ann in p.get("annotations", []):
            name = ann.get("name")
            reg_entry = registry.get(name)
            if reg_entry is None or ann.get("x") is None:
                stats["skipped_noreg"] += 1
                continue
            sku_id = reg_entry["sku_id"]
            # 点→框（与检测训练一致）
            wf, hf = sku_box_frac(name)
            bw, bh = wf * W, hf * H
            x, y = ann["x"], ann["y"]
            box = [x - bw/2, y - bh/2, x + bw/2, y + bh/2]
            crop = crop_with_boundary(img, box, W, H)
            if crop is None:
                stats["skipped_small"] += 1
                continue
            out_img = resize_keep_ratio(crop, size)
            # 文件名唯一：照片ID_坐标
            fn = f"{pid}_{int(x)}_{int(y)}.jpg"
            out_img.save(OUT_DIR / split / sku_id / fn, "JPEG", quality=92)
            stats[split] += 1
            class_count[sku_id][split] += 1

    # 统计少数类（<50 张训练样本）
    minority = {sid: c["train"] for sid, c in class_count.items() if c["train"] < 50}
    summary = {
        "size": size, "val_ratio": val_ratio,
        "train_crops": stats["train"], "val_crops": stats["val"],
        "skipped_small": stats["skipped_small"], "skipped_noreg": stats["skipped_noreg"],
        "skipped_noimg": stats["skipped_noimg"],
        "n_classes": len(registry),
        "minority_classes_lt50": len(minority),
        "class_count": class_count,
    }
    (OUT_DIR / "dataset_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    # 类别→索引映射（训练用）
    idx_map = {info["sku_id"]: info["class_id"] for info in registry.values()}
    (OUT_DIR / "class_index.json").write_text(json.dumps(idx_map, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== crop_dataset 构建完成 ===")
    print(f"  训练裁剪: {stats['train']} | 验证裁剪: {stats['val']}")
    print(f"  类别数: {len(registry)} | 少数类(<50训练样本): {len(minority)} 个")
    print(f"  跳过: 太小 {stats['skipped_small']} | 无注册 {stats['skipped_noreg']} | 无图 {stats['skipped_noimg']}")
    print(f"  输出: {OUT_DIR}/{{train,val}}/<sku_id>/")
    if minority:
        print(f"  少数类示例(前10): {list(minority.items())[:10]}")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=224)
    ap.add_argument("--val-ratio", type=float, default=0.2)
    a = ap.parse_args()
    build(a.size, a.val_ratio)
