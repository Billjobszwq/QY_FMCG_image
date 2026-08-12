"""UFC T0 红测试：终态一致性 / 证据驱动 Gate / Agent 失败账本。

指令第六节：先 RED 后 GREEN。所有测试使用独立 tmp DB，不碰运行中
真实服务。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.agents.runtime import AgentRuntime
from src.platform.control_plane import CommandGateway
from src.platform.workflow import WorkflowService

PW = "ufc-red-pw"


class _OkRecognition:
    def recognize(self, data, conf=0.25):
        return {"count": 0, "products": []}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", PW)
    adapter = _OkRecognition()
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=adapter, probe=lambda spec: None)
    build_profiles_service(bundle)
    gateway = CommandGateway(bundle.store, None,
                             recognition_adapter=adapter)
    runtime = AgentRuntime(bundle.store)
    service = WorkflowService(bundle.store, bundle.capabilities,
                              gateway, agent_runtime=runtime)
    return {"store": bundle.store, "service": service,
            "runtime": runtime, "bundle": bundle}


def _publish(env, name, spec) -> str:
    svc = env["service"]
    d = svc.create_draft(name=name, spec=spec, actor="admin")
    did = d["definition_id"]
    lint = svc.lint(did)
    assert not any(i["level"] == "error"
                   for i in lint["lint_report"]), lint["lint_report"]
    svc.simulate(did, inputs={}, actor="admin")
    svc.approve(did, actor="admin")
    svc.publish(did, actor="admin")
    return did


APPROVAL_SPEC = {"trigger": {"type": "manual"}, "variables": {},
                 "nodes": [{"id": "start", "type": "trigger"},
                           {"id": "appr", "type": "human_approval",
                            "config": {"owner": "admin",
                                       "title": "UFC 批准"}},
                           {"id": "end", "type": "end"}],
                 "edges": [{"from": "start", "to": "appr"},
                           {"from": "appr", "to": "end"}]}

PAR_SPEC = {"trigger": {"type": "manual"}, "variables": {},
            "nodes": [{"id": "start", "type": "trigger"},
                      {"id": "par", "type": "parallel",
                       "config": {"max_concurrency": 2}},
                      {"id": "b1", "type": "wait",
                       "config": {"seconds": 3}},
                      {"id": "b2", "type": "transform",
                       "config": {"map": {"x": 1}}},
                      {"id": "j", "type": "join",
                       "config": {"mode": "all"}},
                      {"id": "end", "type": "end"}],
            "edges": [{"from": "start", "to": "par"},
                      {"from": "par", "to": "b1"},
                      {"from": "par", "to": "b2"},
                      {"from": "b1", "to": "j"},
                      {"from": "b2", "to": "j"},
                      {"from": "j", "to": "end"}]}

WAIT_SPEC = {"trigger": {"type": "manual"}, "variables": {},
             "nodes": [{"id": "start", "type": "trigger"},
                       {"id": "w", "type": "wait",
                        "config": {"seconds": 60}},
                       {"id": "end", "type": "end"}],
             "edges": [{"from": "start", "to": "w"},
                       {"from": "w", "to": "end"}]}

FAIL_SPEC = {"trigger": {"type": "manual"}, "variables": {},
             "nodes": [{"id": "start", "type": "trigger"},
                       {"id": "lp", "type": "loop",
                        "config": {"items_path": "$inputs.bad",
                                   "body": "b"}},
                       {"id": "b", "type": "transform",
                        "config": {"map": {"x": 1}}},
                       {"id": "end", "type": "end"}],
             "edges": [{"from": "start", "to": "lp"},
                       {"from": "lp", "to": "end"}]}


def _start(env, did, inputs=None, wait_status="waiting_human"):
    svc, store = env["service"], env["store"]
    out = svc.start_run(did, inputs=inputs or {}, actor="admin")
    rid = out["run"]["run_id"]
    for _ in range(40):
        run = store.get_business_run(rid)
        if run["status"] in (wait_status, "failed", "succeeded",
                             "cancelled"):
            return run
        time.sleep(0.2)
    return store.get_business_run(rid)


def _works(store, run_id):
    return [dict(r) for r in store._conn.execute(
        "SELECT * FROM work_item_v2 WHERE run_id=?",
        (run_id,)).fetchall()]


class TestTerminalConsistency:
    def test_approve_converges_all_objects(self, env):
        """批准后：run=succeeded、主 work=done、approval work=done、
        无活动 approval。"""
        svc, store = env["service"], env["store"]
        did = _publish(env, "ufc-appr", APPROVAL_SPEC)
        run = _start(env, did)
        assert run["status"] == "waiting_human"
        svc.approve_run(run["run_id"], actor="admin",
                        decision="approved")
        run = store.get_business_run(run["run_id"])
        works = _works(store, run["run_id"])
        main = next(w for w in works if w["work_id"] == run["work_id"])
        approvals = [w for w in works if w["status"] == "approval"]
        appr_done = [w for w in works
                     if w["work_id"] != run["work_id"]
                     and w["status"] == "done"]
        assert run["status"] == "succeeded"
        assert main["status"] == "done", f"主 work={main['status']}"
        assert not approvals, "仍存在活动 approval 子待办"
        assert appr_done, "approval 子待办未置 done"

    def test_reject_is_explicit_decision(self, env):
        """拒绝：run=cancelled、主 work=cancelled、approval
        cancelled(rejected)、事件留痕。"""
        svc, store = env["service"], env["store"]
        did = _publish(env, "ufc-rej", APPROVAL_SPEC)
        run = _start(env, did)
        svc.approve_run(run["run_id"], actor="admin",
                        decision="rejected")
        run = store.get_business_run(run["run_id"])
        works = _works(store, run["run_id"])
        main = next(w for w in works if w["work_id"] == run["work_id"])
        appr = [w for w in works if w["work_id"] != run["work_id"]]
        assert run["status"] == "cancelled"
        assert main["status"] == "cancelled"
        assert appr and all(w["status"] == "cancelled" for w in appr)
        evs = store.list_events(run_id=run["run_id"])
        assert any(e["event_type"] == "human_approval.rejected"
                   for e in evs), "拒绝必须有明确 Decision 事件"

    def test_cancel_parallel_converges_and_stays(self, env):
        """取消运行中的 parallel：run/主 work/分支全 cancelled；
        分支线程结束后不得把 run 写回 succeeded/running。"""
        import threading
        svc, store = env["service"], env["store"]
        did = _publish(env, "ufc-par-cancel", PAR_SPEC)

        holder = {}

        def _bg():
            try:
                holder["out"] = svc.start_run(did, inputs={},
                                              actor="admin")
            except Exception as e:
                holder["err"] = str(e)

        th = threading.Thread(target=_bg, daemon=True)
        th.start()
        rid = ""
        for _ in range(50):
            rows = store._conn.execute(
                "SELECT run_id FROM business_run_v1 WHERE"
                " workflow_definition_id=? ORDER BY created_at DESC"
                " LIMIT 1", (did,)).fetchall()
            if rows:
                rid = rows[0]["run_id"]
                st = store.get_business_run(rid)["status"]
                if st == "running":
                    break
            time.sleep(0.1)
        svc.cancel_run(rid, actor="admin")
        th.join(timeout=15)  # 等分支线程自然结束
        time.sleep(0.5)
        run = store.get_business_run(rid)
        works = _works(store, rid)
        main = next(w for w in works if w["work_id"] == run["work_id"])
        branches = [dict(r) for r in store._conn.execute(
            "SELECT * FROM workflow_branch_v1 WHERE run_id=?",
            (rid,)).fetchall()]
        assert run["status"] == "cancelled", \
            f"run 被回写为 {run['status']}"
        assert main["status"] == "cancelled"
        assert branches and all(b["status"] == "cancelled"
                                for b in branches), \
            str([(b["branch_id"], b["status"]) for b in branches])
        evs = store.list_events(run_id=rid)
        assert any(e["event_type"] in ("run.cancelled",
                                       "workflow.cancelled")
                   for e in evs), "取消必须有终态事件"

    def test_cancel_waiting_timer_no_resume(self, env):
        """取消 waiting_timer：timer=cancelled，到期后不得恢复。"""
        svc, store = env["service"], env["store"]
        did = _publish(env, "ufc-wait-cancel", WAIT_SPEC)
        out = svc.start_run(did, inputs={}, actor="admin")
        rid = out["run"]["run_id"]
        run = store.get_business_run(rid)
        assert run["status"] == "waiting_timer"
        svc.cancel_run(rid, actor="admin")
        timers = [dict(r) for r in store._conn.execute(
            "SELECT * FROM workflow_timer_v1 WHERE run_id=?",
            (rid,)).fetchall()]
        assert timers and all(t["status"] == "cancelled"
                              for t in timers)
        fired = svc.resume_due_timers()
        assert not any(f["run_id"] == rid for f in fired)
        assert store.get_business_run(rid)["status"] == "cancelled"

    def test_retry_converges_projection(self, env):
        """retry 成功后：run=succeeded、主 work=done、无 blocked 残留。"""
        svc, store = env["service"], env["store"]
        did = _publish(env, "ufc-retry", FAIL_SPEC)
        out = svc.start_run(did, inputs={"bad": "not-a-list"},
                            actor="admin")
        rid = out["run"]["run_id"]
        assert store.get_business_run(rid)["status"] == "failed"
        svc.retry_run(rid, actor="admin", inputs={"bad": [1, 2]})
        run = store.get_business_run(rid)
        works = _works(store, rid)
        main = next(w for w in works if w["work_id"] == run["work_id"])
        assert run["status"] == "succeeded"
        assert main["status"] == "done"
        proj = store.rebuild_work_projection()
        item = next(i for i in proj["items"]
                    if i["work_id"] == run["work_id"])
        assert item["status"] == "done", \
            f"投影残留 {item['status']}"

    def test_projection_never_reverts_terminal(self, env):
        """rebuild 后终态不得回退为活动态。"""
        svc, store = env["service"], env["store"]
        did = _publish(env, "ufc-proj", APPROVAL_SPEC)
        run = _start(env, did)
        svc.approve_run(run["run_id"], actor="admin",
                        decision="approved")
        rid = run["run_id"]
        store.rebuild_work_projection()
        store.rebuild_work_projection()
        run2 = store.get_business_run(rid)
        works = _works(store, rid)
        assert run2["status"] == "succeeded"
        assert all(w["status"] in ("done", "cancelled")
                   for w in works), str(works)

    def test_restart_keeps_terminal_states(self, env):
        """重启（新 service 实例 + recovery）后终态仍一致。"""
        svc, store = env["service"], env["store"]
        did = _publish(env, "ufc-restart", APPROVAL_SPEC)
        run = _start(env, did)
        svc.approve_run(run["run_id"], actor="admin",
                        decision="approved")
        rid = run["run_id"]
        svc2 = WorkflowService(store, env["bundle"].capabilities,
                               None, agent_runtime=env["runtime"])
        svc2.resume_due_timers()
        svc2.recover_interrupted_parallels()
        run2 = store.get_business_run(rid)
        works = _works(store, rid)
        assert run2["status"] == "succeeded"
        assert all(w["status"] in ("done", "cancelled") for w in works)


class TestAgentFailureLineage:
    def test_missing_agent_creates_failed_run(self, env):
        """不存在 Agent：failed BusinessRun + blocked work + evidence +
        error_code。"""
        rt, store = env["runtime"], env["store"]
        from src.platform.agents.runtime import AgentRuntimeError
        with pytest.raises(AgentRuntimeError):
            rt.invoke("no_such_agent_xyz", "测试", actor="admin",
                      customer_id="c1")
        row = store._conn.execute(
            "SELECT * FROM business_run_v1 WHERE command_kind="
            "'agent.invoke' AND status='failed' ORDER BY created_at"
            " DESC LIMIT 1").fetchone()
        assert row is not None, "必须存在 failed agent BusinessRun"
        params = json.loads(row["params_json"] or "{}")
        assert params.get("error_code") == "AGENT_DEFINITION_NOT_FOUND"
        works = _works(store, row["run_id"])
        assert works and works[0]["status"] == "blocked"
        evid = store._conn.execute(
            "SELECT count(*) c FROM evidence_bundle_v1 WHERE run_id=?",
            (row["run_id"],)).fetchone()["c"]
        assert evid >= 1, "失败 Agent 必须有 Evidence"

    def test_tool_failure_not_succeeded(self, env):
        """allowlist 内关键工具失败 → run failed/partial，不得整体
        succeeded。"""
        rt, store = env["runtime"], env["store"]
        # analytics_agent 的 analytics.report.draft 在未装配 analytics
        # 时抛错（本 fixture runtime.analytics=None）
        out = None
        try:
            out = rt.invoke("analytics_agent", "建个 BI 报表草稿",
                            actor="admin")
        except Exception:
            pass
        rows = store._conn.execute(
            "SELECT status FROM business_run_v1 WHERE command_kind="
            "'agent.invoke' ORDER BY created_at DESC LIMIT 1").fetchall()
        assert rows, "必须有 agent run"
        assert rows[0]["status"] in ("failed", "partial_failed"), \
            f"关键工具失败不得 succeeded：{rows[0]['status']}"

    def test_failed_agent_usage_marked(self, env):
        """failed Agent 调用按实际消耗记 Usage 并标识失败。"""
        rt, store = env["runtime"], env["store"]
        from src.platform.agents.runtime import AgentRuntimeError
        with pytest.raises(AgentRuntimeError):
            rt.invoke("no_such_agent_u2", "x", actor="admin")
        u = store._conn.execute(
            "SELECT * FROM usage_event_v2 WHERE unit='agent_call'"
            " ORDER BY occurred_at DESC LIMIT 1").fetchone()
        assert u is not None and u["run_id"], "失败调用也需 Usage 挂链"
        run = store.get_business_run(u["run_id"])
        assert run["status"] == "failed"


class TestEvidenceDrivenGate:
    def _mk_report(self, tmp_path, ok=True):
        rep = {"ids": {k: "x" for k in (
                   "customer", "project", "tenant", "sku", "employee",
                   "survey", "assignment", "response",
                   "workflow_definition", "workflow_run", "agent_run",
                   "recognition_task", "usage", "evidence",
                   "dashboard")},
               "created": {}, "roles": {"matrix": [1]},
               "api_steps": [{"status": 200}],
               "projection": {"reconcile": {"consistent": True}},
               "events": [{"event_type": "workflow.succeeded"}],
               "hashes": {"workflow_spec": "ab"},
               "browser": {"status": "verified",
                           "files": ["qa_probe.png"]},
               "latency": {"p50_ms": 1}, "recovery": {"executed": True},
               "failures": [], "relations": {"x": 1},
               "checks": [{"check": "a", "ok": ok}],
               "passed": 1 if ok else 0,
               "failed": 0 if ok else 1}
        p = tmp_path / "report.json"
        p.write_text(json.dumps(rep), encoding="utf-8")
        return p

    def test_check_failure_blocks_gate(self, env, tmp_path):
        """报告中任一 check.ok=false / failed>0 → BLOCKED。"""
        from src.platform.gate_evaluator import evaluate_gate_from_evidence
        rep = self._mk_report(tmp_path, ok=False)
        res = evaluate_gate_from_evidence(
            store=env["store"], uat_report_path=rep)
        assert res["gate"] != "READY_FOR_REAL_DATA_UAT"
        assert res["reasons"]

    def test_terminal_drift_blocks_gate(self, env, tmp_path):
        """DB 存在 Run/Work 终态漂移 → BLOCKED。"""
        from src.platform.gate_evaluator import evaluate_gate_from_evidence
        store = env["store"]
        # 制造漂移：cancelled run + running 主 work
        store._conn.execute(
            "INSERT INTO business_run_v1 (run_id, work_id, status,"
            " command_kind, created_at, updated_at) VALUES"
            " ('run-drift1', 'work-drift1', 'cancelled', 'workflow.run',"
            " datetime('now'), datetime('now'))")
        store._conn.execute(
            "INSERT INTO work_item_v2 (work_id, run_id, status, title,"
            " created_at, updated_at) VALUES ('work-drift1',"
            " 'run-drift1', 'running', '漂移', datetime('now'),"
            " datetime('now'))")
        store._conn.commit()
        rep = self._mk_report(tmp_path, ok=True)
        res = evaluate_gate_from_evidence(store=store,
                                          uat_report_path=rep)
        assert res["gate"].startswith("BLOCKED"), res["gate"]

    def test_open_p0_blocks_gate(self, env, tmp_path):
        """ISSUES 存在 OPEN P0/P1 → BLOCKED。"""
        from src.platform.gate_evaluator import evaluate_gate_from_evidence
        issues = tmp_path / "ISSUES.md"
        issues.write_text("| X-1 | P0 | OPEN | 未关闭问题 |\n",
                          encoding="utf-8")
        rep = self._mk_report(tmp_path, ok=True)
        res = evaluate_gate_from_evidence(store=env["store"],
                                          uat_report_path=rep,
                                          issue_ledger_path=issues)
        assert res["gate"].startswith("BLOCKED")
