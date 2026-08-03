"""第一批训练数据入库：解析 xlsx → 下载照片(并发/断点续传) → 点标注转 YOLO bbox → 生成数据集。

数据规模：2947 照片，84K 标注，208 SKU。
输出：.training_data/（manifest + blobs + yolo labels）
用法：python -m src.training.ingest_train [--workers 8] [--skip-download]"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import json
import time
from pathlib import Path

import httpx
import openpyxl
from PIL import Image

from ..common import hashing
from ..common.config import PROJECT_ROOT
from ..common.oss_urls import oss_url

XLSX = PROJECT_ROOT / "第一批训练数据.xlsx"
OUT_DIR = PROJECT_ROOT / ".training_data"
BLOBS = OUT_DIR / "blobs"
YOLO_LABELS = OUT_DIR / "labels"
YOLO_IMAGES = OUT_DIR / "images"
REGISTRY = PROJECT_ROOT / "data" / "sku_registry.json"

# 瓶身比例启发式（点→框）
BOX_W_FRAC = 0.07
BOX_H_FRAC = 0.18


def sku_box_frac(name: str) -> tuple[float, float]:
    """根据 SKU 名称推断商品外观比例（宽占图比, 高占图比）。

    不同包装形态尺寸差异很大（2L大瓶 vs 330ml罐），统一框尺寸会让模型
    学不会准确定位，是检测召回低的主因。这里按名称关键词区分形态。"""
    n = (name or "")
    # 罐装（矮胖/细长罐）
    if any(k in n for k in ["迷你罐", "迷你摩登"]):
        return (0.045, 0.10)   # 200ml 迷你罐，很小
    if "细长罐" in n:
        return (0.05, 0.16)    # 330ml 细长罐
    if any(k in n for k in ["拉罐", "摩登罐", "罐装", "罐", "can"]):
        return (0.06, 0.13)    # 330ml 标准罐，矮胖
    # 超大瓶
    if any(k in n for k in ["2L", "1.8L", "2000ml", "1800ml"]):
        return (0.11, 0.30)    # 2L 大瓶
    if any(k in n for k in ["1.5L", "1.25L", "1500ml", "1250ml"]):
        return (0.10, 0.27)    # 1.25-1.5L
    # 高瓶
    if any(k in n for k in ["1L", "1000ml", "900ml"]):
        return (0.085, 0.24)   # 900ml-1L 高瓶
    # 小瓶
    if any(k in n for k in ["350ml", "330ml", "300ml", "280ml"]):
        return (0.06, 0.15)    # 小瓶
    # 标准瓶（600/550/500/480/450/400ml）默认
    return (BOX_W_FRAC, BOX_H_FRAC)


def parse_xlsx(xlsx: Path = XLSX) -> dict:
    """解析 xlsx，按照片 ID 聚合标注。返回 {photo_id: {meta, filename, url, annotations}}。"""
    wb = openpyxl.load_workbook(str(xlsx), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(c).strip() if c else "" for c in rows[0]]
    idx = {name: i for i, name in enumerate(header)}
    wb.close()

    def g(r, k):
        return r[idx[k]] if k in idx and idx[k] < len(r) else None

    photos = collections.OrderedDict()
    for r in rows[1:]:
        pid = g(r, "ID")
        if pid is None:
            continue
        pid = str(int(pid)) if isinstance(pid, float) else str(pid)
        if pid not in photos:
            photos[pid] = {
                "id": pid,
                "filename": g(r, "TypeValue"),
                "url": g(r, "URL"),
                "meta": {
                    "scode": g(r, "SCode"),
                    "sname": g(r, "SName"),
                    "item": g(r, "ItemName"),
                    "typename": g(r, "TypeName"),
                    "createtime": str(g(r, "CreateTime")) if g(r, "CreateTime") else None,
                },
                "annotations": [],
            }
        name = g(r, "name")
        x, y = g(r, "x"), g(r, "y")
        if name and x is not None and y is not None:
            photos[pid]["annotations"].append({"x": float(x), "y": float(y), "name": str(name).strip()})
    return photos


def download_batch(filenames: list[str], blobs: Path, workers: int = 8) -> dict:
    """并发下载照片到 blobs（内容寻址），断点续传（已存在跳过）。"""
    blobs.mkdir(parents=True, exist_ok=True)
    results = {}

    def _dl(fn):
        url = oss_url(fn)
        try:
            with httpx.Client(follow_redirects=True, timeout=60.0, headers={"User-Agent": "Mozilla/5.0"}) as c:
                r = c.get(url)
                if r.status_code != 200 or not r.content:
                    return fn, {"ok": False, "err": f"http_{r.status_code}"}
                b = r.content
                h = hashing.sha256_bytes(b)
                bp = blobs / h[:2] / h
                if not bp.exists():
                    bp.parent.mkdir(parents=True, exist_ok=True)
                    bp.write_bytes(b)
                with Image.open(bp) as im:
                    w, ht = im.size
                return fn, {"ok": True, "sha256": h, "width": w, "height": ht}
        except Exception as e:
            return fn, {"ok": False, "err": f"{type(e).__name__}:{str(e)[:100]}"}

    # 先检查已下载的（断点续传）
    progress_file = OUT_DIR / "download_progress.json"
    if progress_file.exists():
        results = json.loads(progress_file.read_text(encoding="utf-8"))

    todo = [fn for fn in filenames if fn not in results or not results[fn].get("ok")]
    print(f"  下载: {len(filenames)} 总, {len(filenames) - len(todo)} 已完成, {len(todo)} 待下载")

    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_dl, fn): fn for fn in todo}
        for fut in concurrent.futures.as_completed(futs):
            fn, info = fut.result()
            results[fn] = info
            done += 1
            if done % 50 == 0:
                progress_file.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
                ok = sum(1 for v in results.values() if v.get("ok"))
                print(f"  进度: {done}/{len(todo)} (成功 {ok})")

    progress_file.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    return results


def point_to_box(x, y, W, H, name: str | None = None):
    """点标注→YOLO 归一化 bbox（中心点启发式外扩，框尺寸按 SKU 形态自适应）。"""
    wf, hf = sku_box_frac(name) if name else (BOX_W_FRAC, BOX_H_FRAC)
    bw = wf * W
    bh = hf * H
    x1 = max(0, x - bw / 2)
    y1 = max(0, y - bh / 2)
    x2 = min(W, x + bw / 2)
    y2 = min(H, y + bh / 2)
    # YOLO 格式：xc yc w h（归一化）
    xc = (x1 + x2) / 2 / W
    yc = (y1 + y2) / 2 / H
    w = (x2 - x1) / W
    h = (y2 - y1) / H
    return xc, yc, w, h


def generate_yolo_dataset(photos: dict, dl_info: dict, registry: dict, val_ratio: float = 0.1):
    """生成 YOLO 格式数据集：images/ + labels/ + data.yaml。"""
    YOLO_LABELS.mkdir(parents=True, exist_ok=True)
    YOLO_IMAGES.mkdir(parents=True, exist_ok=True)

    # 按照片 ID 排序，取前 val_ratio 做验证集
    valid_ids = sorted(pid for pid, p in photos.items()
                       if p["filename"] in dl_info and dl_info[p["filename"]].get("ok"))
    n_val = max(1, int(len(valid_ids) * val_ratio))
    val_ids = set(valid_ids[:n_val])

    stats = {"train": 0, "val": 0, "labels_total": 0, "skipped_no_registry": 0}
    for split, ids in [("train", [i for i in valid_ids if i not in val_ids]), ("val", val_ids)]:
        img_dir = YOLO_IMAGES / split
        lbl_dir = YOLO_LABELS / split
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)

        for pid in ids:
            p = photos[pid]
            info = dl_info[p["filename"]]
            sha = info["sha256"]
            W, H = info["width"], info["height"]
            blob_path = BLOBS / sha[:2] / sha

            # 符号链接图片（节省空间）
            ext = ".jpg"
            img_link = img_dir / f"{pid}{ext}"
            if not img_link.exists():
                img_link.symlink_to(blob_path.resolve())

            # 生成标签
            lines = []
            for ann in p["annotations"]:
                reg_entry = registry.get(ann["name"])
                if reg_entry is None:
                    stats["skipped_no_registry"] += 1
                    continue
                cls_id = reg_entry["class_id"]
                xc, yc, w, h = point_to_box(ann["x"], ann["y"], W, H, name=ann.get("name"))
                lines.append(f"{cls_id} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}")

            (lbl_dir / f"{pid}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            stats[split] += 1
            stats["labels_total"] += len(lines)

    # data.yaml
    nc = len(registry)
    names = sorted(registry.keys(), key=lambda n: registry[n]["class_id"])
    yaml_content = f"""path: {OUT_DIR.resolve()}
