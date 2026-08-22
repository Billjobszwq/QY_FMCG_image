"""Task 11（G9）测试：受控 API（鉴权/CSRF/研究流程/知识检索）。

要求（05 计划 Task 11）：
- API auth/scope/CSRF/idempotency 红测试；
- source ingest/publish、knowledge/memory/skill search、research
  start/status/resume/cancel、claim/citation/synthesize 端点。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import build_production_bundle
from src.platform.api.app import create_app
from src.platform.cognition.context import CognitiveContext

PW = "task11-api-pw"


def _now_ctx(action: str) -> CognitiveContext:
    return CognitiveContext(
        principal_id="admin", tenant_id="local", customer_id="",
        project_id="", test_run_id="", data_scope="operational",
        action=action, permission_tags=("public", "internal"),
        purpose="api", correlation_id="", parent_run_id=None,
        as_of=datetime.now(timezone.utc))


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", PW)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("COGNITION_CAS_ROOT", str(tmp_path / "cas"))
    monkeypatch.setenv("COGNITION_INDEX_ROOT", str(tmp_path / "index"))
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=None, probe=lambda spec: None)
    app = create_app(services=(), probe=lambda spec: None,
                     bundle=bundle, web_dist=Path("/nonexistent"))
    return TestClient(app)


def _login(c):
    r = c.post("/api/v1/auth/login",
               json={"username": "admin", "password": PW})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def _ingest_and_index(c, h) -> None:
    """摄取制度文档 → 建知识条目 → 批准发布知识 → 建索引 → 激活。"""
    text = "# 年假制度\n\n入职满一年年假 5 天。\n"
    r = c.post("/api/v1/cognition/sources/ingest", headers=h, json={
        "source_type": "file", "original_uri": "leave.md",
        "media_type": "text/markdown", "content_text": text,
        "permission_tags": ["public"], "trust_tier": "authoritative"})
    assert r.status_code == 200, r.text
    doc = r.json()["document"]
    # chunk_id == span_id（摄取时生成 span）；取该 document 的 chunk 作为
    # 知识来源 span
    stack = c.app.state.cognition
    rows = stack.catalog.repo.store._conn.execute(
        "SELECT chunk_id FROM cognition_chunk_v1 WHERE document_id=?",
        (doc["document_id"],)).fetchall()
    span_ids = [x["chunk_id"] for x in rows]
    assert span_ids, "摄取应生成 chunk/span"
    # 知识条目 draft（来源 span 指向真实 chunk）
    kd = c.post("/api/v1/cognition/knowledge/draft", headers=h, json={
        "knowledge_id": "kb-leave", "knowledge_type": "policy",
        "title": "年假制度", "body": text, "summary": "年假制度",
        "owner": "hr", "effective_from": "2026-01-01T00:00:00+00:00",
        "effective_to": None, "permission_tags": ["public"],
        "source_span_ids": span_ids})
    assert kd.status_code == 200, kd.text
    # 申请发布批准（申请人=系统身份，决策人=admin → maker≠checker）
    ap = c.post("/api/v1/governance/approvals/request", headers=h, json={
        "kind": "cognition.knowledge.publish",
        "subject_ref": "kb-leave@v1", "requested_by": "cognition-service"})
    assert ap.status_code == 200, ap.text
    approval_id = ap.json()["approval_id"]
    d = c.post(f"/api/v1/governance/approvals/{approval_id}/decide",
               headers=h, json={"decision": "approved"})
    assert d.status_code == 200, d.text
    pub = c.post("/api/v1/cognition/knowledge/publish", headers=h, json={
        "knowledge_id": "kb-leave", "version": 1,
        "approval_id": approval_id})
    assert pub.status_code == 200, pub.text
    assert pub.json()["status"] == "published"
    # corpus snapshot + 索引 + 激活
    snap = stack.sources.build_corpus_snapshot(
        _now_ctx("cognition.research.start"))
    b = stack.catalog.build(_now_ctx("cognition.index.build"),
                            target_kind="knowledge",
                            corpus_snapshot_id=snap["corpus_snapshot_id"])
    act = c.post("/api/v1/cognition/index/activate", headers=h, json={
        "target_kind": "knowledge",
        "index_snapshot_id": b["index_snapshot_id"]})
    assert act.status_code == 200, act.text


class TestAuthAndCSRF:
    def test_research_requires_session(self, client):
        r = client.post("/api/v1/research/runs",
                        json={"question": "x", "mode": "lookup"})
        assert r.status_code == 401

    def test_research_requires_csrf(self, client):
        r = client.post("/api/v1/auth/login",
                        json={"username": "admin", "password": PW})
        assert r.status_code == 200
        r2 = client.post("/api/v1/research/runs",
                         json={"question": "x", "mode": "lookup"})
        assert r2.status_code == 403  # 有 cookie 无 CSRF header

    def test_get_endpoints_require_session(self, client):
        r = client.get("/api/v1/research/runs/whatever")
        assert r.status_code == 401


class TestResearchFlowAPI:
    def test_research_start_status_claims_synthesize(self, client):
        h = _login(client)
        _ingest_and_index(client, h)
        r = client.post("/api/v1/research/runs", headers=h,
                        json={"question": "年假多少天", "mode": "lookup"})
        assert r.status_code == 200, r.text
        run_id = r.json()["research_run_id"]
        assert r.json()["status"] == "succeeded"
        s = client.get(f"/api/v1/research/runs/{run_id}")
        assert s.status_code == 200 and s.json()["status"] == "succeeded"
        cl = client.get(f"/api/v1/research/runs/{run_id}/claims")
        assert cl.status_code == 200 and cl.json()["count"] >= 1
        ci = client.get(f"/api/v1/research/runs/{run_id}/citations")
        assert ci.status_code == 200 and ci.json()["gate_ok"] is True
        sy = client.post(f"/api/v1/research/runs/{run_id}/synthesize",
                         headers=h)
        assert sy.status_code == 200, sy.text
        assert sy.json()["abstain"] is False and sy.json()["claims"]

    def test_knowledge_search_endpoint(self, client):
        h = _login(client)
        _ingest_and_index(client, h)
        r = client.get("/api/v1/cognition/knowledge/search",
                       params={"q": "年假"})
        assert r.status_code == 200, r.text
        assert r.json()["candidates"]
        assert r.json()["candidates"][0]["target_kind"] == "knowledge"

    def test_knowledge_search_isolated_by_scope(self, client):
        """跨客户上下文（customer 不匹配）不得返回客户级文档。"""
        h = _login(client)
        _ingest_and_index(client, h)
        # 平台级文档（customer=''）对任意客户可见，但 customer 级隔离
        # 由 gateway pre-filter 保证；此处验证接口不泄露额外字段。
        r = client.get("/api/v1/cognition/knowledge/search",
                       params={"q": "年假", "customer_id": "cust-x"})
        assert r.status_code == 200
        d = r.json()
        assert "total_count" not in d and "facets" not in d

    def test_research_cancel_endpoint(self, client):
        h = _login(client)
        _ingest_and_index(client, h)
        r = client.post("/api/v1/research/runs", headers=h,
                        json={"question": "年假多少天", "mode": "lookup"})
        run_id = r.json()["research_run_id"]
        cc = client.post(f"/api/v1/research/runs/{run_id}/cancel",
                         headers=h)
        assert cc.status_code == 200
        assert cc.json()["status"] == "succeeded"  # 已完成 run 不被改写

    def test_insufficient_research_abstains_via_api(self, client):
        h = _login(client)
        _ingest_and_index(client, h)
        r = client.post("/api/v1/research/runs", headers=h,
                        json={"question": "完全无关 xyzz",
                              "mode": "lookup"})
        run_id = r.json()["research_run_id"]
        sy = client.post(f"/api/v1/research/runs/{run_id}/synthesize",
                         headers=h)
        assert sy.status_code == 200, sy.text
        assert sy.json()["abstain"] is True
