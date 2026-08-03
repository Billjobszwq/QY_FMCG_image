"""标注导出：把 Label Studio 人工审核后的标注导出为 YOLO 训练格式。

只导出有人工 annotation 的 task（即审核确认过的），按 region 解析：
  rectanglelabels(框) + taxonomy(SKU) + choices(状态) 通过相同 region id 关联。
训练集准入（ISSUE-004 拒绝式默认值）：
  - annotation.completed_by != null（真实人工）且未取消
  - 每个 region 必须显式 status=matched（缺状态/缺 SKU/框非法一律跳过）
  - SKU 必须属于当前 registry
LS 框坐标为百分比，转为 YOLO 归一化 (class_id xc yc w h)。

RA-014：
- out_name 强制安全目录名，输出路径规范化后必须落在 DATASETS 内
- 流式写入：图片下载后直接落盘，不在内存累积 bytes
- 切分改为 seed 固定 shuffle 后取 val（非确定性前 N）
- 框坐标 finite/范围完整校验
- staging 目录完整构建 → 计数/哈希对账 → 原子发布（旧版本归档）

用法：
  python -m src.ls_platform.exporter                    # 导出到 .datasets/ls_v1
  python -m src.ls_platform.exporter --out ls_v2 --val-ratio 0.1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import shutil
import sys
import time
from pathlib import Path

import requests

from ..common import paths
from ..common.config import PROJECT_ROOT
from .ls_client import LSClient

REGISTRY = PROJECT_ROOT / "data" / "sku_registry.json"
DATASETS = PROJECT_ROOT / ".datasets"


def _load_classmap():
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {name: info["class_id"] for name, info in reg.items()}, len(reg)


def _parse_regions(results: list[dict]) -> list[dict]:
    """把 LS annotation result 按 region id 聚合为 {box, sku, status}。"""
    by_id: dict[str, dict] = {}
    for r in results:
        rid = r.get("id")
        rtype = r.get("type")
        val = r.get("value", {})
        reg = by_id.setdefault(rid, {"box": None, "sku": None, "status": None})
        if rtype == "rectanglelabels":
            reg["box"] = (val.get("x"), val.get("y"), val.get("width"), val.get("height"))
        elif rtype == "taxonomy":
            tax = val.get("taxonomy") or []
            reg["sku"] = tax[0][0] if tax and tax[0] else None
        elif rtype == "choices":
            ch = val.get("choices") or []
            reg["status"] = ch[0] if ch else None
    return list(by_id.values())


def _download_image(client: LSClient, image_path: str) -> bytes | None:
    url = client.file_url(image_path)
    try:
        r = client.s.get(url, timeout=120)
        if r.status_code == 200 and r.content:
            return r.content
    except Exception:
        pass
    return None


def _region_lines(regions: list[dict], classmap: dict, only_matched: bool, counters: dict | None = None):
    """把 region 转为 YOLO 标签行；拒绝式默认值：缺状态/缺 SKU/框非法一律跳过（ISSUE-004）。"""
    lines = []
    for reg in regions:
        if reg["box"] is None or any(v is None for v in reg["box"]):
            if counters is not None:
                counters["skipped_box"] += 1
            continue
        status = reg["status"]  # 不再默认为 matched：缺状态即拒绝
        if only_matched and status != "matched":
            if counters is not None:
                counters["skipped_status"] += 1
            continue
        sku = reg["sku"]
        if sku not in classmap:
            if counters is not None:
                counters["skipped_sku"] += 1
            continue
        x, y, w, h = reg["box"]  # 百分比
        # 框合法性校验（ISSUE-004/010 + RA-014：finite/范围完整校验）
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (x, y, w, h)) \
           or w <= 0 or h <= 0 or x < -1 or y < -1 or x + w > 101 or y + h > 101:
            if counters is not None:
                counters["skipped_box"] += 1
            continue
        xc = (x + w / 2) / 100
        yc = (y + h / 2) / 100
        lines.append(f"{classmap[sku]} {xc:.6f} {yc:.6f} {w / 100:.6f} {h / 100:.6f}")
    return lines


def export_yolo(project_id: int | None = None, out_name: str = "ls_v1", val_ratio: float = 0.1,
                only_matched: bool = True, seed: int = 42):
    pid = project_id or int(os.environ.get("LABEL_STUDIO_PROJECT_ID", "1"))
    # RA-014：out_name 强制安全目录名；规范化后必须落在 DATASETS 内
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_\-]{0,63}", out_name):
        raise ValueError(f"非法输出目录名: {out_name!r}（仅允许字母/数字/_/-）")
    out_dir = (DATASETS / out_name).resolve()
    if DATASETS.resolve() not in out_dir.parents:
        raise ValueError(f"输出路径逃逸数据集根目录: {out_dir}")

    client = LSClient()
    classmap, nc = _load_classmap()
    tasks = client.export(pid, "JSON")

    counters = {"skipped_status": 0, "skipped_sku": 0, "skipped_box": 0}
    # RA-014：第一遍只收集 (task_id, label行, image_path)，不持有图片 bytes
    eligible: list[tuple] = []
    n_labels = n_no_human = 0
    for t in tasks:
        anns = t.get("annotations") or []
        if not anns:
            continue  # 无人工标注（仅 prediction），跳过 —— prediction 不入训练（ISSUE-004）
        # 取最新一条 annotation；必须是真实人工提交（completed_by 非空、未取消）
        ann = sorted(anns, key=lambda a: a.get("created_at", ""))[-1]
        if ann.get("was_cancelled") or not ann.get("completed_by"):
            n_no_human += 1
            continue
        regions = _parse_regions(ann.get("result", []))
        lines = _region_lines(regions, classmap, only_matched, counters)
        if not lines:
            continue
        image_path = (t.get("data") or {}).get("image")
        if not image_path:
            continue
        eligible.append((t.get("id"), lines, image_path))
        n_labels += len(lines)

    # RA-014：seed 固定 shuffle 后取 val（非确定性前 N）
    rng = random.Random(seed)
    order = [e[0] for e in eligible]
    rng.shuffle(order)
    n_val = 0 if len(order) < 2 else max(1, int(len(order) * val_ratio))
    val_ids = set(order[:n_val])

    # RA-014：staging 流式构建 → 对账 → 原子发布
    staging = DATASETS / f".staging_{out_name}_{int(time.time())}_{os.getpid()}"
    img_dir = staging / "images"
    lbl_dir = staging / "labels"
    for split in ("train", "val"):
        (img_dir / split).mkdir(parents=True)
        (lbl_dir / split).mkdir(parents=True)

    written = 0
    manifest_rows = []
    try:
        for tid, lines, image_path in eligible:
            img_bytes = _download_image(client, image_path)
            if not img_bytes:
                continue
            split = "val" if tid in val_ids else "train"
            ext = ".jpg" if img_bytes[:3] == b"\xff\xd8\xff" else ".png"
            paths.safe_write_bytes(img_dir / split / f"{tid}{ext}", img_bytes)
            lbl_txt = "\n".join(lines) + "\n"
            paths.safe_write_text(lbl_dir / split / f"{tid}.txt", lbl_txt)
            written += 1
            manifest_rows.append({"task_id": tid, "split": split, "n_boxes": len(lines),
                                  "img_sha256": hashlib.sha256(img_bytes).hexdigest(),
                                  "label_sha256": hashlib.sha256(lbl_txt.encode()).hexdigest()})
            del img_bytes  # 流式：不累积

        # 对账：磁盘文件数与写入计数一致，每张图片有对应 label
        problems = []
        for split in ("train", "val"):
            n_img = len(list((img_dir / split).glob("*.*")))
            n_lbl = len(list((lbl_dir / split).glob("*.txt")))
            if n_img != n_lbl:
                problems.append(f"{split} 图片{n_img} != 标签{n_lbl}")
        if written != len(manifest_rows):
            problems.append(f"写入计数 {written} != manifest {len(manifest_rows)}")
        if problems:
            raise RuntimeError("导出对账失败: " + "; ".join(problems))

        names = sorted(classmap.keys(), key=lambda n: classmap[n])
        yaml = f"path: {out_dir}\ntrain: images/train\nval: images/val\nnc: {nc}\nnames: {json.dumps(names, ensure_ascii=False)}\n"
        paths.safe_write_text(staging / "data.yaml", yaml)
        paths.safe_write_text(staging / "export_manifest.json",
                              json.dumps({"project_id": pid, "seed": seed, "val_ratio": val_ratio,
                                          "n_written": written, "rows": manifest_rows},
                                         ensure_ascii=False, indent=2))

        # 原子发布：旧版本归档 → staging 整体替换
        if out_dir.exists():
            archive = DATASETS / "archive" / f"{out_name}_{time.strftime('%Y%m%d%H%M%S')}"
            archive.parent.mkdir(parents=True, exist_ok=True)
            os.replace(out_dir, archive)
            print(f"  旧版本已归档: {archive}")
        os.replace(staging, out_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    summary = {
        "project_id": pid, "out": str(out_dir),
        "tasks_with_ann": written, "labels": n_labels,
        "skipped_status": counters["skipped_status"], "skipped_sku": counters["skipped_sku"],
        "skipped_box": counters["skipped_box"], "skipped_no_human": n_no_human,
        "train": written - n_val, "val": n_val, "nc": nc, "seed": seed,
    }
    print("EXPORT_YOLO", json.dumps(summary, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", type=int, default=None)
    ap.add_argument("--out", default="ls_v1")
    ap.add_argument("--val-ratio", type=float, default=0.1)
    ap.add_argument("--include-all-status", action="store_true")
    a = ap.parse_args()
    export_yolo(a.project_id, a.out, a.val_ratio, only_matched=not a.include_all_status)
