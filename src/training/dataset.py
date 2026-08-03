"""从 approved 构建 YOLO 数据集。防泄漏=按照片切分；不足 2 张时 val=train（smoke）。
approved 是训练唯一来源（人工通过后才生成），见 emit.apply_review_to_approved。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common import paths

ROOT = paths.PROJECT_ROOT
FIELD = ROOT / ".field"
LABEL = ROOT / ".labels"
DS = ROOT / ".datasets" / "v1"


def build(val_ratio=0.2):
    m = json.load(open(FIELD / "manifest.json", encoding="utf-8"))
    # ISSUE-008：AssetId 统一规范化为字符串（历史 manifest 可能为整数，文件 stem 为字符串）
    idx = {str(p["id"]): p for p in m["photos"]}
    classes = json.load(open(LABEL / "classes.json", encoding="utf-8"))
    approved = sorted((LABEL / "approved").glob("*.txt"))
    ids = [str(a.stem) for a in approved]
    n_val = 0 if len(ids) < 2 else max(1, int(len(ids) * val_ratio))
    val_ids = set(ids[:n_val])
    train_ids = [i for i in ids if i not in val_ids] or ids
    val_use = list(val_ids) or train_ids
    for split, sids in (("train", train_ids), ("val", val_use)):
        (DS / "images" / split).mkdir(parents=True, exist_ok=True)
        (DS / "labels" / split).mkdir(parents=True, exist_ok=True)
        for i in sids:
            p = idx[i]
            sha = p["image"].get("sha256") or p["image"].get("sha")
            src = FIELD / "blobs" / sha[:2] / sha
            data = src.read_bytes()
            ext = ".jpg" if data[:3] == b"\xff\xd8\xff" else ".png"
            paths.safe_write_bytes(DS / "images" / split / f"{i}{ext}", data)
            paths.safe_write_text(DS / "labels" / split / f"{i}.txt", (LABEL / "approved" / f"{i}.txt").read_text(encoding="utf-8"))
    yaml = f"path: {DS.resolve()}\ntrain: images/train\nval: images/val\nnc: {len(classes)}\nnames: {classes}\n"
    paths.safe_write_text(DS / "data.yaml", yaml)
    rep = {"approved_photos": len(ids), "train": len(train_ids), "val": len(val_use), "nc": len(classes), "data_yaml": str(DS / "data.yaml")}
    print("DATASET", json.dumps(rep, ensure_ascii=False))
    return rep


if __name__ == "__main__":
    build()
