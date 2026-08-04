"""人工审核队列契约测试（手册§七）。

锁定行为：
- diagnostic 前 n_double（默认200）张全部进入双审队列；
- 固定 seed 盲抽 ≥ n_blind（默认50）张，annotator 看不到 SAM 结果；
- 队列项一律 pending，禁止生成任何伪造的审核结果；
- 盲抽集与双审前段允许重叠，但必须独立标注模式；
- 队列可确定性重建（同输入同 seed → 相同队列）。
"""
from __future__ import annotations

import json

import pytest

from src.review.human_review_queue import (
    build_review_queue,
    queue_status,
    write_queue,
)


def _photos(n: int):
    return [{"photo_id": str(i), "sha256": f"{i:064x}"} for i in range(n)]


class TestQueueBuild:
    def test_first_200_all_double_review(self):
        q = build_review_queue(_photos(500), seed=20260804)
        double = [i for i in q["items"] if i["review_mode"] == "double_review"]
        assert len(double) == 200
        assert [i["photo_id"] for i in double] == [str(i) for i in range(200)]

    def test_blind_sample_at_least_50_and_deterministic(self):
        photos = _photos(500)
        q1 = build_review_queue(photos, seed=20260804)
        q2 = build_review_queue(photos, seed=20260804)
        blind = [i for i in q1["items"] if i["review_mode"] == "blind_manual"]
        assert len(blind) >= 50
        assert len({i["photo_id"] for i in blind}) == len(blind)
        assert q1 == q2  # 确定性

    def test_blind_sample_differs_with_seed(self):
        photos = _photos(500)
        b1 = {i["photo_id"] for i in build_review_queue(photos, seed=1)["items"]
              if i["review_mode"] == "blind_manual"}
        b2 = {i["photo_id"] for i in build_review_queue(photos, seed=2)["items"]
              if i["review_mode"] == "blind_manual"}
        assert b1 != b2

    def test_all_items_pending_no_fabricated_result(self):
        q = build_review_queue(_photos(500), seed=20260804)
        for it in q["items"]:
            assert it["status"] == "pending"
            assert "annotator_1" not in it or it["annotator_1"] is None
            assert "final_box" not in it or it["final_box"] is None
        assert q["status"] == "awaiting_human_review"

    def test_small_pool_raises_when_blind_impossible(self):
        # 不足盲抽最低数量时 fail-closed，不允许静默缩减（手册§七）
        with pytest.raises(ValueError):
            build_review_queue(_photos(30), seed=1, n_blind=50)

    def test_schema_fields_complete(self):
        q = build_review_queue(_photos(500), seed=20260804)
        assert q["protocol"] == "diagnostic_v1"
        it = q["items"][0]
        for k in ("photo_id", "sha256", "review_mode", "status",
                  "requires_second_review"):
            assert k in it
        double = [i for i in q["items"] if i["review_mode"] == "double_review"]
        assert all(i["requires_second_review"] for i in double)


class TestQueueStatus:
    def test_status_counts_and_blocking(self):
        q = build_review_queue(_photos(500), seed=20260804)
        st = queue_status(q)
        assert st["status"] == "awaiting_human_review"
        assert st["pending"] == len(q["items"])
        assert st["done"] == 0
        assert "双审未开始" in st["blockers"][0] or st["blockers"]

    def test_status_complete(self):
        q = build_review_queue(_photos(500), seed=20260804)
        for it in q["items"]:
            it["status"] = "done"
        st = queue_status(q)
        assert st["pending"] == 0
        assert st["status"] == "ready_for_truebox_export"


class TestWriteQueue:
    def test_write_is_append_ledger_and_refuses_overwrite(self, tmp_path):
        q = build_review_queue(_photos(500), seed=20260804)
        p = tmp_path / "review_queue.json"
        write_queue(q, p)
        assert json.loads(p.read_text())["protocol"] == "diagnostic_v1"
        # 已存在且非空时禁止覆盖（证据链不可变）
        with pytest.raises(FileExistsError):
            write_queue(q, p)
