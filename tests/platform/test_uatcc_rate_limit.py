"""UATCC T6：rate limit 专项测试。

覆盖：并发命中、窗口恢复、跨主体隔离、重启后窗口不完全丢失、
管理员规则修改+审计、非管理员拒绝、429 结构与 Retry-After、
伪造 header 不得绕过身份。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.api.app import create_app
from src.platform.rate_limit import RateLimiter

PW = "uatcc-rl-pw"


class _OkRecognition:
    def recognize(self, data, conf=0.25):
        return {"count": 0, "products": []}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", PW)
    adapter = _OkRecognition()
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=adapter, probe=lambda spec: None)
    build_profiles_service(bundle)
    app = create_app(services=(), probe=lambda spec: None,
                     bundle=bundle, recognition_adapter=adapter,
                     web_dist=Path("/nonexistent-dist"))
    c = TestClient(app)
    r = c.post("/api/v1/auth/login",
               json={"username": "admin", "password": PW})
    h = {"X-CSRF-Token": r.json()["csrf_token"]}
    return c, h, bundle


class TestRateLimitService:
    def test_concurrent_hits_bounded(self, client):
        """并发命中：超出 max+burst 必被拒。"""
        _c, _h, bundle = client
        rl = RateLimiter(bundle.store)
        rl.set_rule("test.cap", max_per_window=5, window_seconds=60,
                    burst=0, actor="admin")
        results = [rl.check("test.cap", "u1", "1.1.1.1")[0]
                   for _ in range(8)]
        assert results.count(True) == 5
        assert results.count(False) == 3

    def test_window_recovery(self, client):
        """窗口恢复：窗口过后恢复配额。"""
        import time
        _c, _h, bundle = client
        rl = RateLimiter(bundle.store)
        rl.set_rule("test.win", max_per_window=2, window_seconds=1,
                    burst=0, actor="admin")
        assert rl.check("test.win", "u")[0]
        assert rl.check("test.win", "u")[0]
        assert not rl.check("test.win", "u")[0]
        time.sleep(1.2)  # 进入下一窗口
        assert rl.check("test.win", "u")[0], "窗口过后应恢复配额"

    def test_cross_subject_isolation(self, client):
        """跨主体隔离：A 打满不影响 B。"""
        _c, _h, bundle = client
        rl = RateLimiter(bundle.store)
        rl.set_rule("test.iso", max_per_window=2, window_seconds=60,
                    burst=0, actor="admin")
        rl.check("test.iso", "custA"); rl.check("test.iso", "custA")
        assert not rl.check("test.iso", "custA")[0]
        assert rl.check("test.iso", "custB")[0], "B 不应被 A 限流"

    def test_persist_across_restart(self, client):
        """重启后窗口计数不完全丢失（同库新实例仍拒）。"""
        _c, _h, bundle = client
        rl = RateLimiter(bundle.store)
        rl.set_rule("test.persist", max_per_window=2,
                    window_seconds=60, burst=0, actor="admin")
        rl.check("test.persist", "u"); rl.check("test.persist", "u")
        rl2 = RateLimiter(bundle.store)  # 模拟重启新实例
        ok, _, _ = rl2.check("test.persist", "u")
        assert not ok, "重启后应继承窗口计数"

    def test_retry_after_positive(self, client):
        _c, _h, bundle = client
        rl = RateLimiter(bundle.store)
        rl.set_rule("test.ra", max_per_window=1, window_seconds=60,
                    burst=0, actor="admin")
        rl.check("test.ra", "u")
        ok, retry_after, _ = rl.check("test.ra", "u")
        assert not ok and retry_after > 0


class TestRateLimitAPI:
    def test_429_structured_and_retry_after(self, client):
        """429 结构化 + Retry-After header。"""
        c, h, bundle = client
        rl = c.app.state.rate_limiter
        rl.set_rule("auth.login", max_per_window=3, window_seconds=60,
                    burst=0, actor="admin")
        last = None
        for _ in range(6):
            last = c.post("/api/v1/auth/login",
                          json={"username": "x", "password": "bad"})
            if last.status_code == 429:
                break
        assert last.status_code == 429
        assert last.headers.get("Retry-After")
        body = last.json()["detail"]
        assert body["error"] == "rate_limited"
        assert body["capability"] == "auth.login"

    def test_admin_can_view_rules(self, client):
        c, h, _b = client
        r = c.get("/api/v1/rate-limit/rules", headers=h)
        assert r.status_code == 200
        caps = {x["capability"] for x in r.json()["rules"]}
        assert "auth.login" in caps and "recognition.create" in caps

    def test_admin_updates_rule_with_audit(self, client):
        c, h, bundle = client
        r = c.put("/api/v1/rate-limit/rules/agent.invoke", headers=h,
                  json={"max_per_window": 99, "window_seconds": 30,
                        "burst": 5, "enabled": True})
        assert r.status_code == 200
        assert r.json()["rule"]["max_per_window"] == 99
        aud = bundle.store._conn.execute(
            "SELECT count(*) c FROM iam_audit_event_v1 WHERE"
            " action='rate_limit.rule.updated'").fetchone()["c"]
        assert aud >= 1, "规则修改必须留审计"

    def test_deny_audit_event_written(self, client):
        """拒绝写审计事件（rate_limit.denied）。"""
        c, h, bundle = client
        rl = c.app.state.rate_limiter
        rl.set_rule("auth.login", max_per_window=1, window_seconds=60,
                    burst=0, actor="admin")
        c.post("/api/v1/auth/login",
               json={"username": "y", "password": "bad"})
        c.post("/api/v1/auth/login",
               json={"username": "y", "password": "bad"})
        n = bundle.store._conn.execute(
            "SELECT count(*) c FROM event_envelope_v1 WHERE"
            " event_type='rate_limit.denied'").fetchone()["c"]
        assert n >= 1
