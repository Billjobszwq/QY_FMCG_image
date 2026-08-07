"""N2 Task 2：真实控制 API（首批：cycles 控制面）。

- 读端点公开；写端点 session+CSRF；幂等键防重复；参数白名单。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    from src.composition.build import (build_production_bundle,
                                     build_training_control_router)
    from src.platform.api.app import create_app

    monkeypatch.setenv("PLATFORM_USERS", "admin:pw-admin:admin")
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=None, monitor_adapter=None,
        label_studio_adapter=None, probe=lambda spec: None)
    app = create_app(services=(), probe=lambda spec: None, bundle=bundle,
                     web_dist=tmp_path / "none",
                     training_control_router=build_training_control_router(
                         bundle))
    return TestClient(app), bundle


def _login(client):
    r = client.post("/api/v1/auth/login",
                    json={"username": "admin", "password": "pw-admin"})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def test_create_cycle_requires_session(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/training/cycles", json={"name": "c1"})
    assert r.status_code == 401


def test_cycle_lifecycle_via_api(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    h = _login(c)
    r = c.post("/api/v1/training/cycles", json={"name": "c1"}, headers=h)
    assert r.status_code == 200, r.text
    cid = r.json()["cycle_id"]
    # 读端点公开
    d = c.get(f"/api/v1/training/cycles/{cid}").json()
    assert d["status"] == "DRAFT" and d["version"] == 1
    # 推进（幂等键）
    r2 = c.post(f"/api/v1/training/cycles/{cid}/advance",
                json={"target": "BASELINE_VERIFIED",
                      "expected_version": 1, "idempotency_key": "adv-1"},
                headers=h)
    assert r2.status_code == 200
    r3 = c.post(f"/api/v1/training/cycles/{cid}/advance",
                json={"target": "BASELINE_VERIFIED",
                      "expected_version": 1, "idempotency_key": "adv-1"},
                headers=h)
    assert r3.status_code == 200 and r3.json()["duplicate"] is True
    d2 = c.get(f"/api/v1/training/cycles/{cid}").json()
    assert d2["status"] == "BASELINE_VERIFIED" and d2["version"] == 2
    # 事件可回放
    evs = c.get(f"/api/v1/training/cycles/{cid}/events").json()
    assert evs["count"] >= 2


def test_invalid_target_rejected(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    h = _login(c)
    cid = c.post("/api/v1/training/cycles", json={"name": "c2"},
                 headers=h).json()["cycle_id"]
    r = c.post(f"/api/v1/training/cycles/{cid}/advance",
               json={"target": "TRAINING_RUNNING", "expected_version": 1,
                     "idempotency_key": "k"}, headers=h)
    assert r.status_code == 409
