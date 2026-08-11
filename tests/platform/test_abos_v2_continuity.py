"""ABOSV2-P1-007 跨层连续性测试（非源码字符串断言）。

真实走一条跨层链并逐环对账 ID：
  快速目标(goal_draft) → Supervisor 计划/命令预览(trace)
  → Agent 会话 chat（命令落 agent_command_v1）
  → 人工批准 → 组合根执行钩子 → 识别任务(recognition_task, source=agent)
  → 任务详情 API（contract.trace/profile/tier 一致）
  → current workitems 投影不被旧族污染。

附加最小 UI 契约守卫（防止回退）：主管 1024 默认收起阈值、档位
诚实禁用、快速目标先落服务端。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service,
                                   build_training_router)
from src.platform.api.app import create_app
from src.platform.api.health import ServiceSpec, ServiceStatus
from src.platform.api.recognition_tasks import run_recognition_batch

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web" / "src"


def _fake_probe(spec: ServiceSpec) -> ServiceStatus:
    return ServiceStatus(name=spec.name, status="healthy", latency_ms=1,
                         detail="fake")


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    from tests.platform.test_m5_training_gov import (
        FakeLS, FakeMonitor, FakeRecognition)

    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "v2-admin-pw")
    fake_rec = FakeRecognition()
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=fake_rec, monitor_adapter=FakeMonitor(),
        label_studio_adapter=FakeLS(), probe=_fake_probe)
    profiles_service = build_profiles_service(bundle)

    # 组合根执行钩子（测试装配：与生产同构，adapter 换成 fake）
    def on_approved(row: dict):
        if row.get("kind") != "vision.recognition.create":
            return None
        params = json.loads(row.get("params_json") or "{}")
        out = run_recognition_batch(
            fake_rec, [("continuity.jpg", b"\xff\xd8fake")],
            conf=float(params.get("conf", 0.25)), store=bundle.store,
            entry="agent", actor="agent:supervisor",
            idempotency_key=params.get("idempotency_key"),
            recognition_profile_id=params.get(
                "recognition_profile_id", "production_legacy"),
            service_tier=params.get("service_tier", "standard"),
            source="agent", profiles_service=profiles_service)
        return {"status": "created",
                "task_id": out["task"]["task_id"],
                "trace_id": out.get("trace_id")}

    app = create_app(services=(), probe=_fake_probe, bundle=bundle,
                     recognition_adapter=fake_rec,
                     training_router=build_training_router(bundle),
                     profiles_service=profiles_service,
                     agent_on_approved=on_approved,
                     web_dist=tmp_path / "none")
    c = TestClient(app)
    r = c.post("/api/v1/auth/login",
               json={"username": "admin", "password": "v2-admin-pw"})
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}, bundle


class TestCrossLayerContinuity:
    def test_goal_to_command_to_recognition_to_detail(self, client):
        c, h, _ = client
        # 1) 快速目标落服务端并确认 → 形成计划/命令预览
        goal = c.post("/api/v1/goals", json={"text": "发起识别任务"},
                      headers=h).json()["goal"]
        confirmed = c.post(f"/api/v1/goals/{goal['goal_id']}/confirm",
                           headers=h).json()["goal"]
        assert confirmed["status"] == "confirmed"
        previews = confirmed["result"]["command_previews"]
        assert previews and previews[0]["kind"] == "vision.recognition.create"

        # 2) 主管会话：命令预览落库（可批准对象，非回执）
        sid = c.post("/api/agent/v1/sessions", json={"title": "workbench"},
                     headers=h).json()["session_id"]
        resp = c.post("/api/agent/v1/chat",
                      json={"session_id": sid, "text": "发起识别任务"},
                      headers=h).json()
        cmd = resp["command_previews"][0]

        # 3) 人工批准 → 组合根钩子真实创建识别任务（source=agent）
        appr = c.post(f"/api/agent/v1/commands/{cmd['command_id']}/approve",
                      headers=h).json()
        assert appr["status"] == "approved"
        execd = appr["execution"]
        assert execd["status"] == "created"
        task_id, trace_id = execd["task_id"], execd["trace_id"]

        # 4) 任务详情 API：trace/profile/tier/source 全链一致
        d = c.get(f"/api/v1/recognition/tasks/{task_id}").json()
        assert d["contract"]["trace_id"] == trace_id
        assert d["contract"]["source"] == "agent"
        assert d["contract"]["recognition_profile_id"] == "production_legacy"
        assert d["task"]["status"] == "completed"

        # 5) 重复批准幂等保护（状态机，不二次执行）
        again = c.post(f"/api/agent/v1/commands/{cmd['command_id']}/approve",
                       headers=h)
        assert again.status_code == 409

        # 6) current 投影不含被取代族；本链不产生假待办
        w = c.get("/api/v1/workitems").json()
        assert all(not it.get("superseded") for it in w["items"])
        assert w["summary"]["pending_review"] == 0

    def test_reject_is_audited_and_not_executed(self, client):
        c, h, bundle = client
        sid = c.post("/api/agent/v1/sessions", json={"title": "workbench"},
                     headers=h).json()["session_id"]
        cmd = c.post("/api/agent/v1/chat",
                     json={"session_id": sid, "text": "发起识别任务"},
                     headers=h).json()["command_previews"][0]
        r = c.post(f"/api/agent/v1/commands/{cmd['command_id']}/reject",
                   headers=h)
        assert r.status_code == 200 and r.json()["status"] == "rejected"
        n = bundle.store.count_recognition_tasks()
        assert n == 0, "拒绝的命令不得产生识别任务"


class TestUIContractGuards:
    def test_supervisor_default_closed_below_1440(self):
        src = (WEB / "platform" / "SupervisorWorkspace.tsx").read_text(
            encoding="utf-8")
        assert "window.innerWidth >= 1440" in src, (
            "ABOSV2-P1-006：1024–1439 主管必须默认收起，不得遮挡主内容")

    def test_service_tiers_honestly_disabled(self):
        src = (WEB / "pages" / "Vision.tsx").read_text(encoding="utf-8")
        for tier in ("fast", "high", "extreme"):
            assert f'value="{tier}" disabled' in src, (
                f"ABOSV2-P0-004：档位 {tier} 未真实路由前必须禁用")

    def test_quick_goal_persisted_server_side(self):
        src = (WEB / "pages" / "Home.tsx").read_text(encoding="utf-8")
        assert "createGoal(" in src, (
            "ABOSV2-P0-002：快速目标必须先落服务端 goal_draft")
        assert 'navigate("/home?focus=chat")' not in src, (
            "不得只导航不保存目标文本")
