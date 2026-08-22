"""R2-03：并发 resume/cancel/decide 的 CAS 竞争红测试。

契约（round-2-hardening/01 §4.3）：run mutation 使用预期版本 + 预期
状态的条件更新；rowcount != 1 → 稳定 conflict，不得继续执行节点。
并发双 resume、resume+cancel、双 decide 只能一个状态转换成功，不得
重复 step/query/usage/claim。

修复前红点：
- resume 从 ('running','failed') 无新状态锁定，第二个并发 resume 可能
  在第一个推进中再次获取；
- finalize/_stop 无条件 UPDATE status，cancel 之后仍可被改写为
  succeeded（假成功）；
- service mutation 不要求 ctx（无法做 scope 复核）。
"""
from __future__ import annotations

import threading
import time

import pytest

from src.platform.cognition.errors import CognitionConflictError


def _failed_run(rsvc, rctx):
    """用一次性 read 故障制造 failed run，供并发恢复竞争。"""
    calls = {"read": 0}

    def fault(node):
        if node == "read" and calls["read"] == 0:
            calls["read"] += 1
            raise RuntimeError("boom")

    run = rsvc.start(rctx, question="年假多少天", mode="lookup",
                     fault=fault)
    assert run["status"] == "failed"
    return run


def _wait_until(pred, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return False


class TestConcurrentResume:
    def test_double_resume_no_duplicate_work(self, rsvc, rctx, store):
        run = _failed_run(rsvc, rctx)
        run_id = run["research_run_id"]
        barrier = threading.Barrier(2)
        outcomes = []
        lock = threading.Lock()

        def worker():
            barrier.wait()
            try:
                r = rsvc.resume(run_id, ctx=rctx)
                with lock:
                    outcomes.append(("ok", r["status"]))
            except CognitionConflictError as e:
                with lock:
                    outcomes.append(("conflict", str(e)))

        ts = [threading.Thread(target=worker) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=30)
        assert len(outcomes) == 2, "两个并发 resume 都必须有结果"
        final = rsvc.get_run(run_id, ctx=rctx)
        assert final["status"] == "succeeded"
        # 只推进一次：query / usage / read 成功步骤均不重复
        assert len(rsvc.list_queries(run_id, ctx=rctx)) == 1
        rows = store._conn.execute(
            "SELECT node, status FROM research_step_v1 WHERE"
            " research_run_id=? ORDER BY seq", (run_id,)).fetchall()
        read_ok = [r for r in rows if r["node"] == "read"
                   and r["status"] == "succeeded"]
        assert len(read_ok) == 1
        usage = store._conn.execute(
            "SELECT count(*) c FROM usage_event_v2 WHERE run_id=?",
            (final["business_run_id"],)).fetchone()["c"]
        assert usage == 1

    def test_second_resume_during_advance_is_noop(self, rsvc, rctx,
                                                  store):
        """推进中被再次 resume：不得二次获取推进权，不产生重复
        step/query。"""
        run = _failed_run(rsvc, rctx)
        run_id = run["research_run_id"]
        v0 = run["version"]
        gate = threading.Event()

        def block_read(node):
            if node == "read":
                gate.wait(10)

        out = {}

        def advancer():
            out["final"] = rsvc.resume(run_id, ctx=rctx,
                                       fault=block_read)

        t = threading.Thread(target=advancer)
        t.start()
        try:
            assert _wait_until(
                lambda: rsvc.get_run(run_id)["version"] > v0), \
                "第一个 resume 应先获取 CAS（version 递增）"
            steps_before = store._conn.execute(
                "SELECT count(*) c FROM research_step_v1 WHERE"
                " research_run_id=?", (run_id,)).fetchone()["c"]
            again = rsvc.resume(run_id, ctx=rctx)
            # 推进中的 run：第二次 resume 是 no-op，不得再次推进
            assert again["status"] == "running"
            steps_after = store._conn.execute(
                "SELECT count(*) c FROM research_step_v1 WHERE"
                " research_run_id=?", (run_id,)).fetchone()["c"]
            assert steps_after == steps_before
        finally:
            gate.set()
            t.join(timeout=30)
        assert out["final"]["status"] == "succeeded"
        assert len(rsvc.list_queries(run_id, ctx=rctx)) == 1


class TestResumeCancelRace:
    def test_cancel_then_resume_does_not_revive(self, rsvc, rctx, store):
        run = _failed_run(rsvc, rctx)
        run_id = run["research_run_id"]
        got = rsvc.cancel(run_id, actor="boss", ctx=rctx)
        assert got["status"] == "cancelled"
        again = rsvc.resume(run_id, ctx=rctx)
        assert again["status"] == "cancelled", "cancelled 不得被 resume 复活"
        assert rsvc.get_run(run_id, ctx=rctx)["status"] == "cancelled"

    def test_cancel_during_advance_prevents_false_success(self, rsvc,
                                                          rctx, store):
        """resume 推进中被 cancel：cancel 赢，finalize 不得把状态改写
        为 succeeded（假成功）。"""
        run = _failed_run(rsvc, rctx)
        run_id = run["research_run_id"]
        v0 = run["version"]
        gate = threading.Event()

        def block_read(node):
            if node == "read":
                gate.wait(10)

        out = {}

        def advancer():
            try:
                out["final"] = rsvc.resume(run_id, ctx=rctx,
                                           fault=block_read)
            except CognitionConflictError as e:
                out["final"] = e

        t = threading.Thread(target=advancer)
        t.start()
        try:
            assert _wait_until(
                lambda: rsvc.get_run(run_id)["version"] > v0)
            got = rsvc.cancel(run_id, actor="boss", ctx=rctx)
            assert got["status"] == "cancelled"
        finally:
            gate.set()
            t.join(timeout=30)
        final = rsvc.get_run(run_id, ctx=rctx)
        assert final["status"] == "cancelled", \
            "cancel 之后 finalize 不得写 succeeded"
        biz = store.get_business_run(final["business_run_id"])
        assert biz["status"] == "cancelled"


class TestConcurrentDecide:
    def test_double_decide_single_winner(self, rsvc, rctx, store):
        run = rsvc.start(rctx, question="机票报销上限是多少",
                         mode="lookup")
        assert run["status"] == "waiting_human"
        run_id = run["research_run_id"]
        barrier = threading.Barrier(2)
        results = {}
        lock = threading.Lock()

        def worker(i):
            barrier.wait()
            try:
                r = rsvc.decide_conflict(
                    run_id, actor=f"human-{i}",
                    resolution=f"以制度{'A' if i == 0 else 'B'}为准",
                    ctx=rctx)
                with lock:
                    results[i] = r["status"]
            except CognitionConflictError as e:
                with lock:
                    results[i] = e

        ts = [threading.Thread(target=worker, args=(i,))
              for i in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=30)
        winners = [v for v in results.values()
                   if not isinstance(v, CognitionConflictError)]
        losers = [v for v in results.values()
                  if isinstance(v, CognitionConflictError)]
        assert len(winners) == 1 and len(losers) == 1
        final = rsvc.get_run(run_id, ctx=rctx)
        assert final["status"] == "succeeded"
        # Claim 只生成一次（单轮 claim 节点）
        claims = rsvc.list_claims(run_id, ctx=rctx)
        assert len(claims) == 1
