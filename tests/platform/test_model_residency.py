"""VLM-003：hot/warm/cold 模型驻留管理器（租约、TTL 卸载、审计、崩溃恢复）TDD。

红线：
- Qwen 初期 max_concurrency=1（sleeping guardian）；
- 过期租约必须显式 reap，不能永久占用；
- 所有 acquire/release/load/unload 写 audit；
- 进程重启后状态从持久化表恢复。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.platform.data.store import PlatformStore
from src.platform.model_runtime import (
    ModelBusy,
    ModelResidencyManager,
    ModelRuntimeError,
)


class FakeClock:
    def __init__(self, start: str = "2026-08-06T00:00:00+00:00") -> None:
        self.t = datetime.fromisoformat(start)

    def now(self) -> str:
        return self.t.isoformat()

    def advance(self, seconds: float) -> None:
        self.t = self.t + timedelta(seconds=seconds)


@pytest.fixture()
def store(tmp_path) -> PlatformStore:
    return PlatformStore(tmp_path / "p.sqlite")


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def mgr(store, clock) -> ModelResidencyManager:
    return ModelResidencyManager(store, now=clock.now)


# ---------- 注册与初始状态 ----------

def test_register_cold_model_initial_state(mgr) -> None:
    mgr.register("qwen3-vl:4b", residency="cold", max_concurrency=1, idle_ttl_s=300)
    st = mgr.state("qwen3-vl:4b")
    assert st["state"] == "cold"
    assert st["residency"] == "cold"
    assert st["active_leases"] == 0


def test_register_hot_model_stays_hot(mgr) -> None:
    mgr.register("yolo", residency="hot", max_concurrency=4, idle_ttl_s=0)
    assert mgr.state("yolo")["state"] == "hot"


def test_register_duplicate_rejected(mgr) -> None:
    mgr.register("m", residency="cold", max_concurrency=1, idle_ttl_s=10)
    with pytest.raises(ModelRuntimeError):
        mgr.register("m", residency="cold", max_concurrency=1, idle_ttl_s=10)


def test_register_invalid_residency_rejected(mgr) -> None:
    with pytest.raises(ModelRuntimeError):
        mgr.register("m", residency="warmish", max_concurrency=1, idle_ttl_s=10)


def test_unknown_model_state_raises(mgr) -> None:
    with pytest.raises(ModelRuntimeError):
        mgr.state("ghost")
    with pytest.raises(ModelRuntimeError):
        mgr.acquire("ghost", run_id="r1")


# ---------- 租约与并发 ----------

def test_qwen_single_lease_and_idle_unload(mgr, clock) -> None:
    mgr.register("qwen3-vl:4b", residency="cold", max_concurrency=1, idle_ttl_s=300)
    lease = mgr.acquire("qwen3-vl:4b", run_id="r1")
    assert mgr.state("qwen3-vl:4b")["active_leases"] == 1
    assert mgr.state("qwen3-vl:4b")["state"] == "hot"
    with pytest.raises(ModelBusy):
        mgr.acquire("qwen3-vl:4b", run_id="r2")
    mgr.release(lease.lease_id)
    assert mgr.state("qwen3-vl:4b")["active_leases"] == 0
    clock.advance(301)
    assert mgr.unload_idle() == ["qwen3-vl:4b"]
    assert mgr.state("qwen3-vl:4b")["state"] == "cold"


def test_lease_carries_run_attempt_and_deadline(mgr) -> None:
    mgr.register("qwen3-vl:4b", residency="cold", max_concurrency=1, idle_ttl_s=300)
    lease = mgr.acquire(
        "qwen3-vl:4b", run_id="r1", attempt_id="a1", lease_ttl_s=120
    )
    assert lease.run_id == "r1"
    assert lease.attempt_id == "a1"
    assert lease.lease_id
    assert lease.deadline is not None


def test_release_unknown_lease_rejected(mgr) -> None:
    mgr.register("m", residency="hot", max_concurrency=1, idle_ttl_s=10)
    with pytest.raises(ModelRuntimeError):
        mgr.release("no-such-lease")


def test_expired_lease_reaped_explicitly(mgr, clock) -> None:
    mgr.register("qwen3-vl:4b", residency="cold", max_concurrency=1, idle_ttl_s=300)
    lease = mgr.acquire(
        "qwen3-vl:4b", run_id="r1", lease_ttl_s=60
    )
    clock.advance(61)
    reaped = mgr.reap_expired()
    assert lease.lease_id in reaped
    assert mgr.state("qwen3-vl:4b")["active_leases"] == 0
    # 过期后允许新的获取
    lease2 = mgr.acquire("qwen3-vl:4b", run_id="r2")
    assert lease2.lease_id != lease.lease_id


def test_expired_lease_blocks_until_reap(mgr, clock) -> None:
    """fail-closed：过期但未 reap 的租约仍占用并发名额。"""
    mgr.register("m", residency="hot", max_concurrency=1, idle_ttl_s=300)
    mgr.acquire("m", run_id="r1", lease_ttl_s=10)
    clock.advance(20)
    with pytest.raises(ModelBusy):
        mgr.acquire("m", run_id="r2")


def test_hot_model_with_capacity_allows_concurrent_leases(mgr) -> None:
    mgr.register("yolo", residency="hot", max_concurrency=2, idle_ttl_s=0)
    l1 = mgr.acquire("yolo", run_id="r1")
    l2 = mgr.acquire("yolo", run_id="r2")
    assert mgr.state("yolo")["active_leases"] == 2
    with pytest.raises(ModelBusy):
        mgr.acquire("yolo", run_id="r3")
    mgr.release(l1.lease_id)
    mgr.release(l2.lease_id)


# ---------- TTL 卸载边界 ----------

def test_unload_idle_skips_hot_and_busy(mgr, clock) -> None:
    mgr.register("yolo", residency="hot", max_concurrency=1, idle_ttl_s=10)
    mgr.register("qwen3-vl:4b", residency="cold", max_concurrency=1, idle_ttl_s=10)
    mgr.acquire("qwen3-vl:4b", run_id="r1")
    clock.advance(999)
    assert mgr.unload_idle() == []  # hot 不卸载；busy 不卸载


def test_unload_idle_requires_ttl_elapsed(mgr, clock) -> None:
    mgr.register("m", residency="cold", max_concurrency=1, idle_ttl_s=300)
    lease = mgr.acquire("m", run_id="r1")
    mgr.release(lease.lease_id)
    clock.advance(299)
    assert mgr.unload_idle() == []
    clock.advance(2)
    assert mgr.unload_idle() == ["m"]


# ---------- 加载/失败/恢复 ----------

def test_load_failure_marks_failed_and_blocks_acquire(store, clock) -> None:
    calls = []

    def bad_loader(model: str) -> None:
        calls.append(model)
        raise RuntimeError("mlx 未安装（本轮门禁）")

    mgr2 = ModelResidencyManager(store, now=clock.now, loader=bad_loader)
    mgr2.register("qwen3-vl:4b", residency="cold", max_concurrency=1, idle_ttl_s=300)
    with pytest.raises(ModelRuntimeError):
        mgr2.acquire("qwen3-vl:4b", run_id="r1")
    assert mgr2.state("qwen3-vl:4b")["state"] == "failed"
    with pytest.raises(ModelRuntimeError):
        mgr2.acquire("qwen3-vl:4b", run_id="r2")
    assert calls == ["qwen3-vl:4b"]  # 失败后不再反复尝试加载（熔断）


def test_crash_recovery_reaps_loading_state(store, clock) -> None:
    """进程崩溃后 loading 状态必须由显式恢复回到 cold。"""
    m1 = ModelResidencyManager(store, now=clock.now)
    m1.register("qwen3-vl:4b", residency="cold", max_concurrency=1, idle_ttl_s=300)
    store._conn.execute(
        "UPDATE model_residency SET state='loading' WHERE model_id=?",
        ("qwen3-vl:4b",),
    )
    m2 = ModelResidencyManager(store, now=clock.now, recover=True)
    assert m2.state("qwen3-vl:4b")["state"] == "cold"


def test_state_survives_process_restart(tmp_path, clock) -> None:
    db = tmp_path / "p.sqlite"
    s1 = PlatformStore(db)
    m1 = ModelResidencyManager(s1, now=clock.now)
    m1.register("qwen3-vl:4b", residency="cold", max_concurrency=1, idle_ttl_s=300)
    lease = m1.acquire("qwen3-vl:4b", run_id="r1")
    # 模拟进程重启：新 store + 新 manager
    s2 = PlatformStore(db)
    m2 = ModelResidencyManager(s2, now=clock.now)
    st = m2.state("qwen3-vl:4b")
    assert st["state"] == "hot"
    assert st["active_leases"] == 1
    m2.release(lease.lease_id)
    assert m2.state("qwen3-vl:4b")["active_leases"] == 0


# ---------- 审计 ----------

def test_all_lifecycle_events_audited(mgr, store, clock) -> None:
    mgr.register("qwen3-vl:4b", residency="cold", max_concurrency=1, idle_ttl_s=10)
    lease = mgr.acquire("qwen3-vl:4b", run_id="r1")
    mgr.release(lease.lease_id)
    clock.advance(999)
    mgr.unload_idle()
    actions = {a["action"] for a in store.list_audit(subject_id="qwen3-vl:4b")}
    assert {"residency.register", "residency.load", "residency.acquire",
            "residency.release", "residency.unload"} <= actions
