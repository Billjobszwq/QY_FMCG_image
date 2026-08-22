"""R2-04（R2-P1-03）：Research 终态 UoW 与错误诚实性红测试。

契约（round-2-hardening/01 §5）：
- finalize 必须在同一显式 UoW 中收敛 report/evidence/research/business/
  work/event；
- 任一步失败：整体回滚，不得写 succeeded；错误分类为稳定 stop reason；
- 引证门失败不得产生假成功；
- 失败后 run 可 resume（retryable），恢复后账本完整。

修复前红点：`_node_finalize` 的 evidence/business 写入被
`except Exception: pass` 吞掉，research run 仍可写 succeeded。
"""
from __future__ import annotations

import pytest

UOW_STEPS = ["_uow_report", "_uow_evidence", "_uow_business",
             "_uow_work", "_uow_event"]


def _counts(store, run) -> dict:
    rid, bid = run["research_run_id"], run["business_run_id"]
    c = store._conn
    work_id = c.execute("SELECT work_id FROM business_run_v1 WHERE"
                        " run_id=?", (bid,)).fetchone()["work_id"]
    return {
        "reports": c.execute(
            "SELECT count(*) c FROM research_report_v1 WHERE"
            " research_run_id=?", (rid,)).fetchone()["c"],
        "evidence": c.execute(
            "SELECT count(*) c FROM evidence_bundle_v1 WHERE run_id=?",
            (bid,)).fetchone()["c"],
        "business_status": store.get_business_run(bid)["status"],
        "work_status": c.execute(
            "SELECT status FROM work_item_v2 WHERE work_id=?",
            (work_id,)).fetchone()["status"],
        "completed_events": c.execute(
            "SELECT count(*) c FROM event_envelope_v1 WHERE run_id=? AND"
            " event_type='research.completed'", (bid,)).fetchone()["c"],
    }


class TestTerminalUoWFaultInjection:
    @pytest.mark.parametrize("target", UOW_STEPS)
    def test_any_ledger_failure_rolls_back_and_fails_run(
            self, rsvc, rctx, store, target):
        def boom(*a, **k):
            raise RuntimeError(f"{target} 故障注入")

        setattr(rsvc, target, boom)
        run = rsvc.start(rctx, question="年假多少天", mode="lookup")
        # 不得假成功
        assert run["status"] == "failed"
        assert run["stop_reason"] == "integrity:finalize"
        got = _counts(store, run)
        # UoW 整体回滚：任何账本都不得留下半提交终态
        assert got["reports"] == 0, "report 必须随 UoW 回滚"
        assert got["evidence"] == 0, "evidence 必须随 UoW 回滚"
        assert got["business_status"] == "failed", \
            f"business 不得 succeeded/漂移: {got['business_status']}"
        assert got["work_status"] != "completed"
        assert got["completed_events"] == 0
        # 错误分类保留在 step 账本
        steps = store._conn.execute(
            "SELECT node, status, output_json, error FROM"
            " research_step_v1 WHERE research_run_id=? AND"
            " node='finalize'", (run["research_run_id"],)).fetchall()
        assert steps and steps[-1]["status"] == "failed"
        assert "terminal_uow_failed" in (steps[-1]["error"]
                                         + steps[-1]["output_json"])

    def test_terminal_failure_is_retryable_via_resume(self, rsvc, rctx,
                                                      store):
        # 瞬态故障：首次真实写路径失败，之后恢复真实行为（模拟 I/O
        # 抖动），验证 failed run 可经 resume 达成完整终态账本。
        orig = rsvc._uow_evidence
        calls = {"n": 0}

        def once(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("一次性 evidence 故障（瞬态）")
            return orig(*a, **k)

        rsvc._uow_evidence = once
        run = rsvc.start(rctx, question="年假多少天", mode="lookup")
        assert run["status"] == "failed"
        # 故障消失后 resume：终态 UoW 成功，账本完整
        done = rsvc.resume(run["research_run_id"], ctx=rctx)
        assert done["status"] == "succeeded"
        got = _counts(store, done)
        assert got["reports"] == 1
        assert got["evidence"] == 1
        assert got["business_status"] == "succeeded"
        assert got["work_status"] == "completed"
        assert got["completed_events"] == 1


class TestCitationGateAtFinalize:
    def test_gate_failure_blocks_success(self, rsvc, rctx, store):
        rsvc.verifier.verify_run = lambda *a, **k: {
            "gate_ok": False, "blocking_claims": ["clm-x"], "verdicts": []}
        run = rsvc.start(rctx, question="年假多少天", mode="lookup")
        assert run["status"] == "failed"
        assert run["stop_reason"] == "policy_denied:finalize"
        got = _counts(store, run)
        assert got["reports"] == 0
        assert got["evidence"] == 0
        assert got["business_status"] == "failed"


class TestTerminalLedgersComplete:
    def test_success_writes_all_ledgers_atomically(self, rsvc, rctx,
                                                   store):
        run = rsvc.start(rctx, question="年假多少天", mode="lookup")
        assert run["status"] == "succeeded"
        got = _counts(store, run)
        assert got["reports"] == 1
        assert got["evidence"] == 1
        assert got["business_status"] == "succeeded"
        assert got["work_status"] == "completed"
        assert got["completed_events"] == 1
        # outbox 同事务落账
        bid = run["business_run_id"]
        evt = store._conn.execute(
            "SELECT event_id FROM event_envelope_v1 WHERE run_id=? AND"
            " event_type='research.completed'", (bid,)).fetchone()
        ob = store._conn.execute(
            "SELECT count(*) c FROM outbox_v1 WHERE event_id=?",
            (evt["event_id"],)).fetchone()["c"]
        assert ob == 1
