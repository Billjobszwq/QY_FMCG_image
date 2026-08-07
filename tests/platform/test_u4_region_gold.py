"""区域级 human_final 金标准契约（指令第九节）：

- 区域真值只能经人工 submit_review 提交（prediction 永不进入）；
- sku_label 必须在 Registry，否则 fail-closed；unknown/new_packaging 合法弃权；
- 双审一致 → human_final；分歧 → conflict 待仲裁；仲裁 → gold_verified；
- submitted/conflict 不得进入训练（usable_for_training 排除）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REG = {"可口可乐500ml": {"sku_id": "QY_KK_000001",
                       "name": "可口可乐500ml", "class_id": 1}}


@pytest.fixture()
def store(tmp_path: Path):
    from src.platform.data.store import PlatformStore

    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _import_one(store, tmp_path: Path, mode: str, second: bool) -> str:
    from src.platform.annotate.review import import_review_queue

    f = tmp_path / "rq.json"
    f.write_text(json.dumps({
        "queue_version": "rq_v1", "protocol": "diag",
        "items": [{"photo_id": "p1", "sha256": "ab" * 32,
                   "review_mode": mode,
                   "requires_second_review": second,
                   "status": "pending"}],
    }), encoding="utf-8")
    import_review_queue(store, f)
    return store.list_review_tasks()[0]["task_id"]


def _region(region_id="r1", label="可口可乐500ml"):
    return {"region_id": region_id, "box": [10, 20, 110, 220],
            "sku_label": label, "package_version_id": "pkg_v1",
            "evidence": {"zoom": 2}, "group_store": "store_a",
            "group_session": "s1", "near_dup_group": "nd1"}


def test_double_review_agreement_yields_human_final(store, tmp_path):
    from src.platform.annotate.review import gold_region_report, submit_review

    tid = _import_one(store, tmp_path, "double_review", True)
    for actor in ("alice", "bob"):
        submit_review(store, task_id=tid, actor=actor, verdict="accepted",
                      box=(0, 0, 100, 100), regions=[_region()],
                      registry=REG)
    rep = gold_region_report(store)
    assert rep["counts"]["human_final"] == 1
    assert rep["usable_for_training"] == 1
    assert rep["photos_with_gold"] == 1
    r = rep["regions"][0]
    assert r["sku_id"] == "QY_KK_000001" and r["sku_name"] == "可口可乐500ml"
    assert r["group_store"] == "store_a" and r["near_dup_group"] == "nd1"


def test_single_submit_not_final_until_second_review(store, tmp_path):
    from src.platform.annotate.review import gold_region_report, submit_review

    tid = _import_one(store, tmp_path, "double_review", True)
    submit_review(store, task_id=tid, actor="alice", verdict="accepted",
                  box=(0, 0, 100, 100), regions=[_region()], registry=REG)
    rep = gold_region_report(store)
    assert rep["counts"] == {"submitted": 1, "human_final": 0,
                             "gold_verified": 0, "conflict": 0}
    assert rep["usable_for_training"] == 0


def test_double_review_disagreement_is_conflict(store, tmp_path):
    from src.platform.annotate.review import gold_region_report, submit_review

    tid = _import_one(store, tmp_path, "double_review", True)
    submit_review(store, task_id=tid, actor="alice", verdict="accepted",
                  box=(0, 0, 100, 100), regions=[_region()], registry=REG)
    submit_review(store, task_id=tid, actor="bob", verdict="accepted",
                  box=(0, 0, 100, 100),
                  regions=[_region(label="unknown")], registry=REG)
    rep = gold_region_report(store)
    assert rep["counts"]["conflict"] == 2  # 两个不一致结论都待仲裁
    assert rep["usable_for_training"] == 0


def test_arbitration_yields_gold_verified_without_double_count(store, tmp_path):
    from src.platform.annotate.review import gold_region_report, submit_review

    tid = _import_one(store, tmp_path, "double_review", True)
    for actor, label in (("alice", "可口可乐500ml"), ("bob", "unknown")):
        submit_review(store, task_id=tid, actor=actor, verdict="accepted",
                      box=(0, 0, 100, 100), regions=[_region(label=label)],
                      registry=REG)
    submit_review(store, task_id=tid, actor="admin", verdict="adjudicated",
                  box=(0, 0, 100, 100),
                  regions=[_region(label="可口可乐500ml")],
                  role="arbiter", registry=REG)
    rep = gold_region_report(store)
    assert rep["counts"]["gold_verified"] == 1
    assert rep["usable_for_training"] == 1
    assert any(r["final_status"] == "superseded" for r in rep["regions"])


def test_single_review_mode_direct_human_final(store, tmp_path):
    from src.platform.annotate.review import gold_region_report, submit_review

    tid = _import_one(store, tmp_path, "blind_review", False)
    submit_review(store, task_id=tid, actor="alice", verdict="accepted",
                  box=(0, 0, 100, 100), regions=[_region()], registry=REG)
    rep = gold_region_report(store)
    assert rep["counts"]["human_final"] == 1


def test_out_of_registry_label_rejected_fail_closed(store, tmp_path):
    from src.platform.annotate.review import submit_review

    tid = _import_one(store, tmp_path, "blind_review", False)
    with pytest.raises(ValueError, match="不在 Registry"):
        submit_review(store, task_id=tid, actor="alice", verdict="accepted",
                      box=(0, 0, 100, 100),
                      regions=[_region(label="不存在SKU")], registry=REG)
    assert store.list_gold_regions() == []  # 失败即零落账


def test_abstain_labels_allowed_with_empty_sku_id(store, tmp_path):
    from src.platform.annotate.review import submit_review

    tid = _import_one(store, tmp_path, "blind_review", False)
    submit_review(store, task_id=tid, actor="alice", verdict="accepted",
                  box=(0, 0, 100, 100),
                  regions=[_region("rU", "unknown"),
                           _region("rN", "new_packaging")], registry=REG)
    recs = store.list_gold_regions()
    assert len(recs) == 2
    assert all(r["sku_id"] == "" for r in recs)
    assert {r["sku_name"] for r in recs} == {"unknown", "new_packaging"}


def test_same_actor_same_region_twice_rejected(store, tmp_path):
    from src.platform.annotate.review import submit_review

    tid = _import_one(store, tmp_path, "double_review", True)
    submit_review(store, task_id=tid, actor="alice", verdict="accepted",
                  box=(0, 0, 100, 100), regions=[_region()], registry=REG)
    # 同一 actor 对同一任务不得二次提交（含 region 重复）
    with pytest.raises(ValueError):
        submit_review(store, task_id=tid, actor="alice", verdict="accepted",
                      box=(0, 0, 100, 100), regions=[_region()],
                      registry=REG)
