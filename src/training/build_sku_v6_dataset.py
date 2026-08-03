"""sku_v6 召回专项训练数据集构建。

数据组成（透明可审计）：
  - 旧数据：batch2_v4 train（5976 张，symlink，前缀 old_）——保住基础泛化
  - 第三批清洗好图（.batch3_clean）：覆盖驱动抽样（RA-008，非随机 4000）：
      * Phase A：保证每个出现类达到 min-per-class 独立实例（稀有类优先）
      * Phase B：覆盖尚未入选的新门店（跨门店泛化）
      * Phase C：剩余配额随机填充（难例/灰名单照片仍单独处理）
  - 标签：第三批 xlsx 点标注 → sku_box_frac 转 YOLO bbox
  - 切分：按门店 group split（RA-008），val 门店码绝不出现在 train（防泄露）

用法：python -m src.training.build_sku_v6_dataset [--batch3-budget 4000] [--val-ratio 0.1]
        [--min-per-class 20]"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT
from ..common import paths as _paths
from ..training.ingest_train import sku_box_frac

XLSX3 = PROJECT_ROOT / "第三批训练数据.xlsx"
CLEAN_MANIFEST = PROJECT_ROOT / ".batch3_clean" / "clean_manifest.json"
CLEAN_BLOBS = PROJECT_ROOT / ".batch3_clean" / "blobs"
GRAY_MANIFEST = PROJECT_ROOT / "batch3_gray" / "gray_manifest.json"
REGISTRY = PROJECT_ROOT / "data" / "sku_registry.json"
OLD_DS = PROJECT_ROOT / ".datasets" / "batch2_v4"
OUT_DIR = PROJECT_ROOT / ".datasets" / "sku_v6"

# 漏检重灾 SKU（来自端到端测试最差召回）。注：这些 SKU 在百事货架极常见（91%照片含），
# 故不做照片级复制过采样（避免数据膨胀），靠 imgsz=1024+强增强提升小目标召回。
HARD_SKU_KEYWORDS = ["美橙600ml", "百事600ml", "拉罐330ml", "芬达橙500ml", "1L美年达", "细长罐330ml"]
GRAY_INCLUDE_PROB = 0.5


def parse_batch3_annotations() -> dict:
    """解析第三批 xlsx → {photo_id: [ {name,x,y}, ... ]}"""
    wb = openpyxl.load_workbook(str(XLSX3), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(c).strip() if c else "" for c in rows[0]]
    idx = {n: i for i, n in enumerate(header)}
    wb.close()

    def g(r, k):
        return r[idx[k]] if k in idx and idx[k] < len(r) else None

    anns = collections.defaultdict(list)
    for r in rows[1:]:
        pid = g(r, "ID")
        if pid is None:
            continue
        pid = str(int(pid)) if isinstance(pid, float) else str(pid)
        name, x, y = g(r, "name"), g(r, "x"), g(r, "y")
        if name and x is not None and y is not None:
            anns[pid].append({"name": str(name).strip(), "x": float(x), "y": float(y)})
    return dict(anns)


def store_of(pid, clean) -> str:
    """从 filename 提取门店名（第 2 段），用于 group split（RA-008）。"""
    fn = (clean.get(pid) or {}).get("filename", "")
    parts = fn.split("_")
    return parts[1] if len(parts) > 1 else "NA"


def coverage_sample(pool, anns, registry, budget, min_per_class, rng, clean) -> list:
    """RA-008 覆盖驱动抽样：类覆盖优先 → 新门店覆盖 → 随机填充。"""
    # 每张照片贡献的注册类别
    photo_classes = {}
    for pid in pool:
        cs = {registry[a["name"]]["class_id"] for a in anns.get(pid, []) if a["name"] in registry}
        if cs:
            photo_classes[pid] = cs
    candidates = list(photo_classes.keys())
    rng.shuffle(candidates)

    selected, selected_set = [], set()
    class_have = collections.Counter()

    # Phase A：稀有类优先 —— 反复扫描直到每个出现类达到 min_per_class 或无增量
    progress = True
    while progress and len(selected) < budget:
        progress = False
        need = {c for c, n in class_have.items() if n < min_per_class}
        # 也包含尚未出现的类
        all_cls = set().union(*photo_classes.values())
        need |= (all_cls - set(class_have))
        for pid in candidates:
            if len(selected) >= budget or not need:
                break
            if pid in selected_set:
                continue
            gain = photo_classes[pid] & need
            if gain:
                selected.append(pid)
                selected_set.add(pid)
                for c in photo_classes[pid]:
                    class_have[c] += 1
                need -= {c for c in gain if class_have[c] >= min_per_class}
                progress = True

    # Phase B：覆盖新门店
    stores_have = {store_of(p, clean) for p in selected}
    for pid in candidates:
        if len(selected) >= budget:
            break
        if pid in selected_set:
            continue
        s = store_of(pid, clean)
        if s not in stores_have:
            selected.append(pid)
            selected_set.add(pid)
            stores_have.add(s)
            for c in photo_classes[pid]:
                class_have[c] += 1

    # Phase C：随机填充剩余配额
    for pid in candidates:
        if len(selected) >= budget:
            break
        if pid not in selected_set:
            selected.append(pid)
            selected_set.add(pid)
    return selected


def build(batch3_budget: int = 4000, val_ratio: float = 0.1, seed: int = 42,
          min_per_class: int = 20):
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    clean = json.loads(CLEAN_MANIFEST.read_text(encoding="utf-8"))
    gray = json.loads(GRAY_MANIFEST.read_text(encoding="utf-8")) if GRAY_MANIFEST.exists() else {}
    gray_ids = set(gray.keys())

    print("[sku_v6] 解析第三批标注 ...")
    anns = parse_batch3_annotations()
    print(f"  第三批有标注照片: {len(anns)}")

    rng = random.Random(seed)

    # 分类 batch3 clean 照片
    hard_ids, normal_ids = [], []
    for pid in clean.keys():
        pa = anns.get(pid, [])
        if not pa:
            continue
        is_hard = any(any(kw in a["name"] for kw in HARD_SKU_KEYWORDS) for a in pa)
        if pid in gray_ids:
            continue  # 灰名单单独处理
        (hard_ids if is_hard else normal_ids).append(pid)

    gray_list = [pid for pid in gray_ids if pid in clean and anns.get(pid)]

    print(f"  含难例SKU照片: {len(hard_ids)} | 普通照片: {len(normal_ids)} | 灰名单: {len(gray_list)}")

    # 灰名单 50% 纳入；其余从 hard+normal 池做覆盖驱动抽样（RA-008）
    gray_sel = [pid for pid in gray_list if rng.random() < GRAY_INCLUDE_PROB]
    pool = hard_ids + normal_ids
    budget = max(0, batch3_budget - len(gray_sel))
    selected = coverage_sample(pool, anns, registry, budget, min_per_class, rng, clean)
    print(f"  覆盖驱动抽样: 池{len(pool)} → 选{len(selected)} (min_per_class={min_per_class})")

    # RA-008：按门店 group split —— val 门店码绝不出现在 train
    all_sel = selected + gray_sel
    store_map = collections.defaultdict(list)
    for pid in all_sel:
        store_map[store_of(pid, clean)].append(pid)
    stores = sorted(store_map.keys())
    rng.shuffle(stores)
    n_val_target = max(50, int(len(all_sel) * val_ratio))
    val_ids, n_val = set(), 0
    for s in stores:
        if n_val >= n_val_target:
            break
        val_ids.update(store_map[s])
        n_val += len(store_map[s])
    train_ids = [p for p in all_sel if p not in val_ids]
    assert not ({store_of(p, clean) for p in val_ids} & {store_of(p, clean) for p in train_ids}), \
        "门店 group split 失败：val 门店出现在 train"

    # 建目录
    for split in ("train", "val"):
        (OUT_DIR / "images" / split).mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "labels" / split).mkdir(parents=True, exist_ok=True)

    stats = {"train_b3": 0, "val_b3": 0, "gray_train": 0, "skipped_unregistered": 0,
             "unregistered_names": collections.Counter()}

    def write_photo(pid, split, tag):
        rec = clean[pid]
        sha = rec.get("sha256")
        if not sha:
            return False
        bp = CLEAN_BLOBS / sha[:2] / sha
        if not bp.exists():
            return False
        try:
            from PIL import Image
            with Image.open(bp) as im:
                W, H = im.size
        except Exception:
            return False
        img_name = f"b3_{pid}_{tag}"
        link = OUT_DIR / "images" / split / f"{img_name}.jpg"
        if not link.exists():
            link.symlink_to(bp.resolve())
        lines = []
        for a in anns.get(pid, []):
            reg = registry.get(a["name"])
            if reg is None:
                # RA-009 透明化：未注册标签不再静默丢弃，计入审计（other 类转
                # __unknown__ 负样本由 crop 构建器负责，检测端暂不入 208 类闭集）
                stats["skipped_unregistered"] += 1
                stats["unregistered_names"][a["name"]] += 1
                continue
            wf, hf = sku_box_frac(a["name"])
            bw, bh = wf * W, hf * H
            x, y = a["x"], a["y"]
            x1, y1 = max(0, x - bw / 2), max(0, y - bh / 2)
            x2, y2 = min(W, x + bw / 2), min(H, y + bh / 2)
            if x2 - x1 < 2 or y2 - y1 < 2:
                continue
            lines.append(f"{reg['class_id']} {(x1+x2)/2/W:.6f} {(y1+y2)/2/H:.6f} {(x2-x1)/W:.6f} {(y2-y1)/H:.6f}")
        if not lines:
            return False
        (OUT_DIR / "labels" / split / f"{img_name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True

    for pid in train_ids:
        tag = "gray" if pid in gray_ids else "n"
        if write_photo(pid, "train", tag):
            stats["train_b3"] += 1
            if tag == "gray":
                stats["gray_train"] += 1
    for pid in val_ids:
        if write_photo(pid, "val", "v"):
            stats["val_b3"] += 1

    # 合并旧数据 train（symlink，前缀 old_）
    old_img_dir = OLD_DS / "images" / "train"
    old_lbl_dir = OLD_DS / "labels" / "train"
    old_count = 0
    if old_img_dir.exists():
        for img in old_img_dir.iterdir():
            stem = img.stem
            src_lbl = old_lbl_dir / f"{stem}.txt"
            dst_img = OUT_DIR / "images" / "train" / f"old_{stem}.jpg"
            dst_lbl = OUT_DIR / "labels" / "train" / f"old_{stem}.txt"
            if not dst_img.exists():
                try:
                    dst_img.symlink_to(img.resolve())
                except Exception:
                    pass
            if src_lbl.exists() and not dst_lbl.exists():
                dst_lbl.write_text(src_lbl.read_text(encoding="utf-8"), encoding="utf-8")
            old_count += 1

    # data.yaml
    nc = len(registry)
    names = sorted(registry.keys(), key=lambda n: registry[n]["class_id"])
    yaml = f"path: {OUT_DIR.resolve()}\ntrain: images/train\nval: images/val\nnc: {nc}\nnames: {json.dumps(names, ensure_ascii=False)}\n"
    _paths.safe_write_text(OUT_DIR / "data.yaml", yaml)

    total_train = stats["train_b3"] + old_count
    # RA-009：未注册标签审计写入 summary（不再静默丢弃）
    audit = {"seed": seed, "min_per_class": min_per_class, "val_ratio": val_ratio,
             "val_stores": sorted({store_of(p, clean) for p in val_ids}),
             "skipped_unregistered": stats["skipped_unregistered"],
             "unregistered_top": stats["unregistered_names"].most_common(20)}
    _paths.safe_write_text(OUT_DIR / "build_audit.json",
                           json.dumps(audit, ensure_ascii=False, indent=2))
    print("\n=== sku_v6 数据集构建完成 ===")
    print(f"  train 总数: {total_train} (batch3 {stats['train_b3']} + 旧数据 {old_count})")
    print(f"    其中灰名单(50%降采样): {stats['gray_train']}")
    print(f"  val 总数: {stats['val_b3']} (门店 group split，防泄露)")
    print(f"  未注册标签（审计不入训练）: {stats['skipped_unregistered']} (RA-009)")
    print(f"  data.yaml: {OUT_DIR/'data.yaml'}")
    return {"train_total": total_train, "val": stats["val_b3"], "stats": stats, "old": old_count}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch3-budget", type=int, default=4000)
    ap.add_argument("--val-ratio", type=float, default=0.1)
    ap.add_argument("--min-per-class", type=int, default=20,
                    help="覆盖驱动抽样：每个出现类最少独立实例数（RA-008）")
    a = ap.parse_args()
    build(a.batch3_budget, a.val_ratio, min_per_class=a.min_per_class)
