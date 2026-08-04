"""Gate S0 benchmark（手册§五）：50 张 / 约 1000 坐标点，双模型比较。

坐标点来源（均为 prompt 种子，不是真实框）：
- 9 张 .field 照片：人工协议坐标点（诊断用，不进训练）；
- 41 张照片1106/1107：现有检测器 best/sku_v4_best.pt 的 proposal 框中心
  （P1 proposal 语义，手册§六.10 completeness queue 的合法来源）。

测量：每图 encoder 时间、每点 decoder 时间、RSS/MPS 内存、swap、
确定性（重复单图 mask SHA 对比）；质量代理指标：候选硬约束通过率
（candidates.filter_candidates，仅诊断信号，最终质量由 S1 人工判定）。

用法：
  python -m scripts.run_sam_benchmark --model sam2.1_hiera_small --n-field 9 --n-proposal 41
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

from src.sam_assist.candidates import (CandidateDecision, PhysicalLimits,
                                       filter_candidates)
from src.sam_assist.contracts import InstanceInput, SamCandidate
from src.sam_assist.prompts import PromptConfig, build_prompts
from src.sam_assist.runtime import CHECKPOINTS
from src.sam_assist.service import SAMWorkerClient

CKPT_DIR = PROJECT_ROOT / ".sam_checkpoints"
MAX_POINTS_PER_IMAGE = 30


def _swap() -> str:
    try:
        return subprocess.run(["sysctl", "vm.swapusage"], capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except Exception:
        return "(unavailable)"


def _field_photos(n: int):
    manifest = json.loads((PROJECT_ROOT / ".field/manifest.json")
                          .read_text(encoding="utf-8"))
    con = sqlite3.connect(PROJECT_ROOT / ".warehouse/db.sqlite")
    assets = {str(r[0]): {"sha256": r[1], "width": r[2], "height": r[3]}
              for r in con.execute(
                  "select asset_id, sha256, width, height from asset")}
    out = []
    for p in manifest["photos"]:
        pid = str(p["id"])
        if pid not in assets:
            continue
        a = assets[pid]
        blob = PROJECT_ROOT / ".field/blobs" / a["sha256"][:2] / a["sha256"]
        if not blob.exists():
            continue
        pts = [(float(x["x"]), float(x["y"])) for x in p["annotations"]]
        out.append({"photo_id": f"field_{pid}", "blob": blob,
                    "sha": a["sha256"], "width": a["width"],
                    "height": a["height"], "points": pts,
                    "point_source": "human_protocol"})
        if len(out) >= n:
            break
    return out


def _grid_photos(n: int):
    """照片1106+1107 确定性抽样，确定性网格点作为坐标点。

    这些照片是单品近拍（未注册 SKU），货架检测器无输出；
    网格点仅用于性能/确定性测量（point_source=benchmark_grid_v1），
    质量评估由 S1 人工框承担（手册§五/§九）。"""
    import hashlib
    pool = sorted([p for ext in ("照片1106", "照片1107")
                   for p in (PROJECT_ROOT / ext).glob("*.jpg")])
    step = max(1, len(pool) // n)
    picks = pool[::step][:n]
    out = []
    for path in picks:
        import cv2
        img = cv2.imread(str(path))
        if img is None:
            continue
        h, w = img.shape[:2]
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        pts = []
        for r in range(5):
            for c in range(4):
                x = w * (0.15 + 0.7 * c / 3.0)
                y = h * (0.12 + 0.76 * r / 4.0)
                pts.append((round(x, 1), round(y, 1)))
        out.append({"photo_id": f"grid_{path.stem}", "blob": path,
                    "sha": sha, "width": w, "height": h, "points": pts,
                    "point_source": "benchmark_grid_v1"})
    return out


def _build_request(photos, model: str, out_dir: Path, cfg: PromptConfig):
    ckpt_manifest = json.loads((CKPT_DIR / "manifest.json").read_text())
    sha = next(e["sha256"] for e in ckpt_manifest["entries"]
               if e["model"] == model)
    images_req = []
    n_points = 0
    for ph in photos:
        inst_inputs = [InstanceInput(
            asset_id=ph["photo_id"], photo_id=ph["photo_id"],
            image_sha256=ph["sha"], width=ph["width"], height=ph["height"],
            instance_id=f"{ph['photo_id']}_{i:03d}", x=x, y=y,
            quality_version="benchmark_s0")
            for i, (x, y) in enumerate(ph["points"])]
        instances = []
        for inst in inst_inputs:
            ps = build_prompts(inst, inst_inputs,
                               box_frac_fn=lambda _name: None, cfg=cfg)
            instances.append({
                "instance_id": inst.instance_id,
                "positive": list(ps.positive_point),
                "negatives": [list(p) for p in ps.negative_points],
                "coarse_box": list(ps.coarse_box),
                "prompt_config_version": ps.config_version,
            })
            n_points += 1
        images_req.append({"image_path": str(ph["blob"]),
                           "image_sha": ph["sha"],
                           "photo_id": ph["photo_id"],
                           "instances": instances})
    request = {
        "_request_path": str(out_dir / "request.json"),
        "model": model,
        "checkpoint": str(CKPT_DIR / f"{model}.pt"),
        "checkpoint_sha256": sha,
        "config": CHECKPOINTS[model]["config"],
        "out_dir": str(out_dir),
        "images": images_req,
    }
    return request, n_points


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=sorted(CHECKPOINTS))
    ap.add_argument("--n-field", type=int, default=9)
    ap.add_argument("--n-proposal", type=int, default=41)
    a = ap.parse_args()

    cfg = PromptConfig()
    photos = _field_photos(a.n_field) + _grid_photos(a.n_proposal)
    print(f"[bench] photos={len(photos)} "
          f"(field={min(a.n_field, 9)}, proposal)")

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / ".sam_runs" / f"bench_{a.model}_{ts}"
    request, n_points = _build_request(photos, a.model, out_dir, cfg)
    print(f"[bench] model={a.model} points={n_points}")

    swap_before = _swap()
    client = SAMWorkerClient(timeout=3600)
    resp = client.invoke(request)
    swap_after = _swap()

    # 质量代理：候选硬约束通过率（仅诊断，最终质量由 S1 人工判定）
    import cv2
    import numpy as np
    pass_cnt = total_cnt = 0
    field_pass = field_total = 0
    reasons = {}
    src_by_sha = {p["sha"]: p["point_source"] for p in photos}
    pos_by_inst = {i["instance_id"]: tuple(i["positive"])
                   for im in request["images"] for i in im["instances"]}
    roi_by_inst = {i["instance_id"]: tuple(i["coarse_box"])
                   for im in request["images"] for i in im["instances"]}
    pts_by_sha = {im["image_sha"]: [tuple(i["positive"])
                                     for i in im["instances"]]
                  for im in request["images"]}
    for r in resp["results"]:
        ph = next(p for p in photos if p["sha"] == r["image_sha"])
        limits = PhysicalLimits(min_area_px=400.0,
                                max_area_px=0.6 * ph["width"] * ph["height"],
                                min_aspect=0.05, max_aspect=8.0)
        all_pts = pts_by_sha[r["image_sha"]]
        for inst in r["instances"]:
            positive = pos_by_inst[inst["instance_id"]]
            others = [p for p in all_pts if p != positive]
            cands = []
            for c in inst["candidates"]:
                mask = cv2.imread(c["mask_path"], cv2.IMREAD_GRAYSCALE)
                if mask is None:
                    continue
                cands.append(SamCandidate(
                    candidate_id=c["candidate_id"],
                    mask=(mask > 127).astype(np.uint8),
                    iou_score=c["iou_score"],
                    stability_score=c["stability_score"]))
            fr = filter_candidates(cands, positive, others,
                                   roi=roi_by_inst[inst["instance_id"]],
                                   limits=limits, selected_masks=[])
            total_cnt += 1
            ok = fr.decision is CandidateDecision.ACCEPTED
            pass_cnt += int(ok)
            if src_by_sha[r["image_sha"]] == "human_protocol":
                field_total += 1
                field_pass += int(ok)
            for c in fr.candidates:
                for rr in c.reject_reasons:
                    reasons[rr] = reasons.get(rr, 0) + 1

    # 确定性：重跑第一张图，比较 mask SHA
    det_dir = out_dir / "determinism"
    det_req = dict(request)
    det_req["_request_path"] = str(det_dir / "request.json")
    det_req["out_dir"] = str(det_dir)
    det_req["images"] = request["images"][:1]
    resp2 = client.invoke(det_req)
    sha1 = [c["mask_sha256"] for i in resp["results"][0]["instances"]
            for c in i["candidates"]]
    sha2 = [c["mask_sha256"] for i in resp2["results"][0]["instances"]
            for c in i["candidates"]]
    deterministic = sha1 == sha2

    enc = [r["encoder_sec"] for r in resp["results"]]
    dec = [i["decoder_sec"] for r in resp["results"] for i in r["instances"]]
    report = {
        "gate": "S0_benchmark",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": a.model,
        "checkpoint_sha256": request["checkpoint_sha256"],
        "prompt_config_version": cfg.config_version,
        "n_photos": len(photos),
        "n_points": n_points,
        "env": resp["env"],
        "wall_time_sec": resp["wall_time_sec"],
        "swap_before": swap_before,
        "swap_after": swap_after,
        "encoder_sec_mean": round(sum(enc) / len(enc), 4),
        "encoder_sec_max": round(max(enc), 4),
        "decoder_sec_per_point_mean": round(sum(dec) / len(dec), 4),
        "decoder_sec_per_point_max": round(max(dec), 4),
        "mps_peak_mem_bytes": max(r["mps_peak_mem_bytes"]
                                   for r in resp["results"]),
        "hard_constraint_pass_rate": round(pass_cnt / max(1, total_cnt), 4),
        "hard_constraint_counts": {"pass": pass_cnt, "total": total_cnt},
        "field_point_pass": {"pass": field_pass, "total": field_total,
                             "rate": round(field_pass / max(1, field_total), 4)},
        "reject_reasons": reasons,
        "deterministic_rerun": deterministic,
        "results": resp["results"],
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[bench] ok device={resp['env']['device']} wall={resp['wall_time_sec']}s")
    print(f"  encoder mean/max: {report['encoder_sec_mean']}s/{report['encoder_sec_max']}s")
    print(f"  decoder/point mean/max: {report['decoder_sec_per_point_mean']}s/"
          f"{report['decoder_sec_per_point_max']}s")
    print(f"  mps peak: {report['mps_peak_mem_bytes']/1e6:.0f}MB "
          f"rss: {resp['env']['peak_rss_mb']}MB")
    print(f"  hard-constraint pass: {pass_cnt}/{total_cnt} "
          f"({report['hard_constraint_pass_rate']})")
    print(f"  deterministic rerun: {deterministic}")
    print(f"[bench] report: {out_dir/'report.json'}")


if __name__ == "__main__":
    main()
