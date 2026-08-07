"""PLC3-006 红测试：统一审核状态源（任务书§八 / 提交链 5）。

事实源 = review_task_v1 + review_event_v1 + active queue version（DB 推导）；
队列 JSON 只是不可变导入制品，不作为运行状态。要求：
- WorkItems/进度统计走同一查询服务（review_progress）；
- 页面总数、分页、筛选数量一致；
- active/invalid 分开统计；失效 V1 不进默认列表、不阻断 V2。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.platform.annotate.review import (
    claim_task, review_progress, submit_review)
from src.platform.data.store import PlatformStore


def _seed(store, *, queue_version="rq_v2", n=3, mode="double_review",
          requires_second=True, prefix="p"):
    for i in range(n):
        store.add_review_task(
            task_id=f"rt_{queue_version}_{prefix}{i}",
            claim_token=f"tok_{queue_version}_{prefix}{i}",
            photo_id=f"{prefix}{i}", sha256=f"sha_{queue_version}_{i:03d}",
            review_mode=mode, requires_second_review=requires_second,
            queue_version=queue_version, protocol="diagnostic_v1")


@pytest.fixture()
def store(tmp_path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def test_progress_derived_from_db_events(store):
    """claim 事件立即改变推导状态（DB 是唯一事实源）。"""
    _seed(store, n=3)
    p0 = review_progress(store)
    assert p0["source"] == "db_events"
    assert p0["active"]["total"] == 3
    assert p0["active"]["by_status"]["pending"] == 3

    claim_task(store, "tok_rq_v2_p0", actor="alice")
    p1 = review_progress(store)
    assert p1["active"]["by_status"]["pending"] == 2
    assert p1["active"]["by_status"]["claimed"] == 1


def test_json_file_is_not_runtime_source(store, tmp_path, monkeypatch):
    """静态 JSON 声称 3 pending，但 DB 为空 → 运行状态必须是 0。"""
    rq = tmp_path / "fake_queue.json"
    rq.write_text(json.dumps({
        "queue_version": "rq_v1", "protocol": "diagnostic_v1",
        "items": [{"photo_id": f"x{i}", "sha256": f"s{i}",
                   "status": "pending", "review_mode": "double_review"}
                  for i in range(3)]}), encoding="utf-8")
    monkeypatch.setenv("PLATFORM_REVIEW_QUEUE", str(rq))
    p = review_progress(store)
    assert p["active"]["total"] == 0


def test_invalid_queue_excluded_and_separated(store):
    """失效版本不进默认进度；active/invalid 分开统计。"""
    _seed(store, queue_version="rq_v1", n=3, prefix="a")
    _seed(store, queue_version="rq_v2", n=2, prefix="b")
    store.register_queue_version(queue_version="rq_v1", n_tasks=3)
    store.register_queue_version(queue_version="rq_v2", n_tasks=2)
    store.invalidate_queue_version(
        queue_version="rq_v1", reason="invalid_id_sha_mapping",
        superseded_by="rq_v2")
    p = review_progress(store)
    assert p["active"]["total"] == 2
    assert p["active"]["queue_versions"] == ["rq_v2"]
    assert p["invalid"]["total"] == 3
    assert p["invalid"]["queue_versions"] == ["rq_v1"]


def test_finalized_reflected_in_progress(store):
    """单审提交即终态：by_status 出现 finalized。"""
    _seed(store, n=1, mode="blind_review", requires_second=False)
    submit_review(store, task_id="rt_rq_v2_p0", actor="alice",
                  verdict="accepted", box=[0, 0, 10, 10])
    p = review_progress(store)
    assert p["active"]["by_status"]["finalized"] == 1
    assert p["active"]["by_status"].get("pending", 0) == 0


def _client(tmp_path, monkeypatch):
    from src.composition.build import build_production_bundle
    from src.platform.api.app import create_app

    rq = tmp_path / "fake_queue.json"
    rq.write_text(json.dumps({
        "queue_version": "rq_v1", "protocol": "diagnostic_v1",
        "items": [{"photo_id": f"ghost{i}", "sha256": f"s{i}",
                   "status": "pending", "review_mode": "double_review"}
                  for i in range(3)]}), encoding="utf-8")
    monkeypatch.setenv("PLATFORM_REVIEW_QUEUE", str(rq))
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=None, monitor_adapter=None,
        label_studio_adapter=None, probe=lambda spec: None)
    app = create_app(services=(), probe=lambda spec: None, bundle=bundle,
                     web_dist=tmp_path / "none")
    return TestClient(app), bundle


def test_workitems_use_db_not_json(tmp_path, monkeypatch):
    """JSON 有 3 条 pending 但 DB 未导入 → WorkItems 不得显示。"""
    client, _ = _client(tmp_path, monkeypatch)
    d = client.get("/api/v1/workitems").json()
    reviews = [w for w in d["items"] if w["kind"] == "human_review"]
    assert reviews == []
    assert d["summary"]["pending_review"] == 0


def test_workitems_track_claim_event(tmp_path, monkeypatch):
    """DB 导入 3 条后：认领一条 → WorkItems 立即 2 pending + 1 claimed。"""
    client, bundle = _client(tmp_path, monkeypatch)
    store = bundle.store
    _seed(store, n=3)
    claim_task(store, "tok_rq_v2_p0", actor="alice")
    d = client.get("/api/v1/workitems").json()
    reviews = [w for w in d["items"] if w["kind"] == "human_review"]
    assert len(reviews) == 3
    assert d["summary"]["pending_review"] == 2
    statuses = {w["id"]: w["status"] for w in reviews}
    assert statuses["review:rt_rq_v2_p0"] == "claimed"
    assert statuses["review:rt_rq_v2_p1"] == "pending"
    assert d["count"] == len(d["items"])


def test_workitems_hide_invalid_queue_tasks(tmp_path, monkeypatch):
    """失效队列任务不进 WorkItems 默认列表，不阻断 V2。"""
    client, bundle = _client(tmp_path, monkeypatch)
    store = bundle.store
    _seed(store, queue_version="rq_v1", n=3, prefix="a")
    _seed(store, queue_version="rq_v2", n=2, prefix="b")
    store.register_queue_version(queue_version="rq_v1", n_tasks=3)
    store.register_queue_version(queue_version="rq_v2", n_tasks=2)
    store.invalidate_queue_version(
        queue_version="rq_v1", reason="invalid_id_sha_mapping",
        superseded_by="rq_v2")
    d = client.get("/api/v1/workitems").json()
    reviews = [w for w in d["items"] if w["kind"] == "human_review"]
    assert len(reviews) == 2
    assert all(w["detail"]["queue_version"] == "rq_v2" for w in reviews)
    only = client.get("/api/v1/workitems?kind=human_review").json()
    assert only["count"] == 2