train: images/train
val: images/val
nc: {nc}
names: {json.dumps(names, ensure_ascii=False)}
"""
    (OUT_DIR / "data.yaml").write_text(yaml_content, encoding="utf-8")
    return stats


def main(workers=8, skip_download=False):
    print("=== 第一批训练数据入库 ===")
    t0 = time.time()

    # 1. 加载 SKU 注册表
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    print(f"[1/4] SKU 注册表: {len(registry)} 类")

    # 2. 解析 xlsx
    photos = parse_xlsx()
    n_ann = sum(len(p["annotations"]) for p in photos.values())
    print(f"[2/4] 解析 xlsx: {len(photos)} 照片, {n_ann} 标注")

    # 3. 下载照片
    filenames = sorted({p["filename"] for p in photos.values() if p["filename"]})
    if skip_download:
        progress_file = OUT_DIR / "download_progress.json"
        dl_info = json.loads(progress_file.read_text(encoding="utf-8")) if progress_file.exists() else {}
        print(f"[3/4] 跳过下载, 已有 {sum(1 for v in dl_info.values() if v.get('ok'))} 张")
    else:
        print(f"[3/4] 下载 {len(filenames)} 张照片 (workers={workers})...")
        dl_info = download_batch(filenames, BLOBS, workers=workers)
        ok = sum(1 for v in dl_info.values() if v.get("ok"))
        fail = sum(1 for v in dl_info.values() if not v.get("ok"))
        print(f"  完成: {ok} 成功, {fail} 失败")

    # 4. 生成 YOLO 数据集
    print("[4/4] 生成 YOLO 数据集...")
    stats = generate_yolo_dataset(photos, dl_info, registry)
    print(f"  train={stats['train']}, val={stats['val']}, labels={stats['labels_total']}")

    # 保存 manifest
    manifest = {
        "photos": {pid: {**p, "image": dl_info.get(p["filename"], {})} for pid, p in photos.items()},
        "stats": stats,
        "created_at": time.time(),
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, default=str), encoding="utf-8")

    elapsed = time.time() - t0
    print(f"\n=== 完成 ({elapsed:.1f}s) ===")
    print(f"  数据集: {OUT_DIR / 'data.yaml'}")
    print(f"  train: {stats['train']} 张, val: {stats['val']} 张")
    print(f"  标签总数: {stats['labels_total']}, SKU 类别: {len(registry)}")
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--skip-download", action="store_true")
    a = ap.parse_args()
    main(a.workers, a.skip_download)
