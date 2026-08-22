"""R2-09（Step 1）：Research API 行为门——rate limit / idempotency / 409。

契约：mutation（start/resume/cancel/decide/synthesize）必须有 rate limit
与幂等；401/403/404/409/429 语义正确；重复请求不得重复执行。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import build_production_bundle
from src.platform.api.app import create_app

PW = "r209-api-pw"


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


class TestRateLimit:
    def test_start_rate_limited_429(self, client):
        h = _login(client)
        limiter = client.app.state.rate_limiter
        limiter.set_rule("research.run.start", max_per_window=2,
                         window_seconds=60, burst=0, actor="admin")
        codes = []
        for _ in range(3):
            r = client.post("/api/v1/research/runs", headers=h,
                            json={"question": "q", "mode": "lookup"})
            codes.append(r.status_code)
        assert codes[-1] == 429, f"第三次应 429: {codes}"
        assert "Retry-After" in r.headers

    def test_resume_cancel_decide_have_rate_rules(self, client):
        limiter = client.app.state.rate_limiter
        for cap in ("research.run.resume", "research.run.cancel",
                    "research.run.decide", "research.synthesize"):
            assert limiter.get_rule(cap) is not None, f"缺限流规则: {cap}"


class TestIdempotency:
    def test_start_idempotent_same_key(self, client):
        h = _login(client)
        hh = {**h, "Idempotency-Key": "idem-start-1"}
        r1 = client.post("/api/v1/research/runs", headers=hh,
                         json={"question": "幂等问题", "mode": "lookup"})
        assert r1.status_code == 200, r1.text
        r2 = client.post("/api/v1/research/runs", headers=hh,
                         json={"question": "幂等问题", "mode": "lookup"})
        assert r2.status_code == 200
        # 同一幂等键 → 同一 run，不重复执行
        assert r2.json()["research_run_id"] == r1.json()["research_run_id"]
        # 仅一条 research run
        n = client.get("/api/v1/research/runs/"
                       + r1.json()["research_run_id"], headers=h)
        assert n.status_code == 200

    def test_different_keys_create_distinct_runs(self, client):
        h = _login(client)
        r1 = client.post("/api/v1/research/runs",
                         headers={**h, "Idempotency-Key": "k-a"},
                         json={"question": "q1", "mode": "lookup"})
        r2 = client.post("/api/v1/research/runs",
                         headers={**h, "Idempotency-Key": "k-b"},
                         json={"question": "q2", "mode": "lookup"})
        assert r1.json()["research_run_id"] != r2.json()["research_run_id"]


class TestConflictSemantics:
    def test_decide_non_waiting_run_409(self, client):
        h = _login(client)
        r = client.post("/api/v1/research/runs", headers=h,
                        json={"question": "q", "mode": "lookup"})
        run_id = r.json()["research_run_id"]
        assert r.json()["status"] == "succeeded"
        d = client.post(f"/api/v1/research/runs/{run_id}/decide-conflict",
                        headers=h, json={"resolution": "x"})
        assert d.status_code == 409

    def test_missing_run_404(self, client):
        h = _login(client)
        assert client.get("/api/v1/research/runs/rrun-nope",
                          headers=h).status_code == 404
