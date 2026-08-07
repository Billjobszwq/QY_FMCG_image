"""PLC3-002 红测试：rq_v1 追加式失效 + V2 active queue（账本语义）。

红线：不得删除/更新 review_task_v1 历史行（触发器保护）；失效必须追加式；
active/invalid/superseded 分开统计；失效 V1 不得阻断 V2。
"""
import pytest

from src.platform.data.store import PlatformStore, StoreError


@pytest.fixture()
def store(tmp_path):
    s = PlatformStore(tmp_path / "t.sqlite")
    yield s
    s.close()


def _add_task(store, task_id, photo_id, sha, mode="double_review", qv="rq_v1"):
    import secrets
    ok = store.add_review_task(
        task_id=task_id, claim_token=secrets.token_urlsafe(8),
        photo_id=photo_id, sha256=sha, review_mode=mode,
        requires_second_review=True, queue_version=qv,
        protocol="diagnostic_v1", import_seed=20260804)
    assert ok


# ---------- 队列版本账本 ----------

def test_register_and_invalidate_queue_append_only(store):
    store.register_queue_version(queue_version="rq_v1", protocol="diagnostic_v1",
                                 n_tasks=250, source_path=".review_queue/rq_v1.json")
    store.register_queue_version(queue_version="rq_v2", protocol="diagnostic_v1",
                                 n_tasks=250, source_path=".review_queue/rq_v2.json")
    store.invalidate_queue_version(
        queue_version="rq_v1", reason="invalid_id_sha_mapping",
        root_cause="photo_ids 与 sha256 独立排序后按位置 zip",
        impact_summary="250/250 ID/SHA 配对错误", git_commit="abc123",
        evidence_path=".review_queue/rq_v1_invalidation.json",
        superseded_by="rq_v2")
    led = {r["queue_version"]: r for r in store.list_queue_ledger()}
    assert led["rq_v1"]["status"] == "invalid"
    assert led["rq_v1"]["superseded_by"] == "rq_v2"
    assert led["rq_v2"]["status"] == "active"


def test_invalidate_unknown_queue_fail_closed(store):
    with pytest.raises(StoreError):
        store.invalidate_queue_version(queue_version="rq_x", reason="r")


def test_double_invalidate_idempotent_evidence(store):
    store.register_queue_version(queue_version="rq_v1", protocol="p", n_tasks=1,
                                 source_path="x")
    store.invalidate_queue_version(queue_version="rq_v1", reason="invalid_id_sha_mapping")
    # 重复失效不新增行（追加式账本也要幂等防刷）
    store.invalidate_queue_version(queue_version="rq_v1", reason="invalid_id_sha_mapping")
    rows = [r for r in store.list_queue_ledger() if r["queue_version"] == "rq_v1"]
    assert len(rows) == 1


# ---------- 活动队列过滤 ----------

def test_active_queue_filter_excludes_invalidated_tasks(store):
    store.register_queue_version(queue_version="rq_v1", protocol="p", n_tasks=2,
                                 source_path="x")
    store.register_queue_version(queue_version="rq_v2", protocol="p", n_tasks=1,
                                 source_path="y")
    _add_task(store, "t1", "111", "aaa", qv="rq_v1")
    _add_task(store, "t2", "222", "bbb", qv="rq_v1")
    _add_task(store, "t3", "333", "ccc", qv="rq_v2")
    store.invalidate_queue_version(queue_version="rq_v1",
                                   reason="invalid_id_sha_mapping",
                                   superseded_by="rq_v2")
    active = store.list_review_tasks_active()
    assert [t["task_id"] for t in active] == ["t3"]
    # 历史行仍在（未删除）
    assert len(store.list_review_tasks()) == 3


def test_active_stats_split_active_invalid(store):
    store.register_queue_version(queue_version="rq_v1", protocol="p", n_tasks=2,
                                 source_path="x")
    store.register_queue_version(queue_version="rq_v2", protocol="p", n_tasks=1,
                                 source_path="y")
    _add_task(store, "t1", "111", "aaa", qv="rq_v1")
    _add_task(store, "t2", "222", "bbb", qv="rq_v1")
    _add_task(store, "t3", "333", "ccc", qv="rq_v2")
    store.invalidate_queue_version(queue_version="rq_v1", reason="r",
                                   superseded_by="rq_v2")
    stats = store.review_task_stats()
    assert stats["active"] == 1
    assert stats["invalid"] == 2
    assert stats["total"] == 3


def test_invalidation_does_not_block_v2_progress(store):
    """失效 V1 后，V2 任务照常可认领、可审核（状态推导不被阻断）。"""
    from src.platform.annotate.review import claim_task, submit_review
    store.register_queue_version(queue_version="rq_v1", protocol="p", n_tasks=1,
                                 source_path="x")
    store.register_queue_version(queue_version="rq_v2", protocol="p", n_tasks=1,
                                 source_path="y")
    _add_task(store, "old1", "111", "aaa", qv="rq_v1")
    store.invalidate_queue_version(queue_version="rq_v1", reason="r",
                                   superseded_by="rq_v2")
    import secrets
    tok = secrets.token_urlsafe(8)
    store.add_review_task(task_id="new1", claim_token=tok, photo_id="333",
                          sha256="ccc", review_mode="double_review",
                          requires_second_review=True, queue_version="rq_v2")
    out = claim_task(store, tok, actor="alice")
    assert out["claimed"] is True


# ---------- 已有 claim 保留但不计活动进度 ----------

def test_claim_on_invalidated_task_kept_but_not_active(store):
    from src.platform.annotate.review import claim_task
    store.register_queue_version(queue_version="rq_v1", protocol="p", n_tasks=1,
                                 source_path="x")
    import secrets
    tok = secrets.token_urlsafe(8)
    store.add_review_task(task_id="t1", claim_token=tok, photo_id="111",
                          sha256="aaa", review_mode="double_review",
                          requires_second_review=True, queue_version="rq_v1")
    assert claim_task(store, tok, actor="bob")["claimed"] is True
    store.invalidate_queue_version(queue_version="rq_v1", reason="r")
    # claim 事件保留
    ev = store.list_review_events("t1")
    assert any(e["kind"] == "claim" for e in ev)
    # 但不计入活动进度
    assert store.list_review_tasks_active() == []
