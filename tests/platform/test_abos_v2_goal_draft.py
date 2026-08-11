"""ABOSV2-P0-002 红测试：快速目标服务端持久化并进入主管。

现场复现：首页输入目标点“交给主管”只导航 `/home?focus=chat`，
输入内容丢失（不进主管、不落服务端、刷新不可恢复）。

要求（v2 审计 P0-002 / 04-UI-UX §3）：
1. 目标先落服务端 goal_draft（不得只存 URL/React/localStorage）；
2. 打开主管可见同一文本；确认后形成计划/命令（supervisor 响应留痕）；
3. 刷新可恢复：open 状态 goal 可通过 GET 拉回；
4. 写操作需登录 + CSRF；空文本 fail-closed。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import build_production_bundle
from src.platform.api.app import create_app
from src.platform.api.health import ServiceSpec, ServiceStatus


def _fake_probe(spec: ServiceSpec) -> ServiceStatus:
    return ServiceStatus(name=spec.name, status="healthy", latency_ms=1,
                         detail="fake")


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "v2-admin-pw")
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        probe=_fake_probe)
    app = create_app(services=(), probe=_fake_probe, bundle=bundle,
                     web_dist=tmp_path / "none")
    c = TestClient(app)
    r = c.post("/api/v1/auth/login",
               json={"username": "admin", "password": "v2-admin-pw"})
    csrf = r.json()["csrf_token"]
    return c, {"X-CSRF-Token": csrf}


class TestGoalDraft:
    def test_create_requires_auth_and_csrf(self, client):
        c, h = client
        anon = TestClient(c.app)
        assert anon.post("/api/v1/goals",
                         json={"text": "打开识别任务"}).status_code == 401
        assert c.post("/api/v1/goals",
                      json={"text": "打开识别任务"}).status_code == 403

    def test_create_and_recover_after_refresh(self, client):
        c, h = client
        r = c.post("/api/v1/goals", json={"text": "用生产模型识别这批照片"},
                   headers=h)
        assert r.status_code == 200, r.text
        goal = r.json()["goal"]
        assert goal["status"] == "open"
        assert goal["text"] == "用生产模型识别这批照片"
        # 刷新恢复：open goal 可拉回（含原文本）
        lst = c.get("/api/v1/goals?status=open").json()
        assert lst["count"] == 1
        assert lst["goals"][0]["goal_id"] == goal["goal_id"]

    def test_empty_text_rejected(self, client):
        c, h = client
        r = c.post("/api/v1/goals", json={"text": "   "}, headers=h)
        assert r.status_code == 422

    def test_confirm_forms_plan_and_is_recoverable(self, client):
        c, h = client
        goal = c.post("/api/v1/goals", json={"text": "发起识别任务"},
                      headers=h).json()["goal"]
        r = c.post(f"/api/v1/goals/{goal['goal_id']}/confirm", headers=h)
        assert r.status_code == 200, r.text
        confirmed = r.json()["goal"]
        assert confirmed["status"] == "confirmed"
        result = confirmed["result"]
        assert result.get("message"), "确认后必须形成计划/回答"
        assert result.get("trace_id"), "确认留痕必须有 trace_id"
        # 确认后不再出现在 open 列表（主管不会重复索取）
        lst = c.get("/api/v1/goals?status=open").json()
        assert lst["count"] == 0

    def test_confirm_unknown_goal_404(self, client):
        c, h = client
        r = c.post("/api/v1/goals/nope/confirm", headers=h)
        assert r.status_code == 404
