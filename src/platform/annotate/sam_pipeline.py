"""U4-1：点坐标引导 SAM 管线（point→prompt→mask→box 完整 lineage）。

口径（手册 §六/U4 指令）：
- 默认 SAM2.1 Hiera Small；只有该实例无合格候选（疑难）才升级
  Base+ 重推一次；仍无合格候选 → manual_required，绝不回退
  固定比例框（tight_box 恒为 NULL）。
- 每个实例的最终结论追加落库 sam_lineage_v1（不可变）：
  point（x/y）→ prompt（正/负点、粗 ROI、config 版本）→
  mask（SHA、路径）→ box（tight box、选择原因、规则版本）。
- SAM 权重推理在隔离 venv worker（.venv_sam）执行，主环境不落权重；
  worker 可注入（测试用确定性 stub）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from ...sam_assist.candidates import (CandidateDecision, PhysicalLimits,
                                      filter_candidates)
from ...sam_assist.contracts import InstanceInput, SamCandidate
from ...sam_assist.prompts import PromptConfig, build_prompts
from ...sam_assist.runtime import CHECKPOINTS
from ...sam_assist.scoring import RULES_VERSION, score_candidates

REPO_ROOT = Path(__file__).resolve().parents[3]
CKPT_DIR = REPO_ROOT / ".sam_checkpoints"

PRIMARY_MODEL = "sam2.1_hiera_small"
ESCALATE_MODEL = "sam2.1_hiera_base_plus"


def _ckpt_sha(model: str) -> str:
    """从 .sam_checkpoints/manifest.json 读 checkpoint SHA（缺失则空）。"""
    man = CKPT_DIR / "manifest.json"
    if not man.exists():
        return ""
    try:
        entries = json.loads(man.read_text(encoding="utf-8"))["entries"]
        return next(e["sha256"] for e in entries if e["model"] == model)
    except (StopIteration, KeyError, json.JSONDecodeError):
        return ""


def _default_limits(w: int, h: int) -> PhysicalLimits:
    """物理范围（与 scripts/run_sam_benchmark.py 一致，面积随图缩放）。"""
    return PhysicalLimits(min_area_px=400.0, max_area_px=0.6 * w * h,
                          min_aspect=0.2, max_aspect=5.0)


def _worker_request(model: str, out_dir: Path,
                    jobs: list[dict[str, Any]]) -> dict[str, Any]:
    images = []
    by_image: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        by_image.setdefault(job["image_sha"], []).append(job)
    for sha, group in by_image.items():
        img = group[0]["img"]
        images.append({
            "image_path": img["image_path"],
            "image_sha": sha,
            "photo_id": img["photo_id"],
            "width": img["width"], "height": img["height"],
            "instances": [{
                "instance_id": job["inst"].instance_id,
                "positive": list(job["ps"].positive_point),
                "negatives": [list(p) for p in job["ps"].negative_points],
                "coarse_box": list(job["ps"].coarse_box),
            } for job in group],
        })
    return {
        "_request_path": str(out_dir / f"request_{model}.json"),
        "model": model,
        "checkpoint": str(CKPT_DIR / f"{model}.pt"),
        "checkpoint_sha256": _ckpt_sha(model),
        "config": CHECKPOINTS[model]["config"],
        "out_dir": str(out_dir),
        "images": images,
    }


def _to_candidates(inst_resp: dict) -> list[SamCandidate]:
    out = []
    for c in inst_resp.get("candidates", []):
        from PIL import Image

        m = np.asarray(Image.open(c["mask_path"]).convert("L")) > 0
        out.append(SamCandidate(
            candidate_id=c["candidate_id"],
            mask=m.astype(np.uint8),
            iou_score=float(c.get("iou_score", 0.0)),
            stability_score=float(c.get("stability_score", 0.0)),
            area_px=float(c.get("area_px", 0)),
            bbox=tuple(c["bbox"]) if c.get("bbox") else None))
    return out


def run_sam_assist(store, *, images: list[dict[str, Any]],
                   worker: Any = None, out_root: Path | None = None,
                   primary: str = PRIMARY_MODEL,
                   escalate: str = ESCALATE_MODEL) -> dict[str, Any]:
    """对 images（photo_id/image_sha/width/height/image_path/instances
    [{instance_id,x,y,sku_raw_name}]）执行点引导 SAM，落库 lineage。"""
    if worker is None:
        from ...sam_assist.service import SAMWorkerClient
        worker = SAMWorkerClient()

    ts = time.strftime("%Y%m%d_%H%M%S")
    run_dir = Path(out_root) / f"sam_assist_{primary}_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    cfg = PromptConfig()
    jobs: list[dict[str, Any]] = []
    for img in images:
        inst_inputs = [InstanceInput(
            asset_id=i.get("instance_id", ""),
            photo_id=img["photo_id"], image_sha256=img["image_sha"],
            width=img["width"], height=img["height"],
            instance_id=i["instance_id"], x=float(i["x"]), y=float(i["y"]),
            sku_raw_name=i.get("sku_raw_name", ""))
            for i in img["instances"]]
        for inst in inst_inputs:
            ps = build_prompts(inst, inst_inputs,
                               box_frac_fn=lambda _name: None, cfg=cfg)
            jobs.append({"img": img, "image_sha": img["image_sha"],
                         "image_path": img["image_path"],
                         "inst": inst, "ps": ps})

    def _invoke(model: str, sub: list[dict[str, Any]]) -> dict:
        req = _worker_request(model, run_dir, sub)
        resp = worker.invoke(req)
        idx: dict[str, dict] = {}
        for r in resp.get("results", []):
            for ir in r.get("instances", []):
                idx[ir["instance_id"]] = ir
        return idx

    # 第一轮：Hiera Small（selected_masks 按图隔离，避免跨图形状冲突）
    resp_small = _invoke(primary, jobs)
    accepted: dict[str, Any] = {}
    difficult: list[dict[str, Any]] = []
    selected_by_image: dict[str, list[np.ndarray]] = {}
    for job in jobs:
        iid = job["inst"].instance_id
        sel = selected_by_image.setdefault(job["image_sha"], [])
        ir = resp_small.get(iid)
        result = _filter_job(job, ir, sel) if ir is not None else None
        if result is not None and result["decision"] == "accepted":
            accepted[iid] = {"job": job, "result": result,
                             "model": primary, "escalated_to": None}
        else:
            difficult.append({"job": job,
                              "small_result": result})

    # 第二轮：仅疑难实例升级 Base+（一次）
    if difficult:
        resp_big = _invoke(escalate, [d["job"] for d in difficult])
        for d in difficult:
            iid = d["job"]["inst"].instance_id
            sel = selected_by_image.setdefault(d["job"]["image_sha"], [])
            ir = resp_big.get(iid)
            result = _filter_job(d["job"], ir, sel) \
                if ir is not None else None
            if result is not None and result["decision"] == "accepted":
                accepted[iid] = {"job": d["job"], "result": result,
                                 "model": escalate,
                                 "escalated_to": escalate}
            else:
                # 仍无合格候选：manual_required（禁止回退比例框）
                accepted[iid] = {
                    "job": d["job"],
                    "result": result or {
                        "decision": "manual_required",
                        "selection_reason": "worker_missing_instance",
                        "best": None, "reject_reasons": []},
                    "model": escalate, "escalated_to": escalate}

    # 落库 lineage + 统计
    n_acc = n_manual = n_esc = 0
    for iid, rec in accepted.items():
        job, result = rec["job"], rec["result"]
        inst, ps, img = job["inst"], job["ps"], job["img"]
        best = result.get("best")
        decision = result["decision"]
        tight = tuple(float(v) for v in best.bbox) \
            if decision == "accepted" and best and best.bbox else None
        store.record_sam_lineage(
            instance_id=iid, photo_id=img["photo_id"],
            image_sha256=img["image_sha"],
            point_x=inst.x, point_y=inst.y,
            prompt_config_version=ps.config_version,
            positive_point=ps.positive_point,
            negative_points=list(ps.negative_points),
            coarse_box=ps.coarse_box, model=rec["model"],
            checkpoint_sha256=_ckpt_sha(rec["model"]),
            decision=decision, escalated_to=rec["escalated_to"],
            tight_box=tight,
            mask_sha256=result.get("mask_sha256"),
            mask_path=result.get("mask_path"),
            selection_reason=result.get("selection_reason", ""),
            rules_version=RULES_VERSION,
            reject_reasons=result.get("reject_reasons", []),
            run_dir=str(run_dir))
        if decision == "accepted":
            n_acc += 1
        else:
            n_manual += 1
        if rec["escalated_to"]:
            n_esc += 1

    return {
        "n_instances": len(jobs),
        "accepted": n_acc,
        "manual_required": n_manual,
        "escalated": n_esc,
        "run_dir": str(run_dir),
        "primary_model": primary,
        "escalate_model": escalate,
        "note": "manual_required 不含任何自动框；final box 只来自人工终态",
    }


def _filter_job(job: dict, ir: dict,
                selected_masks: list[np.ndarray]) -> dict[str, Any] | None:
    """对 worker 单实例响应做硬约束筛选，返回 decision/best/证据。"""
    img, inst, ps = job["img"], job["inst"], job["ps"]
    cands = _to_candidates(ir)
    if not cands:
        return None
    limits = _default_limits(img["width"], img["height"])
    fr = filter_candidates(
        cands, positive=tuple(ps.positive_point),
        other_points=[tuple(p) for p in ps.negative_points],
        roi=(0, 0, img["width"], img["height"]),
        limits=limits, selected_masks=selected_masks)
    best, reason, _rules = score_candidates(fr.candidates)
    reject_reasons = sorted({r for c in fr.candidates
                             for r in c.reject_reasons})
    mask_sha = mask_path = None
    if fr.decision == CandidateDecision.ACCEPTED and best is not None:
        selected_masks.append(best.mask)
        # mask 证据：沿用 worker 已落盘 mask 的候选路径/SHA
        for raw, c in zip(ir.get("candidates", []), fr.candidates):
            if c is best:
                mask_sha, mask_path = raw.get("mask_sha256"), \
                    raw.get("mask_path")
                break
        return {"decision": "accepted", "best": best,
                "selection_reason": reason,
                "reject_reasons": reject_reasons,
                "mask_sha256": mask_sha, "mask_path": mask_path}
    return {"decision": "manual_required", "best": None,
            "selection_reason": reason,
            "reject_reasons": reject_reasons,
            "mask_sha256": None, "mask_path": None}
