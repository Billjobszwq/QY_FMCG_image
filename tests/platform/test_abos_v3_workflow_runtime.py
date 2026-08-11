"""ABOSV3 T5 红测试：可视化工作流的后端运行时升级。

要求（AGENT-EXECUTION-PROMPT §T5、02 文档 §3）：
- wait = 持久化 timer：run 进入 waiting_timer，到期恢复；重启（新
  service 实例、同一 store）后仍可恢复；
- parallel 扇出 + join all/any/quorum（缺分支记录 missing）；
- agent 节点调用指定 Agent（真实工具循环，不固定 Supervisor）；
- UI 坐标不参与定义 hash；
- lint 覆盖 wait/join 配置。
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.agents.runtime import AgentRuntime
from src.platform.control_plane import CommandGateway
from src.platform.workflow import WorkflowService


class _OkRecognition:
    def recognize(self, data: bytes, conf: float = 0.25):
        return {"count": 1, "products": [{"name": "SKU-X", "count": 1}]}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "v3-wf-pw")
    adapter = _OkRecognition()
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=adapter, probe=lambda spec: None)
    profiles = build_profiles_service(bundle)
    gateway = CommandGateway(bundle.store, profiles,
                             recognition_adapter=adapter)
    runtime = AgentRuntime(bundle.store)
    service = WorkflowService(bundle.store, bundle.capabilities,
                              gateway, agent_runtime=runtime)
    return {"store": bundle.store, "service": service,
            "gateway": gateway, "runtime": runtime}


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


WAIT_SPEC = {"trigger": {"type": "manual"}, "variables": {},
             "nodes": [{"id": "start", "type": "trigger"},
                       {"id": "w", "type": "wait",
                        "config": {"seconds": 0.2}},
                       {"id": "end", "type": "end"}],
             "edges": [{"from": "start", "to": "w"},
                       {"from": "w", "to": "end"}]}

PARALLEL_SPEC = {"trigger": {"type": "manual"}, "variables": {},
                 "nodes": [{"id": "start", "type": "trigger"},
                           {"id": "par", "type": "parallel",
                            "config": {"max_concurrency": 1}},
                           {"id": "b1", "type": "transform",
                            "config": {"map": {"a": 1}}},
                           {"id": "b2", "type": "transform",
                            "config": {"map": {"b": 2}}},
                           {"id": "j", "type": "join",
                            "config": {"mode": "all"}},
                           {"id": "end", "type": "end"}],
                 "edges": [{"from": "start", "to": "par"},
                           {"from": "par", "to": "b1"},
                           {"from": "par", "to": "b2"},
                           {"from": "b1", "to": "j"},
                           {"from": "b2", "to": "j"},
                           {"from": "j", "to": "end"}]}


class TestWaitTimer:
    def test_wait_persists_and_recovers_after_restart(self, env):
        did = _publish(env, "等待链", WAIT_SPEC)
        out = env["service"].start_run(did, inputs={}, actor="admin")
        run = env["store"].get_business_run(out["run"]["run_id"])
        assert run["status"] == "waiting_timer", run["status"]
        timers = env["service"].list_timers(status="pending")
        assert timers and timers[0]["run_id"] == run["run_id"]
        # 模拟重启：新 service 实例（同一 store）到期恢复
        time.sleep(0.3)
        svc2 = WorkflowService(env["store"], env["service"].caps,
                               env["gateway"])
        fired = svc2.resume_due_timers()
        assert fired, "到期 timer 必须被恢复（重启后不丢）"
        run = env["store"].get_business_run(run["run_id"])
        assert run["status"] == "succeeded"
        # 投影：waiting_timer 期间 work=waiting；完成后 done
        proj = env["store"].rebuild_work_projection()
        mine = next(i for i in proj["items"]
                    if i["work_id"] == run["work_id"])
        assert mine["status"] == "done"

    def test_lint_rejects_bad_wait(self, env):
        bad = {"trigger": {"type": "manual"}, "variables": {},
               "nodes": [{"id": "start", "type": "trigger"},
                         {"id": "w", "type": "wait",
                          "config": {"seconds": "abc"}},
                         {"id": "end", "type": "end"}],
               "edges": [{"from": "start", "to": "w"},
                         {"from": "w", "to": "end"}]}
        d = env["service"].create_draft(name="坏等待", spec=bad,
                                        actor="admin")
        rep = env["service"].lint(d["definition_id"])["lint_report"]
        assert any(i["code"] == "wait_seconds" for i in rep)


class TestParallelJoin:
    def test_join_all_after_parallel(self, env):
        did = _publish(env, "并行链", PARALLEL_SPEC)
        out = env["service"].start_run(did, inputs={}, actor="admin")
        run = env["store"].get_business_run(out["run"]["run_id"])
        assert run["status"] == "succeeded", run
        nodes = env["store"].list_node_executions(run["run_id"])
        join = next(n for n in nodes if n["node_id"] == "j")
        assert join["status"] == "succeeded"
        assert sorted(join["output"]["joined"]) == ["b1", "b2"]

    def test_join_quorum_mode(self, env):
        spec = {"trigger": {"type": "manual"}, "variables": {},
                "nodes": [{"id": "start", "type": "trigger"},
                          {"id": "par", "type": "parallel"},
                          {"id": "b1", "type": "transform",
                           "config": {"map": {"a": 1}}},
                          {"id": "b2", "type": "transform",
                           "config": {"map": {"b": 2}}},
                          {"id": "j", "type": "join",
                           "config": {"mode": "quorum", "quorum": 1}},
                          {"id": "end", "type": "end"}],
                "edges": [{"from": "start", "to": "par"},
                          {"from": "par", "to": "b1"},
                          {"from": "par", "to": "b2"},
                          {"from": "b1", "to": "j"},
                          {"from": "b2", "to": "j"},
                          {"from": "j", "to": "end"}]}
        did = _publish(env, "法定人数链", spec)
        out = env["service"].start_run(did, inputs={}, actor="admin")
        assert out["run"]["status"] == "succeeded"

    def test_lint_rejects_bad_join_mode(self, env):
        spec = {"trigger": {"type": "manual"}, "variables": {},
                "nodes": [{"id": "start", "type": "trigger"},
                          {"id": "j", "type": "join",
                           "config": {"mode": "whatever"}},
                          {"id": "end", "type": "end"}],
                "edges": [{"from": "start", "to": "j"},
                          {"from": "j", "to": "end"}]}
        d = env["service"].create_draft(name="坏汇合", spec=spec,
                                        actor="admin")
        rep = env["service"].lint(d["definition_id"])["lint_report"]
        assert any(i["code"] == "join_mode" for i in rep)


class TestAgentNodeAndHash:
    def test_agent_node_calls_specified_agent(self, env):
        spec = {"trigger": {"type": "manual"}, "variables": {},
                "nodes": [{"id": "start", "type": "trigger"},
                          {"id": "a", "type": "agent",
                           "config": {"agent_id": "analytics_agent",
                                      "prompt": "列出指标"}},
                          {"id": "end", "type": "end"}],
                "edges": [{"from": "start", "to": "a"},
                          {"from": "a", "to": "end"}]}
        did = _publish(env, "指定Agent链", spec)
        out = env["service"].start_run(did, inputs={}, actor="admin")
        assert out["run"]["status"] == "succeeded"
        nodes = env["store"].list_node_executions(out["run"]["run_id"])
        a = next(n for n in nodes if n["node_id"] == "a")
        assert a["output"]["agent_id"] == "analytics_agent"
        assert a["output"].get("tool_trace"), (
            "agent 节点必须走真实工具循环")

    def test_ui_coords_do_not_change_hash(self, env):
        spec1 = {"trigger": {"type": "manual"}, "variables": {},
                 "nodes": [{"id": "start", "type": "trigger",
                            "ui": {"x": 10, "y": 20}},
                           {"id": "end", "type": "end",
                            "ui": {"x": 200, "y": 20}}],
                 "edges": [{"from": "start", "to": "end"}]}
        d = env["service"].create_draft(name="UI链", spec=spec1,
                                        actor="admin")
        h1 = d["spec_hash"]
        spec2 = {"trigger": {"type": "manual"}, "variables": {},
                 "nodes": [{"id": "start", "type": "trigger",
                            "ui": {"x": 999, "y": 5}},
                           {"id": "end", "type": "end",
                            "ui": {"x": 1, "y": 1}}],
                 "edges": [{"from": "start", "to": "end"}]}
        d2 = env["service"].update_draft(d["definition_id"], spec=spec2,
                                         actor="admin")
        assert d2["spec_hash"] == h1, "UI 坐标不得参与定义 hash"
        # 业务变更必须改变 hash
        spec3 = dict(spec2)
        spec3 = {"trigger": {"type": "manual"}, "variables": {},
                 "nodes": [{"id": "start", "type": "trigger"},
                           {"id": "t", "type": "transform",
                            "config": {"map": {"x": 1}},
                            "ui": {"x": 1, "y": 1}},
                           {"id": "end", "type": "end"}],
                 "edges": [{"from": "start", "to": "t"},
                           {"from": "t", "to": "end"}]}
        d3 = env["service"].update_draft(d["definition_id"], spec=spec3,
                                         actor="admin")
        assert d3["spec_hash"] != h1

    def test_node_library_exposes_canvas_palette(self, env):
        lib = env["service"].node_library()
        need = {"trigger", "condition", "transform", "loop", "parallel",
                "join", "wait", "human_approval", "agent", "model",
                "command", "subflow", "connector", "end"}
        assert need <= set(lib["node_types"])
