"""rq_v2 → Label Studio payload 构建契约（commit 8，任务书§十）。

纯构建逻辑测试（不连真实 LS）：
- assisted（double_review）/ blind（blind_manual）任务拆分与计数
- 每条 task 的 meta 契约（photo_id / image_sha256 / task_ref / review_mode / queue_version）
- filename 约定与本地 blob 存在性 fail-closed
- blind payload 序列化零模型信息（无 predictions/model_version/score/suggested）
- assisted 无 proposals 时 predictions 为空列表（不伪造）
- 重叠照片标记 overlap_photo_ids（assisted/blind 身份隔离证据）
- proposals 按 photo_id 精确匹配附加 predictions
"""
from __future__ import annotations

import hashlib
import json

import pytest

from src.review.ls_v2_payload import build_ls_v2_payloads


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _make_queue(tmp_path) -> tuple[dict, Path]:
    """合成小队列：10 项 = 7 double_review + 3 blind_manual，含 1 张重叠照片。"""
    photos = [f"ph{i:03d}" for i in range(9)]  # 9 张唯一照片
    shas = {p: _sha(p) for p in photos}
    # 前 7 张进 double_review；最后 3 张进 blind_manual；
    # 其中 ph006 同时出现在两种模式（重叠）。
    items = []
    for p in photos[:7]:
        items.append({"photo_id": p, "sha256": shas[p], "review_mode": "double_review"})
    for p in ["ph006", "ph007", "ph008"]:
        items.append({"photo_id": p, "sha256": shas[p], "review_mode": "blind_manual"})
    queue = {"queue_version": "rq_v2", "protocol": "diagnostic_v1", "items": items}

    blobs = tmp_path / "blobs"
    for p, sha in shas.items():
        d = blobs / sha[:2]
        d.mkdir(parents=True, exist_ok=True)
        (d / sha).write_bytes(f"jpeg-{p}".encode())
    return queue, blobs


@pytest.fixture()
def env(tmp_path):
    queue, blobs = _make_queue(tmp_path)
    return queue, blobs


def test_structure_and_counts(env):
    queue, blobs = env
    out = build_ls_v2_payloads(queue, blobs)
    assert set(out) == {"assisted", "blind", "evidence"}
    assert len(out["assisted"]) == 7  # double_review 数
    assert len(out["blind"]) == 3     # blind_manual 数


def test_meta_contract(env):
    queue, blobs = env
    out = build_ls_v2_payloads(queue, blobs)
    for side in ("assisted", "blind"):
        for task in out[side]:
            meta = task["meta"]
            assert meta["photo_id"]
            assert meta["image_sha256"]
            assert meta["queue_version"] == "rq_v2"
            assert meta["review_mode"] in ("double_review", "blind_manual")
            expect_ref = f"rt_{meta['review_mode'][:5]}_{meta['photo_id']}_{meta['image_sha256'][:16]}"
            assert meta["task_ref"] == expect_ref
    assert out["assisted"][0]["meta"]["review_mode"] == "double_review"
    assert out["blind"][0]["meta"]["review_mode"] == "blind_manual"


def test_filename_and_blob_path(env):
    queue, blobs = env
    out = build_ls_v2_payloads(queue, blobs)
    for side in ("assisted", "blind"):
        for task in out[side]:
            sha = task["meta"]["image_sha256"]
            assert task["filename"] == f"{task['meta']['photo_id']}_{sha[:16]}.jpg"
            blob = Path(task["blob_path"])
            assert blob.exists()
            assert blob == blobs / sha[:2] / sha


def test_missing_blob_fail_closed(env):
    queue, blobs = env
    # 删除其中一张 blob → 必须抛错（fail-closed，不允许部分构建）
    sha = queue["items"][0]["sha256"]
    (blobs / sha[:2] / sha).unlink()
    with pytest.raises(Exception):
        build_ls_v2_payloads(queue, blobs)


def test_blind_payload_zero_model_info(env):
    queue, blobs = env
    out = build_ls_v2_payloads(queue, blobs)
    text = json.dumps(out["blind"], ensure_ascii=False)
    for forbidden in ("predictions", "model_version", "score", "suggested"):
        assert forbidden not in text


def test_assisted_no_proposals_empty_predictions_not_fabricated(env):
    queue, blobs = env
    out = build_ls_v2_payloads(queue, blobs)
    for task in out["assisted"]:
        assert task["predictions"] == []


def test_evidence_overlap(env):
    queue, blobs = env
    out = build_ls_v2_payloads(queue, blobs)
    ev = out["evidence"]
    assert ev["overlap_photo_ids"] == ["ph006"]
    assert ev["n_assisted"] == 7
    assert ev["n_blind"] == 3
    assert ev["n_unique_photos"] == 9
    assert ev["queue_version"] == "rq_v2"
    # 重叠照片在两个项目各出现一次（身份隔离：同图不同 task_ref）
    a_refs = {t["meta"]["photo_id"]: t["meta"]["task_ref"] for t in out["assisted"]}
    b_refs = {t["meta"]["photo_id"]: t["meta"]["task_ref"] for t in out["blind"]}
    assert "ph006" in a_refs and "ph006" in b_refs
    assert a_refs["ph006"] != b_refs["ph006"]


def test_proposals_exact_photo_match(env):
    queue, blobs = env
    result = [{"from_name": "box", "to_name": "image", "type": "rectanglelabels",
               "value": {"x": 1, "y": 2, "width": 30, "height": 40,
                         "rectanglelabels": ["product"]}}]
    proposals = [
        {"photo_id": "ph000", "score": 0.91, "model_version": "yolo_v9", "result": result},
        {"photo_id": "NOT_IN_QUEUE", "score": 0.99, "model_version": "yolo_v9", "result": result},
    ]
    out = build_ls_v2_payloads(queue, blobs, proposals=proposals)
    by_photo = {t["meta"]["photo_id"]: t for t in out["assisted"]}
    preds = by_photo["ph000"]["predictions"]
    assert len(preds) == 1
    assert preds[0]["score"] == 0.91
    assert preds[0]["model_version"] == "yolo_v9"
    assert preds[0]["result"] == result
    # 其余 assisted 任务不得被波及；blind 依旧零模型信息
    assert all(t["predictions"] == [] for pid, t in by_photo.items() if pid != "ph000")
    assert "NOT_IN_QUEUE" not in by_photo
    assert json.dumps(out["blind"], ensure_ascii=False).find("score") < 0
