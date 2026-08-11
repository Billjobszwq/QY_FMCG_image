"""ABOSV2 Phase C 红测试：Workflow Studio MVP（Gate G3）。

要求（02-WORKFLOW-STUDIO-AND-N8N-DIFY.md）：
1. canonical 定义 + 生命周期 draft→linted→simulated→approved→published
   →deprecated；发布后不可原地修改；发布必须经人工 approve；
2. lint：未知 capability fail-closed、不可达节点、缺 trigger/end；
3. runtime：checkpoint、human_approval 等待节点、失败→死信、cancel；
4. 节点库从已注册 Capability/Gateway 命令动态生成；
5. n8n/Dify adapter 诚实 blocked（许可未确认），不得伪装完成；
6. Workflow Agent 只能生成 draft，发布必须人工批准；
7. 首批照片识别链模板可运行（与 gateway 全链贯通）。
"""
from __future__ import annotations

import base64
from pathlib import Path

import pytest

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.control_plane import CommandGateway
from src.platform.workflow import (NativeWorkflowExecutor,
                                   N8nWorkflowAdapter, DifyWorkflowAdapter,
                                   WorkflowError, WorkflowExecutorBlocked,
                                   WorkflowService)


class _BoomRecognition:
    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.calls = 0

    def recognize(self, data: bytes, conf: float = 0.25):
        from src.platform.adapters.legacy.recognition import (
            RecognitionAdapterError)
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RecognitionAdapterError("unreachable", "识别服务不可达")
        return {"count": 1, "products": [{"name": "SKU-X", "count": 1}]}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "v2-admin-pw")
    adapter = _BoomRecognition()
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=adapter, probe=lambda spec: None)
    profiles = build_profiles_service(bundle)
    gateway = CommandGateway(bundle.store, profiles,
                             recognition_adapter=adapter)
    service = WorkflowService(bundle.store, bundle.capabilities, gateway)
    return {"store": bundle.store, "service": service,
            "gateway": gateway, "adapter": adapter}


IMG = base64.b64encode(b"\xff\xd8fake-jpeg").decode()


def _publish_template(env, name="照片识别链") -> str:
    svc = env["service"]
    d = svc.create_draft(name=name, spec={}, actor="admin",
                         from_template="tpl_recognition_chain_v1")
    did = d["definition_id"]
    svc.lint(did)
    svc.simulate(did, inputs={"images": [["s.jpg", IMG]]}, actor="admin")
    svc.approve(did, actor="admin")
    svc.publish(did, actor="admin")
    return did


class TestLifecycle:
    def test_full_lifecycle_and_immutability(self, env):
        svc = env["service"]
        d = svc.create_draft(name="t1", spec={}, actor="admin",
                             from_template="tpl_recognition_chain_v1")
        did = d["definition_id"]
        assert d["status"] == "draft"
        # 未 lint 不得直接发布（人工批准门）
        with pytest.raises(WorkflowError):
            svc.publish(did, actor="admin")
        linted = svc.lint(did)
        assert linted["status"] == "linted"
        assert linted["lint_report"] == [] or all(
            i["level"] != "error" for i in linted["lint_report"])
        sim = svc.simulate(did, inputs={"images": [["s.jpg", IMG]]},
                           actor="admin")
        assert sim["status"] == "succeeded"
        # 未 approve 不得发布
        with pytest.raises(WorkflowError):
            svc.publish(did, actor="admin")
        svc.approve(did, actor="admin")
        pub = svc.publish(did, actor="admin")
        assert pub["status"] == "published" and pub["published_at"]
        # 发布后不可原地修改；修改必须新版本（draft）
        with pytest.raises(WorkflowError):
            svc.update_draft(did, spec={"nodes": []}, actor="admin")
        v2 = svc.new_version(did, actor="admin")
        assert v2["version"] == 2 and v2["status"] == "draft"
        # deprecated
        dep = svc.deprecate(did, actor="admin")
        assert dep["status"] == "deprecated"

    def test_lint_fail_closed_on_unknown_capability(self, env):
        svc = env["service"]
        spec = {"trigger": {"type": "manual"}, "variables": {},
                "nodes": [{"id": "start", "type": "trigger"},
                          {"id": "bad", "type": "command",
                           "capability": "not.registered.evil"},
                          {"id": "end", "type": "end"}],
                "edges": [{"from": "start", "to": "bad"},
                          {"from": "bad", "to": "end"}],
                "policy": {}}
        d = svc.create_draft(name="bad", spec=spec, actor="admin")
        linted = svc.lint(d["definition_id"])
        codes = {i["code"] for i in linted["lint_report"]}
        assert "capability_missing" in codes
        assert linted["status"] == "draft", "lint 失败不得晋级"
        with pytest.raises(WorkflowError):
            svc.simulate(d["definition_id"], inputs={}, actor="admin")

    def test_lint_detects_unreachable_and_missing_end(self, env):
        svc = env["service"]
        spec = {"trigger": {"type": "manual"}, "variables": {},
                "nodes": [{"id": "start", "type": "trigger"},
                          {"id": "island", "type": "transform",
                           "config": {"map": {"a": "$vars.x"}}}],
                "edges": [], "policy": {}}
        d = svc.create_draft(name="broken", spec=spec, actor="admin")
        linted = svc.lint(d["definition_id"])
        codes = {i["code"] for i in linted["lint_report"]}
        assert "unreachable" in codes and "end_count" in codes


