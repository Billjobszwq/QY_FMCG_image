"""区域级 gold 状态机契约（任务书§十一缺陷修复）：

- 多区域提交原子性：任一区域非法 → 整次提交零落账、零事件；
- bbox 合法性：x1/y1=0 合法；拒绝 x2<=x1 / y2<=y1 / 负坐标 /
  非数字 / 长度≠4 / 越界（提供 width/height 时）；
- 双审一致性：按区域 one-to-one 几何匹配（IoU >= 阈值），
  匹配上的区域对比 SKU 结论，未匹配视为分歧；
- 仲裁范围：仅作用于发生分歧的区域组，未分歧区域不受影响；
- 身份隔离：annotator 不得再当同任务 arbiter；同图不同任务 gold 隔离。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REG = {
    "可口可乐500ml": {"sku_id": "QY_KK_000001",
                     "name": "可口可乐500ml", "class_id": 1},
    "百事可乐330ml": {"sku_id": "QY_BS_000002",
                     "name": "百事可乐330ml", "class_id": 2},
}


@pytest.fixture()
def store(tmp_path: Path):
    from src.platform.data.store import PlatformStore

    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _import_tasks(store, tmp_path: Path, items: list[dict]) -> list[dict]:
    from src.platform.annotate.review import import_review_queue

    f = tmp_path / "rq.json"
    f.write_text(json.dumps({"queue_version": "rq_v1", "protocol": "diag",
                             "items": items}), encoding="utf-8")
    import_review_queue(store, f)
    return store.list_review_tasks()


def _import_one(store, tmp_path: Path,
                mode: str = "double_review", second: bool = True) -> str:
    rows = _import_tasks(store, tmp_path, [{
        "photo_id": "p1", "sha256": "ab" * 32, "review_mode": mode,
        "requires_second_review": second, "status": "pending"}])
    return rows[0]["task_id"]


def _region(region_id: str, box, label: str = "可口可乐500ml") -> dict:
    return {"region_id": region_id, "box": list(box), "sku_label": label,
            "package_version_id": "pkg_v1", "evidence": {"zoom": 2},
            "group_store": "store_a", "group_session": "s1",
            "near_dup_group": "nd1"}


def _submit(store, tid: str, actor: str, regions: list[dict],
            role: str = "annotator", **kw):
    from src.platform.annotate.review import submit_review

    return submit_review(store, task_id=tid, actor=actor,
                         verdict="adjudicated" if role == "arbiter"
                         else "accepted",
                         box=(0, 0, 100, 100), regions=regions,
                         role=role, registry=REG, **kw)


def _report(store):
    from src.platform.annotate.review import gold_region_report

    return gold_region_report(store)


# ---------------- 缺陷1：多区域提交原子性 ----------------

def test_multi_region_submission_is_atomic(store, tmp_path):
    """3 区域其中 1 个非法（label 不在 Registry）→ 整次 0 落账、0 事件。"""
    tid = _import_one(store, tmp_path, "blind_review", False)
    regions = [_region("r1", [0, 0, 10, 10]),
               _region("r2", [20, 20, 30, 30], label="不存在SKU"),
               _region("r3", [40, 40, 50, 50])]
    with pytest.raises(ValueError, match="不在 Registry"):
        _submit(store, tid, "alice", regions)
    assert store.list_gold_regions() == []
    assert not [e for e in store.list_review_events(tid)
                if e["kind"] == "review"]


# ---------------- 缺陷2：bbox 合法性 ----------------

def test_box_with_zero_origin_is_valid(store, tmp_path):
    """x1/y1=0 是合法坐标（图片左上角）。"""
    tid = _import_one(store, tmp_path, "blind_review", False)
    _submit(store, tid, "alice", [_region("r1", [0, 0, 10, 10])])
    recs = store.list_gold_regions()
    assert len(recs) == 1
    assert recs[0]["box"] == [0.0, 0.0, 10.0, 10.0]


@pytest.mark.parametrize("box", [
    [10, 10, 5, 20],     # x2 <= x1
    [10, 10, 20, 10],    # y2 <= y1
    [-1, 0, 10, 10],     # 负坐标
    [0, -5, 10, 10],     # 负坐标
    [0, 0, "x", 10],     # 非数字
    [0, 0, 10],          # 长度 != 4
])
def test_invalid_region_box_rejected_with_zero_landing(store, tmp_path, box):
    tid = _import_one(store, tmp_path, "blind_review", False)
    with pytest.raises(ValueError):
        _submit(store, tid, "alice", [_region("r1", box)])
    assert store.list_gold_regions() == []


def test_region_box_outside_image_bounds_rejected(store, tmp_path):
    """提供 width/height 时，越界坐标必须拒绝。"""
    tid = _import_one(store, tmp_path, "blind_review", False)
    with pytest.raises(ValueError):
        _submit(store, tid, "alice", [_region("r1", [0, 0, 200, 50])],
                width=100, height=100)
    assert store.list_gold_regions() == []


def test_region_box_within_image_bounds_accepted(store, tmp_path):
    tid = _import_one(store, tmp_path, "blind_review", False)
    _submit(store, tid, "alice", [_region("r1", [0, 0, 100, 100])],
            width=100, height=100)
    assert len(store.list_gold_regions()) == 1


# ---------------- 缺陷3：双审 one-to-one 几何匹配 ----------------

def test_double_review_iou_match_sku_agree_is_human_final(store, tmp_path):
    """两人各 2 区域，框 IoU>=0.75 且 SKU 一致 → human_final。"""
    tid = _import_one(store, tmp_path)
    _submit(store, tid, "alice",
            [_region("a1", [0, 0, 100, 100]),
             _region("a2", [200, 0, 300, 100], label="百事可乐330ml")])
    _submit(store, tid, "bob",
            [_region("b1", [2, 2, 102, 102]),          # IoU≈0.92
             _region("b2", [202, 2, 302, 102],
                     label="百事可乐330ml")])
    rep = _report(store)
    assert rep["counts"]["human_final"] == 2
    assert rep["counts"]["conflict"] == 0
    assert rep["usable_for_training"] == 2


def test_double_review_iou_match_sku_disagree_is_conflict(store, tmp_path):
    """几何匹配上但 SKU 结论不一致 → conflict。"""
    tid = _import_one(store, tmp_path)
    _submit(store, tid, "alice", [_region("a1", [0, 0, 100, 100])])
    _submit(store, tid, "bob",
            [_region("b1", [0, 0, 100, 100], label="百事可乐330ml")])
    rep = _report(store)
    assert rep["counts"]["human_final"] == 0
    assert rep["counts"]["conflict"] == 2
    assert rep["usable_for_training"] == 0


def test_double_review_low_iou_is_divergence(store, tmp_path):
    """一人框偏移过大（IoU<0.75）→ 未匹配，视为分歧而非 human_final。"""
    tid = _import_one(store, tmp_path)
    _submit(store, tid, "alice", [_region("a1", [0, 0, 100, 100])])
    _submit(store, tid, "bob", [_region("b1", [60, 0, 160, 100])])  # IoU=0.25
    rep = _report(store)
    assert rep["counts"]["human_final"] == 0
    assert rep["counts"]["conflict"] == 2
    assert rep["usable_for_training"] == 0


def test_double_review_abstain_label_compared_by_sku_name(store, tmp_path):
    """弃权标签（sku_id 为空）按 sku_name 比：unknown vs unknown 一致。"""
    tid = _import_one(store, tmp_path)
    _submit(store, tid, "alice", [_region("a1", [0, 0, 100, 100], "unknown")])
    _submit(store, tid, "bob", [_region("b1", [0, 0, 100, 100], "unknown")])
    rep = _report(store)
    assert rep["counts"]["human_final"] == 1


# ---------------- 缺陷4：仲裁只覆盖分歧区域 ----------------

def test_arbitration_only_supersedes_conflicted_regions(store, tmp_path):
    """区域 A 双审一致 + 区域 B 分歧；arbiter 只提交 B →
    B gold_verified、B 原记录 superseded，A 保持 human_final。"""
    tid = _import_one(store, tmp_path)
    _submit(store, tid, "alice",
            [_region("A", [0, 0, 100, 100]),
             _region("B", [200, 0, 300, 100])])
    _submit(store, tid, "bob",
            [_region("A", [1, 1, 101, 101]),
             _region("B", [200, 0, 300, 100], label="百事可乐330ml")])
    _submit(store, tid, "admin",
            [_region("B", [200, 0, 300, 100])], role="arbiter")
    rep = _report(store)
    assert rep["counts"]["gold_verified"] == 1
    assert rep["counts"]["human_final"] == 1
    assert rep["usable_for_training"] == 2
    assert not any(r["region_id"] == "A"
                   and r["final_status"] == "superseded"
                   for r in rep["regions"])
    assert any(r["region_id"] == "A" and r["final_status"] == "human_final"
               for r in rep["regions"])
    assert any(r["region_id"] == "B" and r["final_status"] == "gold_verified"
               for r in rep["regions"])
    assert any(r["region_id"] == "B" and r["final_status"] == "superseded"
               for r in rep["regions"])


# ---------------- 缺陷5：身份隔离（保留既有校验） ----------------

def test_arbiter_requires_two_prior_reviews(store, tmp_path):
    tid = _import_one(store, tmp_path)
    _submit(store, tid, "alice", [_region("A", [0, 0, 10, 10])])
    with pytest.raises(ValueError, match="仲裁前必须"):
        _submit(store, tid, "admin", [_region("A", [0, 0, 10, 10])],
                role="arbiter")


def test_annotator_cannot_become_arbiter_of_same_task(store, tmp_path):
    """同一 actor 不得既 annotator 又 arbiter（二次提交校验覆盖）。"""
    tid = _import_one(store, tmp_path)
    _submit(store, tid, "alice", [_region("A", [0, 0, 10, 10])])
    _submit(store, tid, "bob",
            [_region("A", [0, 0, 10, 10], label="百事可乐330ml")])
    with pytest.raises(ValueError):
        _submit(store, tid, "alice", [_region("A", [0, 0, 10, 10])],
                role="arbiter")


def test_same_actor_second_submission_rejected(store, tmp_path):
    tid = _import_one(store, tmp_path)
    _submit(store, tid, "alice", [_region("A", [0, 0, 10, 10])])
    with pytest.raises(ValueError):
        _submit(store, tid, "alice", [_region("B", [20, 20, 30, 30])])


def test_same_photo_different_tasks_gold_isolated(store, tmp_path):
    """同图两个任务（blind 单审 vs double 双审）：gold 按 task_id 隔离，
    不得跨任务合并——单审任务即 human_final，双审任务仍等二审。"""
    _import_tasks(store, tmp_path, [
        {"photo_id": "p1", "sha256": "ab" * 32, "review_mode": "blind_review",
         "requires_second_review": False, "status": "pending"},
        {"photo_id": "p1", "sha256": "ab" * 32,
         "review_mode": "double_review",
         "requires_second_review": True, "status": "pending"},
    ])
    tasks = {t["review_mode"]: t["task_id"]
             for t in store.list_review_tasks()}
    _submit(store, tasks["blind_review"], "alice",
            [_region("r1", [0, 0, 10, 10])])
    _submit(store, tasks["double_review"], "bob",
            [_region("r1", [0, 0, 10, 10])])
    rep = _report(store)
    assert rep["counts"] == {"submitted": 1, "human_final": 1,
                             "gold_verified": 0, "conflict": 0}
