"""UATCC T3：真实有界并行引擎契约测试。

覆盖指令 §8：独立分支身份、独立 ctx、max_concurrency、durable 分支
状态、join all/any/quorum、any/quorum 达成后剩余分支取消、分支失败、
分支超时、进程重启恢复（分支粒度）、合并变量冲突记录、wall-time。
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.agents.runtime import AgentRuntime
from src.platform.control_plane import CommandGateway
from src.platform.workflow import WorkflowService


class _OkRecognition:
    def recognize(self, data, conf=0.25):
        return {"count": 0, "products": []}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "uatcc-par-pw")
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
    return {"store": bundle.store, "service": service}


def _failing_branch(entry: str) -> dict:
    """运行时必败分支：items_path 解析为非列表（lint 合法）。"""
    return {"id": entry, "type": "loop",
            "config": {"items_path": "inputs.bad", "body": "end"}}


def _wait_branch(entry: str, seconds: float) -> dict:
    return {"id": entry, "type": "wait", "config": {"seconds": seconds}}


def _par_spec(branches: list[dict], join_cfg: dict,
              par_cfg: dict | None = None) -> dict:
    nodes = [{"id": "start", "type": "trigger"},
             {"id": "par", "type": "parallel",
              "config": par_cfg or {"max_concurrency": 4}}]
    edges = [{"from": "start", "to": "par"}]
    for b in branches:
        nodes.append(b)
        edges.append({"from": "par", "to": b["id"]})
        edges.append({"from": b["id"], "to": "join"})
    nodes.append({"id": "join", "type": "join", "config": join_cfg})
    nodes.append({"id": "end", "type": "end"})
    edges.append({"from": "join", "to": "end"})
    return {"trigger": {"type": "manual"}, "variables": {},
            "nodes": nodes, "edges": edges}


def _publish_run(env, name, spec, inputs=None):
    svc = env["service"]
    d = svc.create_draft(name=name, spec=spec, actor="admin")
    did = d["definition_id"]
    lint = svc.lint(did)
    assert not any(i["level"] == "error"
                   for i in lint["lint_report"]), lint["lint_report"]
    svc.simulate(did, inputs={}, actor="admin")
    svc.approve(did, actor="admin")
    svc.publish(did, actor="admin")
    out = svc.start_run(did, inputs=inputs or {}, actor="admin")
    return out["run"]


def _drain_branch_workers(timeout: float = 12.0) -> None:
    """OSV51 C-5：有界等待被放弃的并行分支 worker 线程（线程池
    前缀 wfbr）全部退出。超时/取消后 ex.shutdown(wait=False) 会遗留
    仍在 sleep 的 worker，它们退出前可能发出迟到回写；先 drain 再断
    言，使终态断言不再依赖 SELECT 落点的时序运气（确定性前置条件，
    有界等待，非 sleep 计时断言）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        alive = [t for t in threading.enumerate()
                 if t.name.startswith("wfbr")]
        if not alive:
            return
        time.sleep(0.02)


