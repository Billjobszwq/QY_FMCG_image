"""SAM 候选 → LS prediction 导入（手册§一.9 / §七）。

主环境侧编排：
1. 读取 worker 返回的候选（mask 落盘路径），执行硬约束筛选与评分；
2. accepted → to_ls_prediction（仅 prediction，is_final_annotation=False）；
3. manual_required → 不生成框，进入人工队列；
4. 每实例写完整证据（EvidenceRecord），追加式留痕。

本模块从不创建/修改 annotation（由测试契约锁定）。"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .candidates import PhysicalLimits, filter_candidates, mask_to_boxes
from .contracts import SamCandidate
from .evidence import EvidenceRecord, EvidenceStore
from .prediction import to_ls_prediction
from .scoring import score_candidates


@dataclass
class ImageOutcome:
    image_sha256: str
    predictions: list = field(default_factory=list)   # LS prediction dict
    evidence: list = field(default_factory=list)      # EvidenceRecord
    manual_required: list = field(default_factory=list)  # instance_id 列表


def _default_mask_loader(cand: dict) -> np.ndarray:
    m = cv2.imread(cand["mask_path"], cv2.IMREAD_GRAYSCALE)
    if m is None:
        raise FileNotFoundError(f"mask 不存在: {cand['mask_path']}")
    return (m > 127).astype(np.uint8)


def process_image(worker_result: dict, request_image: dict, *,
                  model_id: str, checkpoint_sha256: str, code_commit: str,
                  limits: PhysicalLimits, mask_loader=None) -> ImageOutcome:
    """对单张图的 worker 结果执行筛选/评分/格式化。"""
    loader = mask_loader or _default_mask_loader
    sha = request_image["image_sha"]
    width, height = request_image["width"], request_image["height"]
    all_pts = [tuple(i["positive"]) for i in request_image["instances"]]
    req_by_id = {i["instance_id"]: i for i in request_image["instances"]}

    out = ImageOutcome(image_sha256=sha)
    for inst_res in worker_result["instances"]:
        iid = inst_res["instance_id"]
        inst_req = req_by_id[iid]
        positive = tuple(inst_req["positive"])
        others = [p for p in all_pts if p != positive]

        cands = []
        for c in inst_res["candidates"]:
            cands.append(SamCandidate(
                candidate_id=c["candidate_id"], mask=loader(c),
                iou_score=c["iou_score"], stability_score=c["stability_score"]))
        fr = filter_candidates(cands, positive, others,
                               roi=tuple(inst_req["coarse_box"]),
                               limits=limits, selected_masks=[])
        best, reason, rules = score_candidates(fr.candidates)

        auto_box = None
        if best is not None:
            auto_box = mask_to_boxes(best.mask)["visible_tight_box"]
            out.predictions.append(to_ls_prediction(
                width, height, auto_box, model_version=model_id,
                score=best.iou_score))
        else:
            out.manual_required.append(iid)

        out.evidence.append(EvidenceRecord(
            photo_id=request_image.get("photo_id", ""),
            image_sha256=sha,
            instance_id=iid,
            original_point=positive,
            prompts={
                "positive": positive,
                "negatives": [tuple(p) for p in inst_req.get("negatives", [])],
                "coarse_box": tuple(inst_req["coarse_box"]),
                "coarse_only": True,
                "prompt_config_version": inst_req.get(
                    "prompt_config_version", ""),
            },
            model_id=model_id,
            checkpoint_sha256=checkpoint_sha256,
            code_commit=code_commit,
            params={"limits": {
                "min_area_px": limits.min_area_px,
                "max_area_px": limits.max_area_px,
                "min_aspect": limits.min_aspect,
                "max_aspect": limits.max_aspect}},
            candidates=[{
                "candidate_id": c.candidate_id,
                "iou_score": c.iou_score,
                "stability_score": c.stability_score,
                "area_px": c.area_px,
                "bbox": c.bbox,
                "reject_reasons": list(c.reject_reasons),
            } for c in fr.candidates],
            selection_reason=reason,
            rules_version=rules,
            auto_box=auto_box,
        ))
    return out


def import_to_ls(client, task_id: int, outcome: ImageOutcome,
                 model_version: str) -> dict | None:
    """把 accepted 框以单个 prediction 写入 LS task。无 accepted 则不写。"""
    if not outcome.predictions:
        return None
    results = [p["result"][0] for p in outcome.predictions]
    score = max(p["score"] for p in outcome.predictions)
    return client.create_prediction(task_id, results, score=score,
                                    model_version=model_version)


def record_evidence(store: EvidenceStore, outcome: ImageOutcome) -> None:
    for rec in outcome.evidence:
        store.append(rec)
