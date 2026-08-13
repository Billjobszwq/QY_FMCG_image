"""OSV51 W1-a（契约 C-5）：并行工作流引擎终态零漂移压力测试。

≥100 轮随机抖动调度（OSV51_STRESS_ROUNDS 只允许上调），覆盖：
- join all / any / quorum 三种模式；
- 外部取消（running 期间 cancel_run）；
- branch timeout（全超时 / 完成与超时混合）；
- 超时驱动 run 终态收敛（timeout → run failed + finalize 分支收敛）；
- 重启恢复（recover_interrupted_parallels 分支粒度重跑）。

零漂移不变式（每轮断言）：
1. run 终态后所有分支行必须处于终态
   （completed/failed/timeout/cancelled）；
2. 执行期间任何时刻观察到的分支终态必须永远保持——后到写者不得
   降级/改写（timeout 绝不得变 cancelled/completed，反之亦然）；
3. 排空被放弃的 worker 线程（wfbr-*）前后双读一致（迟到写被条件
   UPDATE rowcount=0 拒绝，不产生 durable 漂移）。

确定性：断言只依赖“有界等待 + 状态轮询”（drain 到无遗留 worker 再
双读），不依赖 sleep 计时落点。
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
from pathlib import Path

import pytest

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.agents.runtime import AgentRuntime
from src.platform.control_plane import CommandGateway
from src.platform.workflow import WorkflowService

BRANCH_TERMINAL = ("completed", "failed", "timeout", "cancelled")
ROUNDS = max(100, int(os.environ.get("OSV51_STRESS_ROUNDS", "100")))
SEED = int(os.environ.get("OSV51_STRESS_SEED", "20260813"))


class _OkRecognition:
    def recognize(self, data, conf=0.25):
        return {"count": 0, "products": []}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "osv51-stress-pw")
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


def _wait_branch(entry: str, seconds: float) -> dict:
    return {"id": entry, "type": "wait", "config": {"seconds": seconds}}


def _failing_branch(entry: str) -> dict:
    return {"id": entry, "type": "loop",
            "config": {"items_path": "inputs.bad", "body": "end"}}


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


def _publish(env, name: str, spec: dict) -> str:
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


def _drain_branch_workers(timeout: float = 15.0) -> None:
    """有界等待所有 wfbr-* 分支 worker 线程退出（迟到写全部落定）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        alive = [t for t in threading.enumerate()
                 if t.name.startswith("wfbr")]
        if not alive:
            return
        time.sleep(0.02)


def _branch_statuses(store, run_id: str) -> dict[str, str]:
    rows = store._conn.execute(
        "SELECT branch_id, status FROM workflow_branch_v1"
        " WHERE run_id=?", (run_id,)).fetchall()
    return {r["branch_id"]: r["status"] for r in rows}


class _TerminalObserver(threading.Thread):
    """执行期轮询分支行，记录每个分支首次被观察到的终态。

    C-5 不变式：首次观察到的终态必须永远保持（终态互不覆盖）。
    """

    def __init__(self, store, run_id: str, stop_evt: threading.Event):
        super().__init__(daemon=True, name="osv51-obs")
        self.store = store
        self.run_id = run_id
        self.stop_evt = stop_evt
        self.first_terminal: dict[str, str] = {}

    def run(self) -> None:
        while not self.stop_evt.is_set():
            try:
                for bid, st in _branch_statuses(
                        self.store, self.run_id).items():
                    if st in BRANCH_TERMINAL and bid \
                            not in self.first_terminal:
                        self.first_terminal[bid] = st
            except Exception:
                pass  # 观察失败不影响主断言（双读仍兜底）
            time.sleep(0.005)


def _start_run_async(env, did: str, inputs: dict) -> tuple:
    """后台线程跑同步 start_run；返回 (thread, result_box)。"""
    res: dict = {}

    def _go():
        try:
            res["out"] = env["service"].start_run(
                did, inputs=inputs, actor="admin")
        except Exception as e:  # noqa: BLE001 —— 记录供断言
            res["error"] = repr(e)

    t = threading.Thread(target=_go, name="osv51-run")
    t.start()
    return t, res