class TestRuntime:
    def test_template_run_full_chain_with_checkpoints(self, env):
        did = _publish_template(env)
        out = env["service"].start_run(
            did, inputs={"images": [["shelf.jpg", IMG]]}, actor="admin")
        run = out["run"]
        assert run["status"] == "succeeded"
        assert run["workflow_definition_id"] == did
        cps = env["store"].list_node_executions(run["run_id"])
        ids = [c["node_id"] for c in cps]
        assert {"start", "recognize", "check", "end"} <= set(ids)
        # 识别子 run 挂在 parent 下（全链贯通）
        rec_node = next(c for c in cps if c["node_id"] == "recognize")
        child_run_id = rec_node["output"]["run_id"]
        child = env["store"].get_business_run(child_run_id)
        assert child["parent_run_id"] == run["run_id"]
        assert child["correlation_id"] == run["correlation_id"]
        assert child["subject_id"], "识别域记录必须回链"
        # 子 run 有真实 usage/证据
        assert env["store"].list_usage_events_v2(run_id=child_run_id)
        assert child["evidence_bundle_id"]
        # 未发布版本不得运行
        v2 = env["service"].new_version(did, actor="admin")
        with pytest.raises(WorkflowError):
            env["service"].start_run(
                did, inputs={"images": [["s.jpg", IMG]]}, actor="admin",
                version=v2["version"])

    def test_failure_routes_to_human_approval_then_recovers(self, env):
        """识别失败 → condition 路由 → human_approval 等待 → 人工批准
        → 同一 run 继续到 end（批准是节点，不是旁路）。"""
        env["adapter"].fail_times = 99
        did = _publish_template(env, name="失败链")
        out = env["service"].start_run(
            did, inputs={"images": [["s.jpg", IMG]]}, actor="admin")
        run = out["run"]
        assert run["status"] == "waiting_human"
        assert out["trace"]["status"] == "waiting_human"
        # 有 approval 工作项
        approvals = env["store"].list_work_items_v2(status="approval")
        assert approvals, "必须生成人工批准 WorkItem"
        # 拒绝路径：另一条 run
        out2 = env["service"].start_run(
            did, inputs={"images": [["s.jpg", IMG]]}, actor="admin")
        denied = env["service"].approve_run(
            out2["run"]["run_id"], actor="admin", decision="denied")
        assert denied["status"] == "cancelled"
        # 批准路径：恢复并完成
        resumed = env["service"].approve_run(
            run["run_id"], actor="admin")
        assert resumed["status"] == "succeeded"
        events = {e["event_type"] for e in env["store"].list_events(
            run_id=run["run_id"])}
        assert "run.waiting_human" in events
        assert "human_approval.decided" in events

    def test_connector_blocked_goes_to_dead_letter(self, env):
        """未许可连接器节点：诚实失败 → 重试耗尽 → 死信 + run failed。"""
        svc = env["service"]
        spec = {"trigger": {"type": "manual"}, "variables": {},
                "nodes": [{"id": "start", "type": "trigger"},
                          {"id": "ext", "type": "connector",
                           "config": {"connector_id": "n8n"},
                           "policy": {"retry": 0}},
                          {"id": "end", "type": "end"}],
                "edges": [{"from": "start", "to": "ext"},
                          {"from": "ext", "to": "end"}],
                "policy": {}}
        d = svc.create_draft(name="conn", spec=spec, actor="admin")
        did = d["definition_id"]
        linted = svc.lint(did)
        assert any(i["code"] == "connector_blocked"
                   for i in linted["lint_report"]), "lint 必须预警 blocked"
        # blocked 只是 warn：允许走完生命周期，但运行诚实失败
        assert linted["status"] == "linted"
        svc.simulate(did, inputs={}, actor="admin")
        svc.approve(did, actor="admin")
        svc.publish(did, actor="admin")
        out = svc.start_run(did, inputs={}, actor="admin")
        assert out["run"]["status"] == "failed"
        dead = env["store"].list_dead_letters(out["run"]["run_id"])
        assert dead and "blocked" in dead[0]["reason"]

    def test_cancel_waiting_run(self, env):
        env["adapter"].fail_times = 99
        did = _publish_template(env, name="取消链")
        out = env["service"].start_run(
            did, inputs={"images": [["s.jpg", IMG]]}, actor="admin")
        cancelled = env["service"].cancel_run(out["run"]["run_id"],
                                              actor="admin")
        assert cancelled["status"] == "cancelled"


