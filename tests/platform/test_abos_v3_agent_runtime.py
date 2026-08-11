"""ABOSV3 T4 红测试：真实 Agent Runtime（工具循环 + 版本化定义）。

要求（AGENT-EXECUTION-PROMPT §T4）：
- 7 个 Agent 有真实版本化定义与有界 health 探针；
- Supervisor 真实执行 8 个工具意图（不再是统一 ok=true）；
- 每次 invoke 写 Run/Event/Evidence/Usage；
- 写动作生成待批准命令；draft 类动作真实创建对象；
- 定义/资产 draft→发布→回滚完整；Secret 不进 Prompt。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.api.app import create_app
from src.platform.control_plane import CommandGateway

PW = "v3-agent-pw"
SEVEN = ("supervisor", "modelops", "data_steward", "survey_agent",
         "analytics_agent", "fieldops_agent", "finance_agent")


class _OkRecognition:
    def recognize(self, data: bytes, conf: float = 0.25):
        return {"count": 1, "products": [{"name": "SKU-X", "count": 1}]}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", PW)
    adapter = _OkRecognition()
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=adapter, probe=lambda spec: None)
    profiles = build_profiles_service(bundle)
    gateway = CommandGateway(bundle.store, profiles,
                             recognition_adapter=adapter)
    app = create_app(services=(), probe=lambda spec: None,
                     bundle=bundle, recognition_adapter=adapter,
                     web_dist=Path("/nonexistent-dist"))
    c = TestClient(app)
    r = c.post("/api/v1/auth/login",
               json={"username": "admin", "password": PW})
    h = {"X-CSRF-Token": r.json()["csrf_token"]}
    return c, h, bundle, gateway


def invoke(c, h, agent: str, text: str, **kw) -> dict:
    r = c.post(f"/api/v1/agents/{agent}/invoke", headers=h,
               json={"text": text, **kw})
    assert r.status_code == 200, r.text
    return r.json()


class TestDefinitionsAndHealth:
    def test_seven_agents_seeded_published(self, client):
        c, h, _b, _g = client
        d = c.get("/api/v1/agents/definitions").json()
        ids = {x["agent_id"] for x in d["definitions"]}
        assert set(SEVEN) <= ids
        for x in d["definitions"]:
            if x["agent_id"] in SEVEN:
                assert x["status"] == "published"
                assert x["soul"], "soul 必填（长期身份/价值边界）"
                assert x["system_prompt"]
                assert x["tool_allowlist"]

    def test_health_is_bounded_probe(self, client):
        c, h, _b, _g = client
        for aid in SEVEN:
            body = c.get(f"/api/v1/agents/{aid}/health").json()
            assert body["healthy"] is True, (aid, body)
            kinds = {ch["check"] for ch in body["checks"]}
            assert "definition_published" in kinds
            assert "fact_query" in kinds  # 有界事实查询探针
        # 未注册 Agent：不健康（不是 manifest 存在即健康）
        body = c.get("/api/v1/agents/ghost_agent/health").json()
        assert body["healthy"] is False


class TestSupervisorEightIntents:
    def test_eight_real_tool_intents(self, client):
        c, h, bundle, gw = client
        # 造事实：一条识别 run、一个未确认地址、一个客户 usage
        gw.submit(command_kind="vision.recognition.create",
                  params={"images": [["x.jpg", b"\xff\xd8fake"]]},
                  actor="tester", source="api", customer_id="cust-t")
        from src.platform.field_ops import FieldOpsService
        FieldOpsService(bundle.store).add_address(
            customer_id="cust-t", raw="无坐标地址 1 号", actor="admin")

        # 1) 查进度
        r = invoke(c, h, "supervisor", "项目进度做到哪里了？")
        assert any(t["tool"] == "work.progress.query"
                   and t["status"] == "ok" for t in r["tool_trace"])
        # 2) 查最少 SKU（主数据汇总）
        r = invoke(c, h, "supervisor", "哪个客户的 SKU/项目最少？")
        assert any(t["tool"] == "master.skus.summary"
                   for t in r["tool_trace"])
        # 3) 打开问卷
        r = invoke(c, h, "supervisor", "打开问卷列表")
        assert any(t["tool"] == "survey.list" for t in r["tool_trace"])
        assert any(i.get("target") == "/survey/design"
                   for i in r["ui_intents"])
        # 4) 创建工作流 draft（真实落库）
        r = invoke(c, h, "supervisor", "创建一个工作流草稿")
        assert any(t["tool"] == "workflow.draft.create"
                   and t["status"] == "ok" for t in r["tool_trace"])
        assert bundle.store._conn.execute(
            "SELECT count(*) c FROM workflow_definition_v1 WHERE name"
            " LIKE 'Agent 草稿%'").fetchone()["c"] >= 1
        # 5) 查询缺坐标地址
        r = invoke(c, h, "supervisor", "哪些地址还缺坐标？")
        assert any(t["tool"] == "geo.addresses.missing_coords"
                   for t in r["tool_trace"])
        assert "无坐标地址" in r["message"]
        # 6) 调用识别 → 待批准命令（不得直接执行）
        r = invoke(c, h, "supervisor", "发起识别这批照片")
        assert r["requires_approval"] is True
        assert r["command_previews"]
        cid = r["command_previews"][0]["command_id"]
        assert bundle.store._conn.execute(
            "SELECT status FROM agent_command_v1 WHERE command_id=?",
            (cid,)).fetchone()["status"] == "pending_approval"
        # 7) 创建 BI draft（真实落库）
        r = invoke(c, h, "supervisor", "给我建一个 BI 报表草稿",
                   customer_id="cust-t")
        assert any(t["tool"] == "analytics.report.draft"
                   and t["status"] == "ok" for t in r["tool_trace"])
        assert bundle.store._conn.execute(
            "SELECT count(*) c FROM bi_report_spec_v1 WHERE note LIKE"
            " '%人工批准%'").fetchone()["c"] >= 1
        # 8) 查询客户 Usage
        r = invoke(c, h, "supervisor", "这个客户花了多少 Usage？",
                   customer_id="cust-t")
        assert any(t["tool"] == "usage.query" for t in r["tool_trace"])
        assert "recognition_photo" in r["message"]

    def test_every_invoke_writes_run_event_usage(self, client):
        c, h, bundle, _g = client
        before = bundle.store._conn.execute(
            "SELECT count(*) c FROM agent_run_v1").fetchone()["c"]
        invoke(c, h, "supervisor", "项目进度？")
        assert bundle.store._conn.execute(
            "SELECT count(*) c FROM agent_run_v1").fetchone()[
            "c"] == before + 1
        assert bundle.store._conn.execute(
            "SELECT count(*) c FROM event_envelope_v1"
            " WHERE event_type='agent.invoked'").fetchone()["c"] >= 1
        assert bundle.store._conn.execute(
            "SELECT count(*) c FROM usage_event_v2"
            " WHERE unit='agent_call'").fetchone()["c"] >= 1

    def test_domain_agent_allowlist_enforced(self, client):
        c, h, _b, _g = client
        # analytics_agent 的 allowlist 没有 recognition 工具：
        # 即便文本提到识别，也不会执行识别预览
        r = invoke(c, h, "analytics_agent", "发起识别并建报表")
        tools = [t["tool"] for t in r["tool_trace"]]
        assert "recognition.create.preview" not in tools
        assert "analytics.report.draft" in tools


class TestSupervisorChatToolLoop:
    def test_chat_goes_through_tool_loop(self, client):
        """ABOSV3-P0-006：主管对话不再是纯关键词 if/else；
        命中工具意图时走真实工具循环并持久化消息。"""
        c, h, _b, _g = client
        sid = c.post("/api/agent/v1/sessions", headers=h,
                     json={}).json()["session_id"]
        r = c.post("/api/agent/v1/chat", headers=h, json={
            "session_id": sid,
            "text": "项目进度做到哪里了？"}).json()
        assert r.get("tool_trace"), "chat 必须走真实工具循环"
        assert any(t["tool"] == "work.progress.query"
                   for t in r["tool_trace"])
        msgs = c.get(f"/api/agent/v1/sessions/{sid}/messages").json()
        assert msgs["count"] >= 2


class TestLifecycleAssetsMemory:
    def test_definition_draft_publish_rollback(self, client):
        c, h, _b, _g = client
        cur = c.get("/api/v1/agents/definitions/survey_agent").json()[
            "definition"]
        v0 = cur["version"]
        draft = c.post(
            "/api/v1/agents/definitions/survey_agent/draft", headers=h,
            json={"system_prompt": "你是问卷助手（修订版）"}).json()[
            "definition"]
        assert draft["status"] == "draft"
        assert draft["version"] == v0 + 1
        pub = c.post(
            f"/api/v1/agents/definitions/survey_agent/publish",
            headers=h, json={"version": draft["version"]}).json()[
            "definition"]
        assert pub["status"] == "published"
        assert pub["system_prompt"] == "你是问卷助手（修订版）"
        back = c.post(
            "/api/v1/agents/definitions/survey_agent/rollback",
            headers=h).json()["definition"]
        assert back["version"] == v0
        assert back["status"] == "published"

    def test_asset_draft_publish_and_kb_search(self, client):
        c, h, _b, _g = client
        a = c.post("/api/v1/agents/assets", headers=h, json={
            "kind": "kb", "name": "巡检手册",
            "content": "门店巡检必须先拍门头照，再填问卷。"}).json()["asset"]
        assert a["status"] == "draft"
        # draft 状态不得被检索
        r = invoke(c, h, "supervisor", "查知识库：巡检手册")
        assert "巡检手册" not in r["message"]
        p = c.post(f"/api/v1/agents/assets/{a['asset_id']}/publish",
                   headers=h).json()["asset"]
        assert p["status"] == "published"
        r = invoke(c, h, "supervisor", "查知识库：巡检手册")
        assert "巡检手册" in r["message"]
        # skill 资产同样走 draft→发布
        s = c.post("/api/v1/agents/assets", headers=h, json={
            "kind": "skill", "name": "地址核查",
            "content": "步骤：查缺坐标→地理编码→人工确认"}).json()["asset"]
        assert s["status"] == "draft"

    def test_memory_lifecycle(self, client):
        c, h, _b, _g = client
        m = c.post("/api/v1/agents/supervisor/memories", headers=h,
                   json={"content": "客户A偏好月初巡检",
                         "level": "L3"}).json()
        rows = c.get("/api/v1/agents/supervisor/memories").json()
        assert any(x["memory_id"] == m["memory_id"]
                   for x in rows["memories"])
        d = c.delete(f"/api/v1/agents/memories/{m['memory_id']}",
                     headers=h)
        assert d.status_code == 200
        rows = c.get("/api/v1/agents/supervisor/memories").json()
        assert all(x["memory_id"] != m["memory_id"]
                   for x in rows["memories"])