def _await_run_row(store, did: str, timeout: float = 10.0) -> str:
    """轮询直到本轮 run 行出现（queued/running），返回 run_id。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = store._conn.execute(
            "SELECT run_id FROM business_run_v1 WHERE"
            " workflow_definition_id=? AND status IN"
            " ('queued','running') ORDER BY rowid DESC LIMIT 1",
            (did,)).fetchone()
        if row:
            return row["run_id"]
        time.sleep(0.005)
    raise AssertionError("run 行未在 10s 内出现")


def _assert_zero_drift(env, run_id: str,
                       obs: _TerminalObserver | None, ctx: str) -> None:
    """终态零漂移三断言：全终态 + 观察终态保持 + drain 前后双读一致。"""
    store = env["store"]
    final1 = _branch_statuses(store, run_id)
    _drain_branch_workers()
    final2 = _branch_statuses(store, run_id)
    assert final1 == final2, (
        f"[{ctx}] run={run_id} 迟到写造成 durable 漂移：{final1} →"
        f" {final2}")
    nonterminal = {b: s for b, s in final2.items()
                   if s not in BRANCH_TERMINAL}
    assert not nonterminal, (
        f"[{ctx}] run={run_id} run 终态后仍有非终态分支：{nonterminal}")
    if obs is not None:
        for bid, st in obs.first_terminal.items():
            assert final2.get(bid) == st, (
                f"[{ctx}] run={run_id} 分支 {bid} 终态漂移：曾观察"
                f" {st} → 最终 {final2.get(bid)}（C-5 终态优先级："
                "先到且合法者赢，后到者无条件放弃）")


@pytest.fixture()
def defs(env):
    """一次性发布的可复用定义池（轮次只 start_run，摊薄发布开销）。"""
    return {
        "all_fast": _publish(env, "stress-all-fast", _par_spec(
            [_wait_branch("b1", 0.03), _wait_branch("b2", 0.03)],
            {"mode": "all"})),
        "all_three": _publish(env, "stress-all-three", _par_spec(
            [_wait_branch("b1", 0.02), _wait_branch("b2", 0.03),
             _wait_branch("b3", 0.04)],
            {"mode": "all"})),
        "any_mix": _publish(env, "stress-any-mix", _par_spec(
            [_failing_branch("b1"), _wait_branch("b2", 0.04),
             _wait_branch("b3", 0.04)],
            {"mode": "any"})),
        "quorum_2of3": _publish(env, "stress-quorum", _par_spec(
            [_wait_branch("b1", 0.03), _wait_branch("b2", 0.04),
             _wait_branch("b3", 0.05)],
            {"mode": "quorum", "quorum": 2})),
        "timeout_all": _publish(env, "stress-timeout-all", _par_spec(
            [_wait_branch("b1", 0.9), _wait_branch("b2", 0.9)],
            {"mode": "all"},
            par_cfg={"max_concurrency": 2,
                     "branch_timeout_seconds": 0.15})),
        "timeout_mixed": _publish(env, "stress-timeout-mixed", _par_spec(
            [_wait_branch("b1", 0.03), _wait_branch("b2", 0.9)],
            {"mode": "all"},
            par_cfg={"max_concurrency": 2,
                     "branch_timeout_seconds": 0.15})),
        "cancel_target": _publish(env, "stress-cancel", _par_spec(
            [_wait_branch("b1", 0.6), _wait_branch("b2", 0.6),
             _wait_branch("b3", 0.6)],
            {"mode": "all"})),
        "recovery_target": _publish(env, "stress-recovery", _par_spec(
            [_wait_branch("b1", 0.03), _wait_branch("b2", 0.03)],
            {"mode": "all"})),
    }


SCENARIOS = (["all_fast"] * 12 + ["all_three"] * 10 + ["any_mix"] * 12
             + ["quorum_2of3"] * 12 + ["timeout_all"] * 14
             + ["timeout_mixed"] * 14 + ["cancel"] * 16
             + ["recovery"] * 10)


class TestParallelTerminalStress:
    def test_stress_terminal_state_zero_drift(self, env, defs):
        """≥100 轮随机场景压力：终态零漂移（见模块 docstring）。"""
        rng = random.Random(SEED)
        store, svc = env["store"], env["service"]
        order = [rng.choice(SCENARIOS) for _ in range(ROUNDS)]
        for i, scen in enumerate(order):
            ctx = f"round {i}/{ROUNDS} scen={scen}"
            if scen == "recovery":
                self._round_recovery(env, defs, i)
                continue
            did = defs["cancel_target"] if scen == "cancel" \
                else defs[scen]
            inputs = {"bad": "not-a-list"} if scen == "any_mix" else {}
            t, res = _start_run_async(env, did, inputs)
            run_id = _await_run_row(store, did)
            obs = _TerminalObserver(store, run_id,
                                    threading.Event())
            obs.start()
            if scen == "cancel":
                # 抖动取消时点：落在分支执行窗口内
                time.sleep(rng.uniform(0.08, 0.3))
                svc.cancel_run(run_id, actor="stress")
            t.join(timeout=30)
            obs.stop_evt.set()
            obs.join(timeout=5)
            assert "error" not in res, f"[{ctx}] start_run 异常: {res}"
            run = res["out"]["run"]
            assert run["status"] in ("succeeded", "failed",
                                     "cancelled"), f"[{ctx}] {run}"
            final = _branch_statuses(store, run_id)
            if scen in ("all_fast", "all_three"):
                assert run["status"] == "succeeded", f"[{ctx}] {run}"
                assert set(final.values()) == {"completed"}, \
                    f"[{ctx}] {final}"
            elif scen == "any_mix":
                assert run["status"] == "succeeded", f"[{ctx}] {run}"
                assert sum(1 for s in final.values()
                           if s == "completed") >= 1, \
                    f"[{ctx}] {final}"
            elif scen == "quorum_2of3":
                assert run["status"] == "succeeded", f"[{ctx}] {run}"
                assert sum(1 for s in final.values()
                           if s == "completed") >= 2, \
                    f"[{ctx}] {final}"
            elif scen == "timeout_all":
                # 超时驱动 run 终态：run failed 且 timeout 必须保持
                assert run["status"] == "failed", f"[{ctx}] {run}"
                assert set(final.values()) == {"timeout"}, \
                    f"[{ctx}] {final}"
            elif scen == "timeout_mixed":
                assert run["status"] == "failed", f"[{ctx}] {run}"
                assert "timeout" in final.values(), f"[{ctx}] {final}"
                assert "completed" in final.values(), \
                    f"[{ctx}] {final}"
            elif scen == "cancel":
                # 取消大概率落在执行窗口；晚到则 run 已成功——两者
                # 都必须满足零漂移（下方统一断言）。
                assert run["status"] in ("cancelled", "succeeded"), \
                    f"[{ctx}] {run}"
            _assert_zero_drift(env, run_id, obs, ctx)

    def _round_recovery(self, env, defs, i: int) -> None:
        """重启恢复轮：伪造崩溃现场（running run + 非终态分支），
        recover_interrupted_parallels 分支粒度重跑至成功。"""
        store, svc = env["store"], env["service"]
        did = defs["recovery_target"]
        run_id, work_id = f"run-stressrec-{i}", f"work-stressrec-{i}"
        store.insert_business_run({
            "run_id": run_id, "work_id": work_id,
            "trigger_type": "manual", "status": "running",
            "command_kind": "workflow.run",
            "workflow_definition_id": did, "workflow_version": "1",
            "correlation_id": f"corr-stressrec-{i}"})
        store.insert_work_item_v2({
            "work_id": work_id, "run_id": run_id, "status": "running",
            "title": f"压力恢复 {i}", "owner_type": "system",
            "owner_id": "workflow_runtime"})
        now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        for j, entry in enumerate(("b1", "b2")):
            # 抖动：pending / running 混合现场
            st = "running" if (i + j) % 2 else "pending"
            store._conn.execute(
                "INSERT INTO workflow_branch_v1 (branch_id, run_id,"
                " node_id, branch_index, status, output_json,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (f"br-stressrec-{i}-{j}", run_id, "par", j, st,
                 json.dumps({"entry": entry}), now, now))
        store._conn.commit()
        recovered = svc.recover_interrupted_parallels()
        assert any(r["run_id"] == run_id for r in recovered), \
            f"round {i} 恢复未命中 {run_id}"
        run = store.get_business_run(run_id)
        assert run["status"] == "succeeded", f"round {i}: {run}"
        final = _branch_statuses(store, run_id)
        assert set(final.values()) == {"completed"}, \
            f"round {i}: {final}"
        _assert_zero_drift(env, run_id, None, f"recovery round {i}")
