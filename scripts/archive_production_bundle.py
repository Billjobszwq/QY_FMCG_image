"""归档当前最优生产模型与全部训练数据指纹为只读 bundle（RA-003/RA-006 前置止损）。

用法：python -m scripts.archive_production_bundle
产物：.models/archive/<bundle_id>/（整体只读，含 MANIFEST.json 全量 sha256）
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODELS = PROJECT_ROOT / ".models"
ARCHIVE_ROOT = MODELS / "archive"


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def copy_item(src: Path, dst: Path, manifest: list) -> None:
    if not src.exists():
        raise FileNotFoundError(f"归档源缺失: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    manifest.append({"file": str(dst.relative_to(ARCHIVE_ROOT)), "source": str(src),
                     "size": dst.stat().st_size, "sha256": sha256_of(dst)})


def dataset_fingerprint() -> dict:
    """训练数据指纹：不复制 GB 级数据，固化可验证的内容哈希与计数。"""
    fp: dict = {}

    v6_yaml = PROJECT_ROOT / ".datasets" / "sku_v6" / "data.yaml"
    if v6_yaml.exists():
        fp["sku_v6_data_yaml"] = {"sha256": sha256_of(v6_yaml), "size": v6_yaml.stat().st_size}
        for split in ("train", "val"):
            d = PROJECT_ROOT / ".datasets" / "sku_v6" / "images" / split
            if d.exists():
                fp[f"sku_v6_images_{split}"] = {"count": sum(1 for _ in d.iterdir())}
            d = PROJECT_ROOT / ".datasets" / "sku_v6" / "labels" / split
            if d.exists():
                fp[f"sku_v6_labels_{split}"] = {"count": sum(1 for _ in d.iterdir())}

    crop = PROJECT_ROOT / "crop_dataset_yolo"
    if crop.exists():
        summary = crop / "dataset_summary.json"
        if summary.exists():
            fp["crop_dataset_yolo_summary"] = {"sha256": sha256_of(summary), "size": summary.stat().st_size}
        for split in ("train", "val"):
            d = crop / split
            if d.exists():
                fp[f"crop_dataset_yolo_{split}_crops"] = {
                    "count": sum(1 for _ in d.rglob("*.jpg")),
                    "classes": sum(1 for _ in d.iterdir() if _.is_dir()),
                }

    blobs = PROJECT_ROOT / ".training_data" / "blobs"
    if blobs.exists():
        fp["training_data_blobs"] = {"count": sum(1 for _ in blobs.rglob("*") if _.is_file())}

    b2 = PROJECT_ROOT / ".eval" / "batch2" / "manifest.json"
    if b2.exists():
        fp["batch2_manifest"] = {"sha256": sha256_of(b2), "size": b2.stat().st_size}

    registry = PROJECT_ROOT / "data" / "sku_registry.json"
    if registry.exists():
        fp["sku_registry"] = {"sha256": sha256_of(registry), "size": registry.stat().st_size}
    return fp


def main() -> int:
    bundle_id = f"prod_{time.strftime('%Y%m%d')}_v4_r2"
    bundle = ARCHIVE_ROOT / bundle_id
    if bundle.exists():
        print(f"bundle 已存在，拒绝覆盖: {bundle}", file=sys.stderr)
        return 1
    bundle.mkdir(parents=True)
    manifest: list = []

    # 最优生产权重（线上组合：sku_v4 detector + classifier R2）
    copy_item(MODELS / "sku_v4" / "weights" / "best.pt", bundle / "detector_v4_best.pt", manifest)
    copy_item(MODELS / "classifier" / "best.pt", bundle / "classifier_r2_best.pt", manifest)
    copy_item(MODELS / "classifier" / "classes.json", bundle / "classifier_classes.json", manifest)
    # 暂停的 v6 断点（保留续训能力）
    copy_item(MODELS / "sku_v6_ep6.pt", bundle / "detector_v6_ep6.pt", manifest)
    # SKU 注册表
    copy_item(PROJECT_ROOT / "data" / "sku_registry.json", bundle / "sku_registry.json", manifest)

    # 训练参数全记录
    meta_dir = bundle / "train_meta"
    for d in sorted(MODELS.iterdir()):
        m = d / "train_meta.json" if d.is_dir() else None
        if m and m.exists():
            copy_item(m, meta_dir / f"{d.name}_meta.json", manifest)
    for hist in ("training_history.json", "finetune_history_yolobox.json"):
        src = MODELS / "classifier" / hist
        if src.exists():
            copy_item(src, meta_dir / f"classifier_{hist}", manifest)

    # 阈值与决策记录
    thresholds = {
        "cascade_conf_threshold": 0.6,
        "note": "低置信判定阈值；RA-004 修复后低置信输出 unknown/needs_review，不再回退 detector SKU",
        "detector_export_conf": 0.15,
    }
    tp = bundle / "thresholds.json"
    tp.write_text(json.dumps(thresholds, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest.append({"file": str(tp.relative_to(ARCHIVE_ROOT)), "source": "generated",
                     "size": tp.stat().st_size, "sha256": sha256_of(tp)})

    # 数据集指纹
    df = bundle / "dataset_fingerprint.json"
    df.write_text(json.dumps(dataset_fingerprint(), ensure_ascii=False, indent=2), encoding="utf-8")
    manifest.append({"file": str(df.relative_to(ARCHIVE_ROOT)), "source": "generated",
                     "size": df.stat().st_size, "sha256": sha256_of(df)})

    # 总清单
    mfile = bundle / "MANIFEST.json"
    mfile.write_text(json.dumps({
        "bundle_id": bundle_id,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "production_combo": {"detector": "detector_v4_best.pt", "classifier": "classifier_r2_best.pt"},
        "reason": "终止 v6 phase2 训练前的止损归档：最优版本 + v6 断点 + 全量训练数据指纹",
        "files": manifest,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # 整体只读（目录保留 x 以便进入）
    for root, dirs, files in os.walk(bundle, topdown=False):
        for name in files:
            os.chmod(os.path.join(root, name), 0o444)
        for name in dirs:
            os.chmod(os.path.join(root, name), 0o555)
    os.chmod(bundle, 0o555)

    total_mb = sum(f["size"] for f in manifest) / 1e6
    print(f"归档完成: {bundle}（{len(manifest)} 文件, {total_mb:.1f} MB, 已置只读）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
