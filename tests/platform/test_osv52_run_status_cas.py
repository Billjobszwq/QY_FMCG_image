"""OSV52 红测试：business_run 终态不可回退契约 + 状态写 CAS。

背景（OSV51-013）：set_business_run_status 原为 SELECT-then-UPDATE，
并发下两个写者都通过转移检查 → last-write-wins 覆盖终态
（实证：1500 轮并发 1301 轮双写覆盖）。本文件先于修复存在。

契约：
- succeeded/cancelled 为绝对终态（无出边）；failed/partial_failed
  仅可经 retry→running；
- 终态写入必须是条件 UPDATE（CAS：WHERE status=读取时的 cur）；
- 迟到写（timeout/cancel 之后的 completed）必须被拒，不得覆盖；
- 重复写同一目标态幂等返回；
- 并发竞态恰好一个写者赢。
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from src.platform.data.store import PlatformStore, StoreError


@pytest.fixture()
def store(tmp_path: Path) -> PlatformStore:
    return PlatformStore(tmp_path / "p.sqlite")


def _mk_run(store, rid: str) -> None:
    store.insert_business_run({
        "run_id": rid, "work_id": f"w-{rid}", "tenant_id": "local",
        "customer_id": "", "project_id": "",
        "workflow_definition_id": "", "workflow_version": "",
        "trigger_type": "manual", "parent_run_id": "",
        "correlation_id": "", "causation_id": "",
        "subject_type": "", "subject_id": "",
        "data_scope": "operational", "test_run_id": ""})


def _running(store, rid: str) -> None:
    _mk_run(store, rid)
    store.set_business_run_status(rid, "running")


class TestTerminalContract:
    def test_succeeded_is_absolute_terminal(self, store):
        _running(store, "r1")
        store.set_business_run_status("r1", "succeeded")
        for nxt in ("cancelled", "failed", "running", "paused"):
            with pytest.raises(StoreError):
                store.set_business_run_status("r1", nxt)
        assert store.get_business_run("r1")["status"] == "succeeded"

    def test_cancelled_is_absolute_terminal(self, store):
        _running(store, "r2")
        store.set_business_run_status("r2", "cancelled")
        for nxt in ("succeeded", "failed", "running"):
            with pytest.raises(StoreError):
                store.set_business_run_status("r2", nxt)

    def test_failed_retry_to_running_allowed(self, store):
        _running(store, "r3")
        store.set_business_run_status("r3", "failed", error="boom")
        store.set_business_run_status("r3", "running")
        assert store.get_business_run("r3")["status"] == "running"

    def test_late_write_after_cancel_rejected(self, store):
        """超时/取消后迟到的 completed 不得覆盖 cancelled。"""
        _running(store, "r4")
        store.set_business_run_status("r4", "cancelled")
        with pytest.raises(StoreError):
            store.set_business_run_status("r4", "succeeded")
        assert store.get_business_run("r4")["status"] == "cancelled"

    def test_duplicate_same_target_idempotent(self, store):
        _running(store, "r5")
        a = store.set_business_run_status("r5", "succeeded")
        b = store.set_business_run_status("r5", "succeeded")
        assert a["status"] == b["status"] == "succeeded"
        assert b["version"] == a["version"]  # 幂等：不重复 +1


class TestConcurrentCas:
    def test_concurrent_terminal_exactly_one_winner(self, store):
        rounds = 300
        for i in range(rounds):
            rid = f"rc-{i}"
            _running(store, rid)
            outcomes: list[tuple[str, str]] = []
            lock = threading.Lock()
            barrier = threading.Barrier(2)

            def race(status: str):
                barrier.wait()
                try:
                    store.set_business_run_status(rid, status)
                    res = "ok"
                except StoreError:
                    res = "conflict"
                with lock:
                    outcomes.append((status, res))

            t1 = threading.Thread(target=race, args=("cancelled",))
            t2 = threading.Thread(target=race, args=("succeeded",))
            t1.start(); t2.start(); t1.join(); t2.join()
            final = store.get_business_run(rid)["status"]
            oks = [s for s, r in outcomes if r == "ok"]
            assert len(oks) == 1, (rounds, i, outcomes, final)
            assert final == oks[0], (i, outcomes, final)

    def test_same_target_concurrent_no_conflict(self, store):
        for i in range(60):
            rid = f"rs-{i}"
            _running(store, rid)
            outcomes: list[str] = []
            lock = threading.Lock()
            barrier = threading.Barrier(2)

            def race():
                barrier.wait()
                try:
                    store.set_business_run_status(rid, "succeeded")
                    res = "ok"
                except StoreError:
                    res = "conflict"
                with lock:
                    outcomes.append(res)

            ts = [threading.Thread(target=race) for _ in range(2)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            assert outcomes.count("ok") == 2, (i, outcomes)
            assert store.get_business_run(rid)["status"] == "succeeded"
