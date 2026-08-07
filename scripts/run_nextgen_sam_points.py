"""N2 Task 6：点提示 SAM 数据引擎（bounded、断点续跑、幂等）。

流程：分层采样 canonical 点 → 正点+负点+ROI prompt → SAM 2.1 Hiera Small
（.venv_sam 隔离，MPS fail-closed）→ multimask 候选 → 主环境几何门
（sam_gates）→ 接受：tight box + mask RLE + provenance；拒绝：原因留痕。

红线：SAM 产物为 sam_verified_pseudo（伪标签），不是 human gold；
进入训练前需 mask audit 人工门（02 §4.3）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SAM_PYTHON = ROOT / ".venv_sam/bin/python"
CKPT_MANIFEST = ROOT / ".sam_checkpoints/manifest.json"
OUT = ROOT / "reports/nextgen_v2/sam_point_masks.jsonl"
STATS = ROOT / "reports/nextgen_v2/sam_point_stats.json"


def _load_ckpt(model="sam2.1_hiera_small"):
    man = json.loads(CKPT_MANIFEST.read_text(encoding="utf-8"))
    for e in man["entries"]:
        if e["model"] == model:
            return Path(e["file"]), e["config"], e["sha256"]
    raise SystemExit(f"checkpoint 缺失: {model}")


def _decode_rle(rle: str, h: int, w: int):
    import numpy as np
    mask = np.zeros(h * w, dtype=bool)
    for seg in rle.split(","):
        if not seg:
            continue
        start, ln = seg.split(":")
        mask[int(start):int(start) + int(ln)] = True
    return mask.reshape((h, w), order="F")


def sample_points(n_target: int, per_sku_cap: int, per_photo_cap: int,
                  quality_rejected: set[str]):
    """分层采样：SKU 覆盖优先，每 SKU/每照片封顶。"""
    import openpyxl
    from src.modules.nextgen_data.sku_identity import SkuIdentityService
    svc = SkuIdentityService(registry_path=ROOT / "data/sku_registry.json",
                             aliases_path=ROOT / "data/sku_aliases.json")
    cm = json.loads((ROOT / ".batch3_clean/clean_manifest.json")
                    .read_text(encoding="utf-8"))
    wb = openpyxl.load_workbook(ROOT / "第三批训练数据.xlsx", read_only=True)
    by_photo: dict[str, list] = defaultdict(list)
    for r in wb.active.iter_rows(min_row=2, values_only=True):
        if r[0] is None:
            continue
        pid = str(r[0])
        if cm.get(pid, {}).get("sha256") in quality_rejected:
            continue
        by_photo[pid].append({"x": float(r[11]), "y": float(r[12]),
                              "name": str(r[9] or ""),
                              "code": str(r[10] or "")})
    wb.close()
    per_sku: dict[str, int] = defaultdict(int)
    picked: dict[str, list] = {}
    for pid, pts in sorted(by_photo.items()):
        sel = []
        for i, pt in enumerate(pts):
            if len(sel) >= per_photo_cap:
                break
            ident = svc.resolve(pt["name"], code=pt["code"])
            key = ident["sku_id"] or f"__{ident['status']}"
            if per_sku[key] >= per_sku_cap:
                continue
            per_sku[key] += 1
            sel.append({**pt, "sku_key": key,
                        "status": ident["status"],
                        "sku_id": ident["sku_id"]})
        if sel:
            picked[pid] = sel
        if sum(len(v) for v in picked.values()) >= n_target:
            break
    return picked, cm


def _roi_box(pt, others, width, height):
    """局部 ROI：最近邻距离的一半作为半径（缺省图像 6%）。"""
    dists = [math.hypot(o["x"] - pt["x"], o["y"] - pt["y"])
             for o in others]
    r = (min(dists) / 2) if dists else max(width, height) * 0.06
    r = max(r, 16.0)
    return [max(0.0, pt["x"] - r), max(0.0, pt["y"] - r),
            min(float(width), pt["x"] + r), min(float(height), pt["y"] + r)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", type=int, default=6000)
    ap.add_argument("--per-sku-cap", type=int, default=40)
    ap.add_argument("--per-photo-cap", type=int, default=12)
    ap.add_argument("--images-per-worker", type=int, default=40)
    args = ap.parse_args()

    from src.modules.nextgen_data.sam_gates import score_multimask

    done_photos: set[str] = set()
    if OUT.exists():
        with OUT.open() as f:
            for line in f:
                try:
                    done_photos.add(json.loads(line)["photo_id"])
                except Exception:
                    continue
    qrej: set[str] = set()
    qfile = ROOT / "reports/nextgen_v2/quality_decisions.jsonl"
    if qfile.exists():
        with qfile.open() as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if d.get("conclusion") == "rejected":
                        qrej.add(d["sha256"])
                except Exception:
                    continue
    print(f"quality rejected 照片排除: {len(qrej)}", flush=True)

    picked, cm = sample_points(args.points, args.per_sku_cap,
                               args.per_photo_cap, qrej)
    todo = {p: v for p, v in picked.items() if p not in done_photos}
    total_pts = sum(len(v) for v in todo.values())
    print(f"采样照片 {len(picked)}（待处理 {len(todo)}），点 {total_pts}",
          flush=True)

    ckpt, config, ckpt_sha = _load_ckpt()
    fout = OUT.open("a", encoding="utf-8")
    stats = defaultdict(int)
    t0 = time.time()
    pids = list(todo)
    for bi in range(0, len(pids), args.images_per_worker):
        batch = pids[bi:bi + args.images_per_worker]
        images = []
        for pid in batch:
            info = cm[pid]
            sha = info["sha256"]
            w, h = int(info.get("width") or 0), int(info.get("height") or 0)
            pts = todo[pid]
            instances = []
            for j, pt in enumerate(pts):
                others = [p for k, p in enumerate(pts) if k != j]
                negs = [[p["x"], p["y"]] for p in others
                        if math.hypot(p["x"] - pt["x"], p["y"] - pt["y"])
                        < max(w, h) * 0.15][:4]
                instances.append({
                    "instance_id": f"{pid}:{j}",
                    "positive": [pt["x"], pt["y"]],
                    "negatives": negs,
                    "roi_box": _roi_box(pt, others, w, h)})
            images.append({"image_id": pid,
                           "image_path": str(ROOT / ".batch3_clean/blobs" /
                                             sha[:2] / sha),
                           "width": w, "height": h, "instances": instances})
        request = {"checkpoint": str(ckpt), "config": config,
                   "checkpoint_sha256": ckpt_sha,
                   "model": "sam2.1_hiera_small", "images": images}
        with tempfile.NamedTemporaryFile("w", suffix=".json",
                                         delete=False) as tf:
            json.dump(request, tf, ensure_ascii=False)
            req_path = tf.name
        proc = subprocess.run([str(SAM_PYTHON),
                               str(ROOT / "scripts/sam_point_worker.py"),
                               "--request", req_path],
                              capture_output=True, text=True, timeout=3600)
        if proc.returncode != 0:
            print("worker 失败:", proc.stderr[:300], flush=True)
            stats["worker_failures"] += 1
            continue
        resp = json.loads(proc.stdout)
        for img_out in resp["results"]:
            pid = img_out["image_id"]
            if "error" in img_out:
                stats["decode_failed"] += 1
                continue
            info = cm[pid]
            w, h = int(info["width"]), int(info["height"])
            neighbor_masks = []
            for inst in img_out["instances"]:
                j = int(inst["instance_id"].split(":")[1])
                pt = todo[pid][j]
                cands = []
                for c in inst["candidates"]:
                    m = _decode_rle(c["rle"], h, w)
                    cands.append((m, c["score"]))
                pick, why = score_multimask(
                    cands, positive=(pt["x"], pt["y"]),
                    other_positives=[(p["x"], p["y"]) for p in todo[pid]],
                    width=w, height=h, neighbor_masks=neighbor_masks)
                rec = {"photo_id": pid,
                       "photo_sha256": info["sha256"],
                       "point": [pt["x"], pt["y"]],
                       "sku_id": pt.get("sku_id"),
                       "sku_status": pt.get("status"),
                       "label_source": "sam_verified_pseudo",
                       "sam_model_sha256": ckpt_sha,
                       "policy": "sam_point_gate_v1"}
                if pick is None:
                    rec.update({"accepted": False,
                                "rejections": why.get("rejections", [])})
                    stats["rejected"] += 1
                else:
                    m_best = cands[pick["index"]][0]
                    from scripts.sam_point_worker import _rle_encode
                    rec.update({"accepted": True,
                                "tight_box": pick["tight_box"],
                                "mask_rle": _rle_encode(m_best),
                                "area_px": pick["area_px"],
                                "sam_raw_score": pick["raw_score"],
                                "selected_reason": why["selected_reason"]})
                    neighbor_masks.append(m_best)
                    stats["accepted"] += 1
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            stats["photos_done"] += 1
        fout.flush()
        el = time.time() - t0
        print(f"batch {bi//args.images_per_worker + 1}: "
              f"photos={stats['photos_done']} "
              f"accepted={stats['accepted']} rejected={stats['rejected']} "
              f"elapsed={el/60:.1f}min", flush=True)
    fout.close()
    STATS.write_text(json.dumps({
        "stats": dict(stats), "elapsed_s": round(time.time() - t0, 1),
        "sam_checkpoint_sha256": ckpt_sha,
        "note": "sam_verified_pseudo 伪标签；mask audit 人工门完成前"
                "不得作为 gold/评估真值"}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps(dict(stats), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
