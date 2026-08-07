"""truebox gold 正式导出契约（任务书§十三）：

gold_region_v1 → diagnostic_v1_truebox_v2 → run_truebox_eval 的正式出口。
- 只有 human_final / gold_verified 区域可进入导出；
- submitted/conflict/失效队列区域出现即 fail-closed（严格模式拒绝整次导出）；
- 导出不可变（同路径重复导出 FileExistsError）、可审计（export/protocol
  hash、git commit、来源队列版本）；0 gold 不写文件；
- 导出文档可被 run_truebox_eval 的 GT 加载入口直接消费（v2），
  旧 v1 列表格式保持兼容。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

REG = {
    "可口可乐500ml": {"sku_id": "QY_KK_000001",
                     "name": "可口可乐500ml", "class_id": 1},
    "百事可乐330ml": {"sku_id": "QY_BS_000002",
                     "name": "百事可乐330ml", "class_id": 2},
}

SHA_P1 = "cd" * 32
SHA_P2 = "ef" * 32


@pytest.fixture()
def store(tmp_path: Path):
    from src.platform.data.store import PlatformStore

    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _import_tasks(store, tmp_path: Path, items: list[dict],
                  queue_version: str = "rq_v1", fname: str = "rq.json"):
    from src.platform.annotate.review import import_review_queue

    f = tmp_path / fname
    f.write_text(json.dumps({"queue_version": queue_version,
                             "protocol": "diagnostic_v1",
                             "items": items}), encoding="utf-8")
    import_review_queue(store, f)
    return store.list_review_tasks()


def _task_of(store, photo_id: str, mode: str) -> str:
    row = store.find_review_task(photo_id=photo_id,
                                 sha256=SHA_P1 if photo_id == "p1" else SHA_P2,
                                 review_mode=mode)
    assert row is not None, f"任务不存在: {photo_id}/{mode}"
    return row["task_id"]


def _region(region_id: str, box, label: str = "可口可乐500ml") -> dict:
    return {"region_id": region_id, "box": list(box), "sku_label": label,
            "package_version_id": "pkg_v1", "evidence": {"zoom": 2},
            "group_store": "store_a", "group_session": "s1",
            "near_dup_group": "nd1"}


def _submit(store, tid: str, actor: str, regions: list[dict],
            role: str = "annotator"):
    from src.platform.annotate.review import submit_review

    return submit_review(store, task_id=tid, actor=actor,
                         verdict="adjudicated" if role == "arbiter"
                         else "accepted",
                         box=(0, 0, 100, 100), regions=regions,
                         role=role, registry=REG)


def _manifest(tmp_path: Path, entries: dict) -> Path:
    p = tmp_path / "clean_manifest.json"
    p.write_text(json.dumps(entries), encoding="utf-8")
    return p


def _protocol(tmp_path: Path) -> Path:
    p = tmp_path / "diagnostic_v1.json"
    p.write_text(json.dumps({"frozen": True, "role": "diagnostic_v1",
                             "photo_ids": ["p1", "p2"]},
                            ensure_ascii=False), encoding="utf-8")
    return p


def _export(store, tmp_path: Path, out: str = "truebox_v2.json", **kw):
    from src.review.truebox_export import export_truebox_gold

    return export_truebox_gold(
        store, out_path=tmp_path / out,
        manifest_path=_manifest(tmp_path, kw.pop("manifest", {
            "p1": {"sha256": SHA_P1, "width": 1500, "height": 2000,
                   "filename": "p1.jpg"},
            "p2": {"sha256": SHA_P2, "width": 1200, "height": 1600,
                   "filename": "p2.jpg"},
        })),
        protocol_path=_protocol(tmp_path),
        git_commit=kw.pop("git_commit", "c0ffee"), **kw)


def _double_agree_plus_arbiter(store, tmp_path: Path,
                               fname: str = "rq.json") -> str:
    """任务1：区域 A 双审一致 human_final；区域 B 分歧 → 仲裁 gold_verified。"""
    _import_tasks(store, tmp_path, [{
        "photo_id": "p2", "sha256": SHA_P2, "review_mode": "double_review",
        "requires_second_review": True}], fname=fname)
    tid = _task_of(store, "p2", "double_review")
    _submit(store, tid, "alice",
            [_region("A", [0, 0, 100, 100]),
             _region("B", [200, 0, 300, 100])])
    _submit(store, tid, "bob",
            [_region("A", [1, 1, 101, 101]),
             _region("B", [200, 0, 300, 100], label="百事可乐330ml")])
    _submit(store, tid, "admin",
            [_region("B", [200, 0, 300, 100])], role="arbiter")
    return tid
    return tid


# ---------------- 终态进入 / 非终态排除 ----------------

def test_human_final_and_gold_verified_enter_export(store, tmp_path):
    _double_agree_plus_arbiter(store, tmp_path)
    res = _export(store, tmp_path)  # 默认严格模式必须放行（无残留非终态）
    assert res["written"] is True
    doc = json.loads((tmp_path / "truebox_v2.json").read_text(encoding="utf-8"))
    recs = doc["records"]
    assert len(recs) == 2
    statuses = {r["region_id"]: r["final_status"] for r in recs}
    assert statuses == {"A": "human_final", "B": "gold_verified"}
    # 双审区域记录含两位审核人；仲裁区域记录含 arbiter
    a = next(r for r in recs if r["region_id"] == "A")
    assert {a["reviewer"], a["second_reviewer"]} == {"alice", "bob"}
    b = next(r for r in recs if r["region_id"] == "B")
    assert b["arbiter"] == "admin"
    # superseded 原提交绝不进入导出
    assert not any(r["final_status"] == "superseded" for r in recs)


def test_strict_mode_rejects_nonterminal_regions(store, tmp_path):
    """submitted/conflict 区域存在 → 默认严格模式拒绝整次导出。"""
    _double_agree_plus_arbiter(store, tmp_path)
    # 任务2（另一任务行）：仅一人提交 → submitted 残留
    t2 = _import_tasks(store, tmp_path, [{
        "photo_id": "p1", "sha256": SHA_P1, "review_mode": "double_review",
        "requires_second_review": True}], fname="rq2.json")
    t2 = _task_of(store, "p1", "double_review")
    _submit(store, t2, "carol", [_region("C", [0, 0, 50, 50])])
    with pytest.raises(ValueError, match="submitted|conflict"):
        _export(store, tmp_path)
    assert not (tmp_path / "truebox_v2.json").exists()


def test_conflict_without_arbitration_rejected_strict(store, tmp_path):
    tid = _import_tasks(store, tmp_path, [{
        "photo_id": "p1", "sha256": SHA_P1, "review_mode": "double_review",
        "requires_second_review": True}])
    tid = _task_of(store, "p1", "double_review")
    _submit(store, tid, "alice", [_region("r1", [0, 0, 100, 100])])
    _submit(store, tid, "bob",
            [_region("r1", [0, 0, 100, 100], label="百事可乐330ml")])
    with pytest.raises(ValueError):
        _export(store, tmp_path)


def test_non_strict_exports_only_terminal_regions(store, tmp_path):
    """strict=False：仅输出终态区域，计数正确。"""
    _double_agree_plus_arbiter(store, tmp_path)
    t2 = _import_tasks(store, tmp_path, [{
        "photo_id": "p1", "sha256": SHA_P1, "review_mode": "double_review",
        "requires_second_review": True}], fname="rq2.json")
    t2 = _task_of(store, "p1", "double_review")
    _submit(store, t2, "carol", [_region("C", [0, 0, 50, 50])])
    res = _export(store, tmp_path, strict=False)
    assert res["written"] is True
    doc = json.loads((tmp_path / "truebox_v2.json").read_text(encoding="utf-8"))
    assert {r["region_id"] for r in doc["records"]} == {"A", "B"}
    c = doc["counts"]
    assert c["exported"] == 2
    assert c["excluded_submitted"] == 1
    assert c["excluded_superseded"] == 2


# ---------------- 失效队列禁入 ----------------

def test_invalid_queue_regions_rejected(store, tmp_path):
    tid = _import_tasks(store, tmp_path, [{
        "photo_id": "p1", "sha256": SHA_P1, "review_mode": "blind_review",
        "requires_second_review": False}], queue_version="rq_bad")
    tid = _task_of(store, "p1", "blind_review")
    store.register_queue_version(queue_version="rq_bad", n_tasks=1)
    _submit(store, tid, "alice", [_region("r1", [0, 0, 10, 10])])
    store.invalidate_queue_version(queue_version="rq_bad", reason="bad")
    # 严格模式：失效队列区域出现即拒绝整次导出
    with pytest.raises(ValueError, match="失效|invalid"):
        _export(store, tmp_path)
    # 非严格：失效队列区域也不得进入导出
    res = _export(store, tmp_path, strict=False)
    assert res["written"] is False  # 无任何可导出 gold → 不写文件
    res2 = _double_agree_plus_bad_queue(store, tmp_path)
    # 失效队列区域计数累计 2：本测试前半的 r1 + helper 中的 x
    assert res2["counts"]["rejected_invalid_queue"] == 2
    assert {r["region_id"] for r in json.loads(
        (tmp_path / "t2.json").read_text(encoding="utf-8"))["records"]} == {"A", "B"}


def _double_agree_plus_bad_queue(store, tmp_path: Path) -> dict:
    _double_agree_plus_arbiter(store, tmp_path, fname="rq4.json")
    tid = _import_tasks(store, tmp_path, [{
        "photo_id": "p1", "sha256": SHA_P1, "review_mode": "blind_review",
        "requires_second_review": False}],
        queue_version="rq_bad2", fname="rq3.json")
    tid = _task_of(store, "p1", "blind_review")
    store.register_queue_version(queue_version="rq_bad2", n_tasks=1)
    _submit(store, tid, "dave", [_region("x", [0, 0, 10, 10])])
    store.invalidate_queue_version(queue_version="rq_bad2", reason="bad")
    return _export(store, tmp_path, out="t2.json", strict=False)


# ---------------- 字段完整性 / 审计 / 不可变 ----------------

def test_record_fields_complete_and_sizes_from_manifest(store, tmp_path):
    tid = _import_tasks(store, tmp_path, [{
        "photo_id": "p1", "sha256": SHA_P1, "review_mode": "blind_review",
        "requires_second_review": False}])
    tid = _task_of(store, "p1", "blind_review")
    _submit(store, tid, "alice", [_region("r1", [0, 0, 10, 20])])
    _export(store, tmp_path)
    doc = json.loads((tmp_path / "truebox_v2.json").read_text(encoding="utf-8"))
    r = doc["records"][0]
    required = ("image_id", "photo_id", "photo_sha256", "image_uri",
                "width", "height", "boxes", "sku_id", "sku_name",
                "package_version_id", "label_source", "reviewer",
                "second_reviewer", "arbiter", "final_status",
                "evidence_ids", "group_store", "group_session",
                "near_dup_group", "queue_version", "task_id", "region_id")
    for k in required:
        assert k in r, f"缺少字段 {k}"
    assert r["image_id"] == r["photo_id"] == "p1"
    assert r["photo_sha256"] == SHA_P1
    assert r["image_uri"] == f".batch3_clean/blobs/{SHA_P1[:2]}/{SHA_P1}"
    assert r["width"] == 1500 and r["height"] == 2000
    assert r["boxes"] == [[0.0, 0.0, 10.0, 20.0]]
    assert r["sku_id"] == "QY_KK_000001"
    assert r["label_source"] == "single_review"
    assert r["reviewer"] == "alice"
    assert r["second_reviewer"] is None and r["arbiter"] is None
    assert r["group_store"] == "store_a"
    assert r["group_session"] == "s1"
    assert r["near_dup_group"] == "nd1"
    assert r["queue_version"] == "rq_v1"
    # images 视图（run_truebox_eval 直接消费）
    img = doc["images"][0]
    assert img["image_id"] == "p1"
    assert img["boxes"] == [[0.0, 0.0, 10.0, 20.0]]
    assert img["width"] == 1500 and img["height"] == 2000


def test_export_is_immutable(store, tmp_path):
    tid = _import_tasks(store, tmp_path, [{
        "photo_id": "p1", "sha256": SHA_P1, "review_mode": "blind_review",
        "requires_second_review": False}])
    tid = _task_of(store, "p1", "blind_review")
    _submit(store, tid, "alice", [_region("r1", [0, 0, 10, 10])])
    _export(store, tmp_path)
    with pytest.raises(FileExistsError):
        _export(store, tmp_path)


def test_audit_fields_present_and_consistent(store, tmp_path):
    tid = _import_tasks(store, tmp_path, [{
        "photo_id": "p1", "sha256": SHA_P1, "review_mode": "blind_review",
        "requires_second_review": False}])
    tid = _task_of(store, "p1", "blind_review")
    _submit(store, tid, "alice", [_region("r1", [0, 0, 10, 10])])
    _export(store, tmp_path, git_commit="abc123")
    raw = (tmp_path / "truebox_v2.json").read_text(encoding="utf-8")
    doc = json.loads(raw)
    assert doc["export_version"] == "diagnostic_v1_truebox_v2"
    assert doc["git_commit"] == "abc123"
    proto_bytes = (tmp_path / "diagnostic_v1.json").read_bytes()
    assert doc["protocol_hash"] == hashlib.sha256(proto_bytes).hexdigest()
    assert doc["source_queue_versions"] == ["rq_v1"]
    # export_hash = 去除 export_hash 字段后的规范 JSON sha256
    body = {k: v for k, v in doc.items() if k != "export_hash"}
    expect = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True
                   ).encode("utf-8")).hexdigest()
    assert doc["export_hash"] == expect


def test_zero_gold_writes_nothing(store, tmp_path):
    res = _export(store, tmp_path)
    assert res["written"] is False
    assert res["counts"]["exported"] == 0
    assert not (tmp_path / "truebox_v2.json").exists()


# ---------------- run_truebox_eval 兼容 ----------------

def test_evaluator_gt_loader_accepts_v2_and_legacy_v1(store, tmp_path):
    tid = _import_tasks(store, tmp_path, [{
        "photo_id": "p1", "sha256": SHA_P1, "review_mode": "blind_review",
        "requires_second_review": False}])
    tid = _task_of(store, "p1", "blind_review")
    _submit(store, tid, "alice",
            [_region("r1", [0, 0, 10, 10]), _region("r2", [30, 30, 40, 40])])
    _export(store, tmp_path)
    from scripts.run_truebox_eval import load_gt

    gt = load_gt(tmp_path / "truebox_v2.json")  # v2 导出文档直接消费
    assert gt["p1"] == [{"box": [0.0, 0.0, 10.0, 10.0]},
                        {"box": [30.0, 30.0, 40.0, 40.0]}]
    # 旧 v1 列表格式保持兼容
    v1 = tmp_path / "gt_v1.json"
    v1.write_text(json.dumps(
        [{"image_id": "p1", "boxes": [[0, 0, 10, 10]]}]), encoding="utf-8")
    assert load_gt(v1) == {"p1": [{"box": [0, 0, 10, 10]}]}
