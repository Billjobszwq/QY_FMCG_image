"""ABOS T6：Supervisor 统一响应契约 + Agent runtime API。

覆盖：统一契约字段完整、高风险拒绝、UIIntent 白名单、会话持久化、
识别委派命令预览、无 SKU 定位、Path 可用（无 NameError）。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.platform.agents.supervisor import SupervisorAgent, UI_INTENTS
from src.platform.api.agent_runtime_api import create_agent_runtime_router
from src.platform.auth import AuthService, create_auth_router
from src.platform.data.store import PlatformStore

ADMIN_PW = "abos-agent-pw"
CONTRACT_FIELDS = ("message", "evidence_refs", "ui_intents",
                   "command_previews", "tasks", "delegations",
                   "memory_updates", "requires_approval", "trace_id")


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


@pytest.fixture()
def sup(store):
    return SupervisorAgent(store)


def _session(store) -> str:
    store._conn.execute(
        "INSERT INTO agent_session_v1 (session_id, created_by, created_at)"
        " VALUES ('s1','admin','2026-01-01T00:00:00Z')")
    store._conn.commit()
    return "s1"


# ---------------- 统一响应契约 ----------------


def test_response_contract_complete(sup, store):
    sid = _session(store)
    resp = sup.chat(sid, "这里能做什么", actor="admin")
    for f in CONTRACT_FIELDS:
        assert f in resp, f"统一响应缺少字段 {f}"
    assert resp["trace_id"].startswith("tr-")
    assert resp["message"]


def test_no_sku_identity_in_answers(sup, store):
    sid = _session(store)
    for q in ("这里能做什么", "识别任务", "帮助"):
        resp = sup.chat(sid, q, actor="admin")
        assert "SKU 识别系统" not in resp["message"]


def test_high_risk_production_switch_denied(sup, store):
    sid = _session(store)
    resp = sup.chat(sid, "帮我切换生产", actor="admin")
    assert resp["requires_approval"] is True
    assert resp.get("denied") is True
    assert "拒绝" in resp["message"]


def test_recognition_delegation_command_preview(sup, store):
    sid = _session(store)
    resp = sup.chat(sid, "用生产模型识别这批照片", actor="admin")
    assert resp["requires_approval"] is True
    assert resp["command_previews"], "必须有命令预览"
    cp = resp["command_previews"][0]
    assert cp["kind"] == "vision.recognition.create"
    assert cp["params"]["recognition_profile_id"]
    assert cp["idempotency_key"] and cp["rollback"]
    assert any(d["agent_id"] == "recognition_agent"
               for d in resp["delegations"]), "必须有委派回执"


def test_ui_intents_whitelist_only(sup, store):
    sid = _session(store)
    resp = sup.chat(sid, "打开识别任务", actor="admin")
    assert resp["ui_intents"]
    for it in resp["ui_intents"]:
        assert it["kind"] in UI_INTENTS
        assert not any(k in it for k in ("html", "js", "script"))


def test_training_process_query_no_nameerror(sup, store):
    """T1 复现问题：Path 未导入/宽泛异常；现在必须真实返回。"""
    sid = _session(store)
    resp = sup.chat(sid, "micro-gold 新项目 ID", actor="admin")
    assert resp["message"]
    assert "待导入" not in resp["message"] or "未导入" in resp["message"]


def test_session_messages_persisted(sup, store):
    sid = _session(store)
    sup.chat(sid, "识别任务", actor="admin")
    rows = store._conn.execute(
        "SELECT role FROM agent_session_msg_v1 WHERE session_id=?",
        (sid,)).fetchall()
    assert {r["role"] for r in rows} >= {"user", "supervisor"}


def test_llm_unavailable_degrades_honestly(sup, store, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    sid = _session(store)
    resp = sup.chat(sid, "一个完全无关的随意问题 zzzz", actor="admin")
    assert resp["provider"] in ("rules_fallback", "deepseek")
    assert resp["message"]


# ---------------- runtime API ----------------


@pytest.fixture()
def client(store, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", ADMIN_PW)
    auth = AuthService(store)
    app = FastAPI()
    app.include_router(create_auth_router(auth))
    app.include_router(create_agent_runtime_router(store, auth=auth))
    return TestClient(app)


def _login(c):
    r = c.post("/api/v1/auth/login",
               json={"username": "admin", "password": ADMIN_PW})
    return r.json()["csrf_token"]


def test_chat_endpoint_returns_contract(client, store):
    csrf = _login(client)
    sid = client.post("/api/agent/v1/sessions", json={"title": "t"},
                      headers={"X-CSRF-Token": csrf}).json()["session_id"]
    d = client.post("/api/agent/v1/chat",
                    json={"session_id": sid, "text": "识别任务"},
                    headers={"X-CSRF-Token": csrf}).json()
    for f in CONTRACT_FIELDS:
        assert f in d


def test_command_approve_reject_persisted(client, store):
    csrf = _login(client)
    sid = client.post("/api/agent/v1/sessions", json={"title": "t"},
                      headers={"X-CSRF-Token": csrf}).json()["session_id"]
    d = client.post("/api/agent/v1/chat",
                    json={"session_id": sid,
                          "text": "用生产模型识别这批照片"},
                    headers={"X-CSRF-Token": csrf}).json()
    cmd = d["command_previews"][0]["command_id"]
    r = client.post(f"/api/agent/v1/commands/{cmd}/approve",
                    headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    row = store._conn.execute(
        "SELECT status, decided_by FROM agent_command_v1"
        " WHERE command_id=?", (cmd,)).fetchone()
    assert row["status"] == "approved" and row["decided_by"]
    # 重复批准 → 409（幂等保护）
    assert client.post(
        f"/api/agent/v1/commands/{cmd}/approve",
        headers={"X-CSRF-Token": csrf}).status_code == 409
