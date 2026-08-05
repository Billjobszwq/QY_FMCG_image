"""U4-4 红测试：分批扩展 100→500→2,000→全 eligible + 质量门。

手册 §七/U4：先跑 100 张 E2E，再按 500→2,000→全 eligible 扩展；
每批质量不达标即停；人工未完成必须 waiting_human，禁止伪造通过。

门控口径（诚实、可机器验证）：
- 批次未完成（存在非终态任务）→ waiting_human（不得扩展）；
- 批次完成但双审一致率（未经仲裁终态 / 全部双审终态）< 0.8
  → gate_failed（扩展永久停止，需人工整改）；
- 批次完成且一致率达标 → ready，按阶梯取下一批 size。
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


def _write_queue(tmp_path: Path, items: list[dict],
                 protocol="diagnostic_v1") -> Path:
    f = tmp_path / f"q_{protocol}.json"
    f.write_text(json.dumps({"queue_version": "rq_v1",
                             "protocol": protocol,
                             "items": items}, ensure_ascii=False),
                 encoding="utf-8")
    return f


def _double_items(n: int, prefix: str) -> list[dict]:
    return [{"photo_id": f"{prefix}{i}", "sha256": f"{prefix}{i:060d}",
             "review_mode": "double_review",
             "requires_second_review": True, "status": "pending"}
            for i in range(n)]


def _finalize_agreed(store, task_row, a1="annot_a", a2="annot_b",
                     box=(1, 2, 3, 4)):
    """两人框一致 → 终态（不经仲裁）。"""
    from src.platform.annotate.review import claim_task, submit_review

    claim_task(store, task_row["claim_token"], actor=a1)
    submit_review(store, task_id=task_row["task_id"], actor=a1,
                  verdict="accepted", box=box)
    submit_review(store, task_id=task_row["task_id"], actor=a2,
                  verdict="accepted", box=box)


def _finalize_arbitrated(store, task_row):
    """两人分歧 → 仲裁终态（计为不一致）。"""
    from src.platform.annotate.review import (claim_task, submit_review)

    claim_task(store, task_row["claim_token"], actor="annot_a")
    submit_review(store, task_id=task_row["task_id"], actor="annot_a",
                  verdict="accepted", box=(1, 2, 3, 4))
    submit_review(store, task_id=task_row["task_id"], actor="annot_b",
                  verdict="accepted", box=(5, 6, 7, 8))
    submit_review(store, task_id=task_row["task_id"], actor="arb_x",
                  verdict="adjudicated", box=(9, 9, 9, 9), role="arbiter")


class TestBatchGate:
    def test_unfinished_batch_waiting_human(self, store, tmp_path):
        from src.platform.annotate.batches import next_batch_plan
        from src.platform.annotate.review import import_review_queue

        import_review_queue(
            store, _write_queue(tmp_path, _double_items(3, "d")))
        plan = next_batch_plan(store)
        assert plan["status"] == "waiting_human", \
            "人工未完成只能 waiting_human，禁止伪造通过"
        assert plan["stage"] == "diagnostic_v1"
        assert plan["n_total"] == 3 and plan["n_finalized"] == 0

    def test_low_agreement_gate_failed(self, store, tmp_path):
        from src.platform.annotate.batches import (expand_review_batch,
                                                   next_batch_plan)
        from src.platform.annotate.review import import_review_queue

        import_review_queue(
            store, _write_queue(tmp_path, _double_items(2, "d")))
        rows = store.list_review_tasks()
        _finalize_agreed(store, rows[0])
        _finalize_arbitrated(store, rows[1])
        plan = next_batch_plan(store)
        # 一致率 1/2 = 0.5 < 0.8 → 批次质量不达标即停
        assert plan["status"] == "gate_failed"
        assert plan["agreement_rate"] == pytest.approx(0.5)
        with pytest.raises(ValueError):
            expand_review_batch(store, items=_double_items(5, "x"),
                                protocol="batch1_v1")

    def test_gate_pass_then_ladder(self, store, tmp_path):
        from src.platform.annotate.batches import (expand_review_batch,
                                                   next_batch_plan)
        from src.platform.annotate.review import import_review_queue

        import_review_queue(
            store, _write_queue(tmp_path, _double_items(2, "d")))
        for row in store.list_review_tasks():
            _finalize_agreed(store, row)
        plan = next_batch_plan(store)
        assert plan["status"] == "ready"
        assert plan["next_size"] == 100, "诊断批通过 → 下一批 100"

        out = expand_review_batch(store, items=_double_items(100, "b1"),
                                  protocol="batch1_v1")
        assert out["imported"] == 100
        plan = next_batch_plan(store)
        assert plan["stage"] == "batch1_v1"
        assert plan["status"] == "waiting_human", \
            "新批未审完不得继续扩展"

    def test_ladder_sizes_and_idempotent_expand(self, store, tmp_path):
        from src.platform.annotate.batches import (BATCH_LADDER,
                                                   expand_review_batch,
                                                   next_batch_plan)
        from src.platform.annotate.review import import_review_queue

        assert BATCH_LADDER == (100, 500, 2000, -1)
        # 逐级推进：诊断→batch1→batch2，阶梯 100→500→2000
        import_review_queue(
            store, _write_queue(tmp_path, _double_items(1, "d")))
        for row in store.list_review_tasks():
            _finalize_agreed(store, row)
        expand_review_batch(store, items=_double_items(2, "b1"),
                            protocol="batch1_v1")
        # 幂等：同 protocol 同项重复扩展不新增
        out = expand_review_batch(store, items=_double_items(2, "b1"),
                                  protocol="batch1_v1")
        assert out["imported"] == 0
        for row in [t for t in store.list_review_tasks()
                    if t["protocol"] == "batch1_v1"]:
            _finalize_agreed(store, row)
        plan = next_batch_plan(store)
        assert plan["status"] == "ready" and plan["next_size"] == 500