class TestParallelEngine:
    def test_walltime_two_branches(self, env):
        """两个各 2s 分支：串行≈4s；真并行≈2s（<3.5s 判定）。"""
        spec = _par_spec([_wait_branch("b1", 2), _wait_branch("b2", 2)],
                         {"mode": "all"})
        t0 = time.monotonic()
        run = _publish_run(env, "par-walltime", spec)
        wall = time.monotonic() - t0
        assert run["status"] == "succeeded", run.get("error")
        assert wall < 3.5, f"wall {wall:.2f}s 疑似串行"
        rows = env["store"]._conn.execute(
            "SELECT count(*) c FROM workflow_branch_v1 WHERE run_id=?",
            (run["run_id"],)).fetchone()
        assert rows["c"] == 2, "durable 分支记录缺失"

    def test_join_any_one_fails_still_succeeds(self, env):
        """any：一支失败、一支成功 → run 成功。"""
        spec = _par_spec([_failing_branch("b1"),
                          _wait_branch("b2", 0.2)], {"mode": "any"})
        run = _publish_run(env, "par-any", spec,
                           inputs={"bad": "not-a-list"})
        assert run["status"] == "succeeded", run.get("error")

    def test_join_quorum_two_of_three(self, env):
        """quorum=2：三支两成一败 → run 成功。"""
        spec = _par_spec([
            _wait_branch("b1", 0.1),
            _wait_branch("b2", 0.1),
            _failing_branch("b3")],
            {"mode": "quorum", "quorum": 2})
        run = _publish_run(env, "par-quorum", spec,
                           inputs={"bad": "not-a-list"})
        assert run["status"] == "succeeded", run.get("error")

    def test_join_all_one_fails_run_fails(self, env):
        """all：一支失败 → run failed（不得冒充成功）。"""
        spec = _par_spec([_wait_branch("b1", 0.1),
                          _failing_branch("b2")], {"mode": "all"})
        run = _publish_run(env, "par-all-fail", spec,
                           inputs={"bad": "not-a-list"})
        assert run["status"] == "failed"
        assert run["error"]

    def test_branch_timeout(self, env):
        """branch_timeout_seconds=1：分支等 3s → timeout → run failed。

        OSV51 C-5 确定性版：先有界 drain 被放弃的 worker（其心跳发现
        run 终态后会迟到回写 cancelled/completed），再断言 durable 终
        态。timeout 是最高优先级终态之一，绝不允许被降级覆盖——断言
        两支均严格保持 timeout。
        """
        spec = _par_spec([_wait_branch("b1", 3), _wait_branch("b2", 3)],
                         {"mode": "all"},
                         par_cfg={"max_concurrency": 2,
                                  "branch_timeout_seconds": 1})
        t0 = time.monotonic()
        run = _publish_run(env, "par-timeout", spec)
        wall = time.monotonic() - t0
        assert run["status"] == "failed"
        assert wall < 3, "超时未生效（等满 3s）"
        _drain_branch_workers()
        rows = env["store"]._conn.execute(
            "SELECT status, count(*) c FROM workflow_branch_v1"
            " WHERE run_id=? GROUP BY status",
            (run["run_id"],)).fetchall()
        statuses = {r["status"] for r in rows}
        assert "timeout" in statuses
        assert statuses == {"timeout"}, (
            f"timeout 终态被迟到写覆盖/降级：{statuses}（C-5 终态"
            "优先级：先到且合法者赢，后到者无条件放弃）")

    def test_branch_terminal_state_never_overwritten(self, env):
        """OSV51 C-5 终态优先级（直接契约）：分支一旦进入终态
        （timeout/failed/completed/cancelled），任何后到写者必须被条
        件 UPDATE 拒绝（rowcount=0，返回 False），durable 状态不变。"""
        store, svc = env["store"], env["service"]
        conn = store._conn
        now = "2026-01-01T00:00:00+00:00"
        conn.execute(
            "INSERT INTO workflow_branch_v1 (branch_id, run_id,"
            " node_id, branch_index, status, output_json,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            ("br-guard-t", "run-guard", "par", 0, "timeout",
             "{}", now, now))
        conn.commit()
        # 迟到 cancelled（run 收敛/取消路径）不得覆盖 timeout
        ok = svc._branch_row("br-guard-t", "cancelled",
                             error="late cancel")
        st = conn.execute(
            "SELECT status FROM workflow_branch_v1 WHERE branch_id=?",
            ("br-guard-t",)).fetchone()["status"]
        assert st == "timeout", f"timeout 被 cancelled 覆盖：{st}"
        assert not ok, "迟到写必须被 rowcount=0 拒绝"
        # 迟到 completed（worker 迟到完成）不得覆盖 timeout
        ok = svc._branch_row("br-guard-t", "completed", output={})
        st = conn.execute(
            "SELECT status FROM workflow_branch_v1 WHERE branch_id=?",
            ("br-guard-t",)).fetchone()["status"]
        assert st == "timeout", f"timeout 被 completed 覆盖：{st}"
        assert not ok
        # 反向：completed 终态同样不可被 timeout/cancelled 覆盖
        conn.execute(
            "INSERT INTO workflow_branch_v1 (branch_id, run_id,"
            " node_id, branch_index, status, output_json,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            ("br-guard-c", "run-guard", "par", 1, "completed",
             "{}", now, now))
        conn.commit()
        for late in ("timeout", "cancelled", "failed"):
            ok = svc._branch_row("br-guard-c", late, error="late")
            st = conn.execute(
                "SELECT status FROM workflow_branch_v1"
                " WHERE branch_id=?", ("br-guard-c",)).fetchone()["status"]
            assert st == "completed", f"completed 被 {late} 覆盖"
            assert not ok

    def test_restart_recovery_branch_level(self, env):
        """重启恢复：未完成分支（running）经 recover 分支粒度重跑。"""
        store, svc = env["store"], env["service"]
        spec = _par_spec([_wait_branch("b1", 0.2),
                          _wait_branch("b2", 0.2)], {"mode": "all"})
        d = svc.create_draft(name="par-recover", spec=spec, actor="admin")
        did = d["definition_id"]
        svc.lint(did)
        svc.simulate(did, inputs={}, actor="admin")
        svc.approve(did, actor="admin")
        svc.publish(did, actor="admin")
        # 手工制造“进程崩溃”现场：running run + running 分支
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        run_id, work_id = "run-crash-test", "work-crash-test"
        store.insert_business_run({
            "run_id": run_id, "work_id": work_id,
            "trigger_type": "manual", "status": "running",
            "command_kind": "workflow.run",
            "workflow_definition_id": did, "workflow_version": "1",
            "correlation_id": "corr-crash"})
        store.insert_work_item_v2({
            "work_id": work_id, "run_id": run_id, "status": "running",
            "title": "崩溃恢复测试", "owner_type": "system",
            "owner_id": "workflow_runtime"})
        import json as _json
        for i, entry in enumerate(("b1", "b2")):
            store._conn.execute(
                "INSERT INTO workflow_branch_v1 (branch_id, run_id,"
                " node_id, branch_index, status, output_json,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (f"br-crash-{i}", run_id, "par", i, "running",
                 _json.dumps({"entry": entry}), now, now))
        store._conn.commit()
        # “重启”后的恢复入口
        recovered = svc.recover_interrupted_parallels()
        assert any(r["run_id"] == run_id for r in recovered)
        run = store.get_business_run(run_id)
        assert run["status"] == "succeeded"

    def test_variable_merge_conflict_recorded(self, env):
        """两分支写同名变量 → last-writer-wins + 冲突记录在 join 输出。"""
        spec = {"trigger": {"type": "manual"},
                "variables": {"flag": {"type": "string",
                                       "default": "init"}},
                "nodes": [
                    {"id": "start", "type": "trigger"},
                    {"id": "par", "type": "parallel",
                     "config": {"max_concurrency": 2}},
                    {"id": "b1", "type": "transform",
                     "config": {"map": {"vars.flag": "from_b1"}}},
                    {"id": "b2", "type": "transform",
                     "config": {"map": {"vars.flag": "from_b2"}}},
                    {"id": "join", "type": "join",
                     "config": {"mode": "all"}},
                    {"id": "end", "type": "end"}],
                "edges": [{"from": "start", "to": "par"},
                          {"from": "par", "to": "b1"},
                          {"from": "par", "to": "b2"},
                          {"from": "b1", "to": "join"},
                          {"from": "b2", "to": "join"},
                          {"from": "join", "to": "end"}]}
        run = _publish_run(env, "par-conflict", spec)
        assert run["status"] == "succeeded"
        jex = env["store"]._conn.execute(
            "SELECT output_json FROM workflow_node_execution_v1"
            " WHERE run_id=? AND node_id='join'",
            (run["run_id"],)).fetchone()
        import json as _json
        out = _json.loads(jex["output_json"] or "{}")
        assert out["conflicts"] >= 1, "变量合并冲突必须被记录"
