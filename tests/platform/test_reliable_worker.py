"""GLTC-007 红测试：资源租约与可靠 Worker（任务书 Task 7 / 01 §8）。

- 提交时冻结 env/command/data/code/config hash；
- PID/heartbeat/attempt/日志 ResourceRef 可对账；
- safe-stop：STOPPING → 确认退出/checkpoint → STOPPED → 释放 lease，
  禁止直接伪写 cancelled/终态；
- orphan 恢复：进程不存在/心跳过期 → orphaned/failed，不伪称 running；
- heavy lease 并发 1、MPS/MLX 互斥（经 store）；
- launch 前重跑真实 G0（可注入，默认真实）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.modules.training_control import worker as W
from src.platform.data.store import PlatformStore

G0_PASS = {"gate_version": "mps_g0_v1", "ok": True,
           "checks": [{"name": "arch_arm64", "ok": True, "detail": "ok"}],
           "evidence": {}}
G0_FAIL = {**G0_PASS, "ok": False,
           "checks": [{"name": "power_ac", "ok": False, "detail": "bat"}]}


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _worker(store, gate=None):
    return W.ReliableWorker(store, hardware_gate=(lambda **kw: gate)
                            if gate is not None else None)


class TestSubmissionFreeze:
    def test_submit_freezes_spec_and_acquires_lease(self, store):
        w = _worker(store, gate=G0_PASS)
        rec = w.submit_run("run1", lane="detector",
                           command=["python3", "-m", "src.training.train_v1",
                                    "--parse-check"],
                           env={"PY": "3.13"}, data_hash="d" * 8,
                           code_hash="c" * 8, config_hash="f" * 8,
                           leases=["mps"], actor="admin")
        assert rec["status"] == "QUEUED"
        spec = store.get_training_run_v2("run1")
        assert spec["status"] == "QUEUED"
        frozen = rec["frozen"]
        assert frozen["env_hash"] and frozen["data_hash"] == "d" * 8
        assert frozen["code_hash"] == "c" * 8
        assert frozen["config_hash"] == "f" * 8
        assert [l["resource"] for l in store.list_active_leases()] == ["mps"]

    def test_submit_reruns_g0_and_rejects_on_fail(self, store):
        w = _worker(store, gate=G0_FAIL)
        with pytest.raises(W.WorkerError, match="G0"):
            w.submit_run("run2", lane="detector", command=["python3"],
                         env={}, data_hash="d", code_hash="c",
                         config_hash="f", leases=["mps"], actor="admin")
        assert store.list_active_leases() == [], "失败不得残留租约"

    def test_heavy_lease_conflict_rejected(self, store):
        w = _worker(store, gate=G0_PASS)
        w.submit_run("runA", lane="detector", command=["python3"],
                     env={}, data_hash="d", code_hash="c",
                     config_hash="f", leases=["mps"], actor="admin")
        with pytest.raises(W.WorkerError):
            w.submit_run("runB", lane="classifier", command=["python3"],
                         env={}, data_hash="d", code_hash="c",
                         config_hash="f", leases=["mps"], actor="admin")


class TestSafeStop:
    def test_safe_stop_evidence_chain(self, store):
        w = _worker(store, gate=G0_PASS)
        w.submit_run("run1", lane="detector", command=["python3"],
                     env={}, data_hash="d", code_hash="c",
                     config_hash="f", leases=["mps"], actor="admin")
        w.mark_running("run1", pid=999999)
        w.request_safe_stop("run1", reason="stop_line")
        assert store.get_training_run_v2("run1")["status"] == "STOPPING"
        assert store.list_active_leases(), "未确认退出前不得释放租约"
        # 未确认退出时不得写终态
        with pytest.raises(W.WorkerError):
            w.request_safe_stop("run1", reason="again") or None
        w.confirm_stopped("run1", exit_code=0, checkpoint_saved=True,
                          process_exited=True)
        assert store.get_training_run_v2("run1")["status"] == "STOPPED"
        assert store.list_active_leases() == []
        evs = store.list_training_events("run1")
        kinds = [e["kind"] for e in evs]
        assert "stop_requested" in kinds and "stopped" in kinds

    def test_cancelled_cannot_fake_stop(self, store):
        w = _worker(store, gate=G0_PASS)
        w.submit_run("run1", lane="detector", command=["python3"],
                     env={}, data_hash="d", code_hash="c",
                     config_hash="f", leases=[], actor="admin")
        w.mark_running("run1", pid=999999)
        with pytest.raises(W.WorkerError):
            # 无进程退出证据不得直达 STOPPED
            w.confirm_stopped("run1", exit_code=None,
                              checkpoint_saved=False,
                              process_exited=False)


class TestOrphanRecovery:
    def test_dead_pid_recovered_as_failed(self, store):
        w = _worker(store, gate=G0_PASS)
        w.submit_run("run1", lane="detector", command=["python3"],
                     env={}, data_hash="d", code_hash="c",
                     config_hash="f", leases=["mps"], actor="admin")
        w.mark_running("run1", pid=2**22 + 12345)  # 几乎必然不存在的 PID
        recovered = w.recover_orphans(stale_seconds=0)
        assert "run1" in recovered
        spec = store.get_training_run_v2("run1")
        assert spec["status"] == "FAILED"
        assert spec["attempt"] >= 1
        assert store.list_active_leases() == [], "orphan 恢复必须释放租约"

    def test_live_run_not_touched(self, store):
        import os
        w = _worker(store, gate=G0_PASS)
        w.submit_run("run1", lane="detector", command=["python3"],
                     env={}, data_hash="d", code_hash="c",
                     config_hash="f", leases=[], actor="admin")
        w.mark_running("run1", pid=os.getpid())  # 本进程存活
        w.record_heartbeat("run1")
        assert w.recover_orphans(stale_seconds=60) == []
        assert store.get_training_run_v2("run1")["status"] == "RUNNING"
