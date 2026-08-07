"""rq_v2 → Label Studio payload 纯构建模块（commit 8，任务书§十）。

把已发布的 review_queue_diag_v2 拆成两个 LS 项目的待导入 payload：
- assisted（double_review）：双审，允许附模型 predictions（无 proposals 时为空列表，不伪造）；
- blind（blind_manual）：盲审，payload 中零模型信息（序列化文本不含
  predictions / model_version / score / suggested）。

纯构建逻辑，不依赖网络、不 import src.ls_platform（保持 review 包独立，
LSClient 由驱动脚本 scripts/create_ls_v2_projects.py 持有）。
blob 缺失即抛错（fail-closed），不允许部分构建。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

MODE_ASSISTED = "double_review"
MODE_BLIND = "blind_manual"


def task_ref_for(review_mode: str, photo_id: str, sha256: str) -> str:
    """平台库 task_id 约定：rt_{mode[:5]}_{photo_id}_{sha[:16]}。"""
    return f"rt_{review_mode[:5]}_{photo_id}_{sha256[:16]}"


def _build_task(item: dict, blobs_dir: Path, queue_version: str,
                with_predictions: bool,
                preds_by_photo: dict[str, list[dict]] | None) -> dict:
    photo_id = item["photo_id"]
    sha = item["sha256"]
    mode = item["review_mode"]
    blob = blobs_dir / sha[:2] / sha
    if not blob.exists():
        raise FileNotFoundError(
            f"blob 缺失（fail-closed，拒绝构建）: photo_id={photo_id} sha256={sha} path={blob}")
    task: dict[str, Any] = {
        "filename": f"{photo_id}_{sha[:16]}.jpg",
        "blob_path": str(blob),
        "meta": {
            "photo_id": photo_id,
            "image_sha256": sha,
            "task_ref": task_ref_for(mode, photo_id, sha),
            "review_mode": mode,
            "queue_version": queue_version,
        },
    }
    if with_predictions:
        preds = (preds_by_photo or {}).get(photo_id, [])
        task["predictions"] = [
            {"score": p["score"], "model_version": p["model_version"], "result": p["result"]}
            for p in preds
        ]
    # blind：不附 predictions 键，保证序列化后零模型信息
    return task


def build_ls_v2_payloads(queue: dict, blobs_dir: Path | str,
                         proposals: list[dict] | None = None) -> dict:
    """构建 assisted / blind 两个 LS 项目的导入 payload。

    queue:     review_queue_diag_v2.json 反序列化结果（含 items / queue_version）
    blobs_dir: blob 根目录，布局 {sha[:2]}/{sha}
    proposals: 可选模型提案 [{photo_id, score, model_version, result}, ...]，
               仅按 photo_id 精确匹配进入 assisted predictions
    返回 {"assisted": [...], "blind": [...], "evidence": {...}}
    """
    blobs_dir = Path(blobs_dir)
    queue_version = queue.get("queue_version", "rq_v2")
    items = queue["items"]

    preds_by_photo: dict[str, list[dict]] = {}
    for p in proposals or []:
        preds_by_photo.setdefault(p["photo_id"], []).append(p)

    assisted: list[dict] = []
    blind: list[dict] = []
    photos_by_mode: dict[str, set[str]] = {"assisted": set(), "blind": set()}
    unique_shas: set[tuple[str, str]] = set()
    for item in items:
        unique_shas.add((item["photo_id"], item["sha256"]))
        if item["review_mode"] == MODE_ASSISTED:
            assisted.append(_build_task(item, blobs_dir, queue_version, True, preds_by_photo))
            photos_by_mode["assisted"].add(item["photo_id"])
        elif item["review_mode"] == MODE_BLIND:
            blind.append(_build_task(item, blobs_dir, queue_version, False, None))
            photos_by_mode["blind"].add(item["photo_id"])
        else:
            raise ValueError(f"未知 review_mode: {item['review_mode']!r}（photo_id={item['photo_id']}）")

    evidence = {
        "queue_version": queue_version,
        "n_assisted": len(assisted),
        "n_blind": len(blind),
        "n_unique_photos": len(unique_shas),
        "overlap_photo_ids": sorted(photos_by_mode["assisted"] & photos_by_mode["blind"]),
    }
    return {"assisted": assisted, "blind": blind, "evidence": evidence}