class TestNodeLibraryAndAdapters:
    def test_node_library_from_registered_sources(self, env):
        lib = env["service"].node_library()
        for t in ("trigger", "command", "query", "condition", "transform",
                  "agent", "model", "human_approval", "wait", "loop",
                  "parallel", "join", "subflow", "connector", "end"):
            assert t in lib["node_types"]
        caps = {c["capability"] for c in lib["command_nodes"]}
        assert "vision.recognition.create" in caps
        assert lib["connectors"]["n8n"]["available"] is False
        assert lib["connectors"]["dify"]["available"] is False

    def test_external_adapters_honestly_blocked(self):
        for ad in (N8nWorkflowAdapter(), DifyWorkflowAdapter()):
            ok, reason = ad.available()
            assert ok is False and reason
            with pytest.raises(WorkflowExecutorBlocked):
                ad.start({}, {})
            assert ad.collect_usage("x") == []

    def test_native_executor_available_and_wraps_service(self, env):
        ex = NativeWorkflowExecutor(env["service"])
        ok, _ = ex.available()
        assert ok is True
        did = _publish_template(env, name="native 链")
        ref = ex.start({"definition_id": did, "actor": "admin"},
                       {"images": [["s.jpg", IMG]]})
        run_id = ref["run"]["run_id"]
        assert ref["run"]["status"] == "succeeded"
        assert isinstance(ex.collect_evidence(run_id), list)


class TestWorkflowAgent:
    def test_agent_draft_only_and_publish_gate(self, env):
        svc = env["service"]
        out = svc.agent_draft("帮我把这批照片识别一下", actor="admin")
        assert out["requires_human_approval"] is True
        draft = out["draft"]
        assert draft["status"] == "draft"
        nodes = {n["type"] for n in draft["spec"]["nodes"]}
        assert "command" in nodes, "NL 识别意图必须生成识别命令节点"
        # Agent 草稿不得直接发布（必须 lint/simulate/approve）
        with pytest.raises(WorkflowError):
            svc.publish(draft["definition_id"], actor="agent")

    def test_agent_draft_unknown_intent_honest(self, env):
        out = env["service"].agent_draft("随便聊聊", actor="admin")
        assert "骨架" in out["note"]
