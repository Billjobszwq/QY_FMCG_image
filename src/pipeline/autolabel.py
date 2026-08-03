"""最小自动标记管线 + 评测（#11）。

流程：YOLO 检测瓶身 -> 裁剪 -> recognize(OCR+VLM+检索) -> 裁决/未知。
评测：用"金标标注点落在预测框内"做匹配（对中心点/角点都鲁棒），输出
detection_recall、sku_top1（宽松=任一覆盖框命中 / 严格=最高置信覆盖框命中）、
unknown_on_known、pred_extra，并按门店/场景切片。
每张照片追加写本次 run 的 .field/eval_progress_<run_id>.jsonl（ISSUE-019：不再删除历史进度），
结束写 .field/eval_runs/<run_id>.json 并更新 eval_report.json 指针（后台被杀也不丢已跑进度，历史可按 run ID 查询）。

运行：python -m src.pipeline.autolabel --max-photos 2 --conf 0.45
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import time
from pathlib import Path

from PIL import Image

from ..catalog.alias_registry import build_registry
from ..catalog.store import LocalStore
from ..common.config import PROJECT_ROOT
from .recognize import recognize

ALIAS = PROJECT_ROOT / "data" / "sku_aliases.json"
KB = PROJECT_ROOT / ".kb"
FIELD = PROJECT_ROOT / ".field"
REF = PROJECT_ROOT / "搭建初期P1"
# ISSUE-019：评测按 run ID 输出，latest 指针另存，历史不删除
EVAL_RUNS = FIELD / "eval_runs"
REPORT = FIELD / "eval_report.json"


def _blob_path(sha: str) -> Path:
    return FIELD / "blobs" / sha[:2] / sha


def detect(image_path: Path, conf: float, imgsz: int = 1280):
    from ultralytics import YOLO  # 延迟导入，避免 import 时加载 torch

    m = YOLO("yolo11n.pt")
    r = m.predict(str(image_path), conf=conf, imgsz=imgsz, verbose=False, device="cpu")
    names = m.names
    boxes = []
    for bi in r:
        if bi.boxes is None:
            continue
        for xyxy, cls, sc in zip(bi.boxes.xyxy.tolist(), bi.boxes.cls.tolist(), bi.boxes.conf.tolist()):
            if names.get(int(cls)) == "bottle":
                boxes.append((xyxy, float(sc)))
    boxes.sort(key=lambda t: -t[1])
    return boxes


def _in(ax: float, ay: float, box) -> bool:
    x1, y1, x2, y2 = box
    return x1 <= ax <= x2 and y1 <= ay <= y2


def run(max_photos: int = 2, conf: float = 0.45, topk: int = 5, unknown_thr: float = 0.30, max_det: int = 30) -> dict:
    m = json.load(open(FIELD / "manifest.json"))
    build_registry(sorted(p.name for p in REF.iterdir() if p.is_dir()), ALIAS)  # 校验对齐
    store = LocalStore(KB)
    ids, vec = store.load_vectors()

    # ISSUE-019：每次评测独立 run ID，进度文件不覆盖历史
    run_id = f"eval_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
    EVAL_RUNS.mkdir(parents=True, exist_ok=True)
    progress_path = FIELD / f"eval_progress_{run_id}.jsonl"
    totals = collections.Counter()
    by_store = collections.defaultdict(collections.Counter)
    by_type = collections.defaultdict(collections.Counter)
    per_photo = []

    for p in m["photos"][:max_photos]:
        sha = p["image"].get("sha256")
        if not sha:
            continue
        ip = _blob_path(sha)
        img = Image.open(ip).convert("RGB")
        W, H = img.size
        dets = detect(ip, conf)[:max_det]
        preds = []
        for box, sc in dets:
            x1, y1, x2, y2 = (int(v) for v in box)
            crop = img.crop((max(0, x1), max(0, y1), min(W, x2), min(H, y2)))
            if crop.width < 8 or crop.height < 8:
                continue
            rec = recognize(crop, store, ids, vec, topk=topk, unknown_thr=unknown_thr)
            preds.append({"box": box, "conf": sc, "decision": rec["decision"], "score": rec["score"]})

        ph = {"id": p["id"], "sname": p["meta"].get("sname"), "typename": p["meta"].get("typename"), "n_det": len(preds), "n_ann": len(p["annotations"])}
        for a in p["annotations"]:
            ax, ay, gold = a["x"], a["y"], a.get("canonical")
            covering = [pr for pr in preds if _in(ax, ay, pr["box"])]
            totals["ann"] += 1
            key_s = by_store[p["meta"].get("sname")]
            key_t = by_type[p["meta"].get("typename")]
            if covering:
                totals["det_covered"] += 1
                key_s["det_covered"] += 1
                key_t["det_covered"] += 1
                if gold and any(pr["decision"] == gold for pr in covering):
                    totals["sku_correct_lenient"] += 1
                    key_s["sku_correct_lenient"] += 1
                    key_t["sku_correct_lenient"] += 1
                best = max(covering, key=lambda pr: pr["conf"])
                if gold and best["decision"] == gold:
                    totals["sku_correct_strict"] += 1
                    key_s["sku_correct_strict"] += 1
                    key_t["sku_correct_strict"] += 1
                if gold and all(pr["decision"] == "unknown" for pr in covering):
                    totals["unknown_on_known"] += 1
            else:
                totals["ann_uncovered"] += 1
                key_s["ann_uncovered"] += 1
                key_t["ann_uncovered"] += 1
            totals["ann_total_per_store_" + str(p["meta"].get("sname"))]  # noop keep key warm
        for pr in preds:
            if not any(_in(a["x"], a["y"], pr["box"]) for a in p["annotations"]):
                totals["pred_extra"] += 1
        per_photo.append(ph)
        with open(progress_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(ph, ensure_ascii=False) + "\n")

    def acc(correct, base):
        return round(correct / base, 4) if base else 0.0

    report = {
        "run_id": run_id,
        "params": {"max_photos": max_photos, "conf": conf, "topk": topk, "unknown_thr": unknown_thr, "max_det": max_det, "imgsz": 1280},
        "photos_evaluated": len(per_photo),
        "totals": dict(totals),
        "detection_recall": acc(totals["det_covered"], totals["ann"]),
        "sku_top1_lenient": acc(totals["sku_correct_lenient"], totals["det_covered"]),
        "sku_top1_strict": acc(totals["sku_correct_strict"], totals["det_covered"]),
        "unknown_on_known_rate": acc(totals["unknown_on_known"], totals["det_covered"]),
        "by_store": {k: dict(v) for k, v in by_store.items()},
        "by_type": {k: dict(v) for k, v in by_type.items()},
        "per_photo": per_photo,
        "progress_file": str(progress_path),
    }
    # ISSUE-019：历史报告按 run ID 保留；current 指针原子更新
    run_path = EVAL_RUNS / f"{run_id}.json"
    tmp = run_path.with_name(run_path.name + ".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, run_path)
    tmp2 = REPORT.with_name(REPORT.name + ".tmp")
    tmp2.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp2, REPORT)
    print(
        "EVAL_REPORT",
        json.dumps({k: report[k] for k in ["params", "photos_evaluated", "totals", "detection_recall", "sku_top1_lenient", "sku_top1_strict", "unknown_on_known_rate"]}, ensure_ascii=False),
    )
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-photos", type=int, default=2)
    ap.add_argument("--conf", type=float, default=0.45)
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--unknown-thr", type=float, default=0.30)
    ap.add_argument("--max-det", type=int, default=30)
    a = ap.parse_args()
    run(a.max_photos, a.conf, a.topk, a.unknown_thr, a.max_det)
