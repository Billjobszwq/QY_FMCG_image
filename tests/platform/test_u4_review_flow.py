"""U4-2 红测试：标注审核闭环状态机。

手册 §七/U4 指令：链接派发、认领、单审、10% 盲抽、异常双审、仲裁、
final box 和不可变导出；SAM prediction 永远不是最终标注；
final_box 只能来自人工终态；队列不得伪造完成。

当前平台无 review_task_v1/review_event_v1，本测试必须 RED。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture()
def store(tmp_path: Path):
    from src.platform.data.store import PlatformStore

    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _queue_file(tmp_path: Path, n_double=6, n_blind=4) -> Path:
    items = []
    for i in range(n_double):
        items.append({"photo_id": f"d{i}", "sha256": f"{i:064d}",
                      "review_mode": "double_review",
                      "requires_second_review": True, "status": "pending"})
    for i in range(n_blind):
        items.append({"photo_id": f"b{i}", "sha256": f"b{i:063d}",
                      "review_mode": "blind_review",
                      "requires_second_review": False, "status": "pending"})
    f = tmp_path / "rq.json"
    f.write_text(json.dumps({
        "queue_version": "rq_v1", "protocol": "diagnostic_v1",
        "n_double": n_double, "n_blind": n_blind, "items": items,
    }, ensure_ascii=False), encoding="utf-8")
    return f


class TestImportAndDispatch:
    def test_import_idempotent_and_counts(self, store, tmp_path):
        from src.platform.annotate.review import import_review_queue

        f = _queue_file(tmp_path)
        out = import_review_queue(store, f, seed=20260804)
        assert out["imported"] == 10 and out["total"] == 10
        out2 = import_review_queue(store, f, seed=20260804)
        assert out2["imported"] == 0, "重复导入必须幂等"

    def test_blind_sampling_10_percent(self, store, tmp_path):
        from src.platform.annotate.review import (blind_sample,
                                                  import_review_queue)

        import_review_queue(store, _queue_file(tmp_path, 20, 0),
                            seed=20260804)
        s = blind_sample(store, ratio=0.1, seed=20260804)
        assert s["selected"] == 2, "10% 盲抽（20→2）"
        s2 = blind_sample(store, ratio=0.1, seed=20260804)
        assert s2["task_ids"] == s["task_ids"], "同 seed 盲抽必须可复现"

    def test_claim_by_link_token(self, store, tmp_path):
        from src.platform.annotate.review import (claim_task,
                                                  import_review_queue,
                                                  task_view)

        import_review_queue(store, _queue_file(tmp_path, 1, 0))
        row = store.list_review_tasks()[0]
        c = claim_task(store, row["claim_token"], actor="annot_a")
        assert c["claimed"] is True
        v = task_view(store, row["claim_token"])
        assert v["claimed_by"] == "annot_a" and v["status"] == "claimed"
        c2 = claim_task(store, row["claim_token"], actor="annot_b")
        assert c2["claimed"] is False, "已被认领的任务不得二次认领"

    def test_same_photo_two_modes_both_imported(self, store, tmp_path):
        """真实队列口径：同一照片的双审项与盲抽项必须各自成任务。"""
        from src.platform.annotate.review import import_review_queue

        f = tmp_path / "alias.json"
        sha = "a" * 64
        f.write_text(json.dumps({"queue_version": "rq_v1", "items": [
            {"photo_id": "p1", "sha256": sha,
             "review_mode": "double_review",
             "requires_second_review": True, "status": "pending"},
            {"photo_id": "p1", "sha256": sha,
             "review_mode": "blind_manual",
             "requires_second_review": True, "status": "pending"},
        ]}), encoding="utf-8")
        out = import_review_queue(store, f)
        assert out["imported"] == 2, "盲抽别名项不得被幂等键吞掉"
        assert import_review_queue(store, f)["imported"] == 0

    @pytest.mark.skipif(
        not (Path(__file__).resolve().parents[2]
             / ".review_queue/review_queue_diag_v1.json").exists(),
        reason="真实队列文件不在仓库内")
    def test_real_queue_250_import_idempotent(self, store):
        """真实 .review_queue 250 条 pending 全量接入且幂等。"""
        from src.platform.annotate.review import import_review_queue

        rq = (Path(__file__).resolve().parents[2]
              / ".review_queue/review_queue_diag_v1.json")
        out = import_review_queue(store, rq, seed=20260804)
        assert out["imported"] == 250 and out["total"] == 250
        out2 = import_review_queue(store, rq, seed=20260804)
        assert out2["imported"] == 0 and out2["total"] == 250


class TestReviewFlow:
    def _claim_first(self, store, tmp_path, mode="double_review"):
        from src.platform.annotate.review import (claim_task,
                                                  import_review_queue)

        n_d = 1 if mode == "double_review" else 0
        n_b = 0 if mode == "double_review" else 1
        import_review_queue(store, _queue_file(tmp_path, n_d, n_b))
        row = store.list_review_tasks()[0]
        claim_task(store, row["claim_token"], actor="annot_a")
        return row

    def test_single_review_blind_finalizes(self, store, tmp_path):
        from src.platform.annotate.review import (final_box,
                                                  submit_review)

        row = self._claim_first(store, tmp_path, "blind_review")
        r = submit_review(store, task_id=row["task_id"], actor="annot_a",
                          verdict="accepted", box=(1, 2, 3, 4))
        assert r["finalized"] is True, "单审（盲审）一次提交即终态"
        assert final_box(store, row["task_id"]) == [1, 2, 3, 4]

    def test_double_review_disagreement_goes_arbitration(
            self, store, tmp_path):
        from src.platform.annotate.review import (final_box,
                                                  submit_review)

        row = self._claim_first(store, tmp_path, "double_review")
        r1 = submit_review(store, task_id=row["task_id"], actor="annot_a",
                           verdict="accepted", box=(1, 2, 3, 4))
        assert r1["finalized"] is False and r1["needs_second"] is True
        # 第二人不同框 → 分歧 → 仲裁
        r2 = submit_review(store, task_id=row["task_id"], actor="annot_b",
                           verdict="accepted", box=(5, 6, 7, 8))
        assert r2["finalized"] is False and r2["needs_arbitration"] is True
        assert final_box(store, row["task_id"]) is None, \
            "仲裁前不得有 final_box"
        r3 = submit_review(store, task_id=row["task_id"], actor="arb_x",
                           verdict="adjudicated", box=(9, 9, 9, 9),
                           role="arbiter")
        assert r3["finalized"] is True
        assert final_box(store, row["task_id"]) == [9, 9, 9, 9]

    def test_double_review_agreement_finalizes(self, store, tmp_path):
        from src.platform.annotate.review import (final_box,
                                                  submit_review)

        row = self._claim_first(store, tmp_path, "double_review")
        submit_review(store, task_id=row["task_id"], actor="annot_a",
                      verdict="accepted", box=(1, 2, 3, 4))
        r2 = submit_review(store, task_id=row["task_id"], actor="annot_b",
                           verdict="accepted", box=(1, 2, 3, 4))
        assert r2["finalized"] is True
        assert final_box(store, row["task_id"]) == [1, 2, 3, 4]

    def test_same_actor_cannot_review_twice(self, store, tmp_path):
        from src.platform.annotate.review import submit_review

        row = self._claim_first(store, tmp_path, "double_review")
        submit_review(store, task_id=row["task_id"], actor="annot_a",
                      verdict="accepted", box=(1, 2, 3, 4))
        with pytest.raises(ValueError):
            submit_review(store, task_id=row["task_id"], actor="annot_a",
                          verdict="accepted", box=(1, 2, 3, 4))


class TestExportAndImmutability:
    def test_export_immutable_json(self, store, tmp_path):
        from src.platform.annotate.review import (export_review,
                                                  import_review_queue,
                                                  submit_review,
                                                  claim_task)

        import_review_queue(store, _queue_file(tmp_path, 1, 1))
        row = store.list_review_tasks()[0]
        claim_task(store, row["claim_token"], actor="annot_a")
        submit_review(store, task_id=row["task_id"], actor="annot_a",
                      verdict="accepted", box=(1, 2, 3, 4))
        out = export_review(store, tmp_path / "export.json")
        data = json.loads(Path(out["path"]).read_text())
        assert data["n_tasks"] == 2 and data["n_finalized"] == 1
        assert out["sha256"] and len(out["sha256"]) == 64

    def test_tables_immutable(self, store, tmp_path):
        import sqlite3

        from src.platform.annotate.review import import_review_queue

        import_review_queue(store, _queue_file(tmp_path, 1, 0))
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute(
                "UPDATE review_task_v1 SET status='finalized'")
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute("DELETE FROM review_task_v1")
