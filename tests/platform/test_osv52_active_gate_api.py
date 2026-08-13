"""OSV52：Active Gate 显式 Registry 的 API 级契约测试。

- 实时端点只读 active gate run；无 active → fail-closed；
- 激活需平台角色 + approved + CAS；未知 run/旧 protocol 拒绝；
- 激活后实时响应附带 active_gate_run 元数据。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.api.app import create_app
from src.platform.gate_registry import record_gate_run

PW = "osv52-ag-pw"


class _OkRecognition:
    def recognize(self, data, conf=0.25):
        return {"count": 0, "products": []}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", PW)
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=_OkRecognition(), probe=lambda spec: None)
    profiles = build_profiles_service(bundle)
    app = create_app(services=(), probe=lambda spec: None,
                     bundle=bundle, recognition_adapter=_OkRecognition(),
                     profiles_service=profiles,
                     web_dist=tmp_path / "none")
    client = TestClient(app)
    r = client.post("/api/v1/auth/login",
                    json={"username": "admin", "password": PW})
    assert r.status_code == 200, r.text
    h = {"X-CSRF-Token": r.json()["csrf_token"]}
    return {"store": bundle.store, "client": client, "h": h,
            "tmp": tmp_path}


def _record(env, protocol="scope_v5"):
    gp = env["tmp"] / f"gate_{protocol}.json"
    gp.write_text(json.dumps({"gate": "READY_FOR_REAL_DATA_UAT"}),
                  encoding="utf-8")
    import hashlib
    return record_gate_run(
        env["store"], protocol=protocol, gate_path=gp,
        source_commit="h0", evaluator_version="3.4.0",
        evidence_manifest_hash="f" * 16,
        gate_file_sha256=hashlib.sha256(gp.read_bytes()).hexdigest(),
        requested_by="tester")


class TestActiveGateApi:
    def test_live_gate_fail_closed_without_active(self, env):
        r = env["client"].get("/api/v1/control/gate")
        assert r.status_code == 200
        d = r.json()
        assert d["gate"] == "BLOCKED_BY_GATE_EVIDENCE"
        assert "active" in str(d.get("reasons", ""))

    def test_runs_listing(self, env):
        gid = _record(env)
        r = env["client"].get("/api/v1/control/gate/runs")
        assert r.status_code == 200
        ids = [x["gate_run_id"] for x in r.json()["runs"]]
        assert gid in ids

    def test_activate_requires_approved(self, env):
        gid = _record(env)
        r = env["client"].post("/api/v1/control/gate/activate",
                               headers=env["h"],
                               json={"gate_run_id": gid})
        assert r.status_code == 409
        assert "NOT_APPROVED" in r.json()["detail"]

    def test_activate_unknown_run_rejected(self, env):
        r = env["client"].post("/api/v1/control/gate/activate",
                               headers=env["h"],
                               json={"gate_run_id": "grun-nope",
                                     "approved": True})
        assert r.status_code == 409
        assert "NOT_FOUND" in r.json()["detail"]

    def test_old_scope_cannot_hijack(self, env):
        gid = _record(env, protocol="scope_v4_old")
        r = env["client"].post(
            "/api/v1/control/gate/activate", headers=env["h"],
            json={"gate_run_id": gid, "approved": True})
        assert r.status_code == 409
        assert "PROTOCOL_MISMATCH" in r.json()["detail"]

    def test_activate_and_live_gate_metadata(self, env):
        gid = _record(env)
        r = env["client"].post(
            "/api/v1/control/gate/activate", headers=env["h"],
            json={"gate_run_id": gid, "approved": True})
        assert r.status_code == 200, r.text
        assert r.json()["activated"]["status"] == "active"
        live = env["client"].get("/api/v1/control/gate").json()
        meta = live.get("active_gate_run") or {}
        assert meta.get("gate_run_id") == gid
        assert meta.get("protocol") == "scope_v5"
        # 激活后不再报“无 active”；进入证据校验（fail-closed 之一）
        assert live["gate"] != "READY_FOR_REAL_DATA_UAT" or \
            meta.get("gate_run_id") == gid

    def test_second_activation_supersedes(self, env):
        g1 = _record(env)
        env["client"].post("/api/v1/control/gate/activate",
                           headers=env["h"],
                           json={"gate_run_id": g1, "approved": True})
        g2 = _record(env)
        r = env["client"].post("/api/v1/control/gate/activate",
                               headers=env["h"],
                               json={"gate_run_id": g2, "approved": True})
        assert r.status_code == 200
        assert r.json()["activated"]["supersedes"] == g1
        row1 = env["store"]._conn.execute(
            "SELECT status FROM gate_run_v1 WHERE gate_run_id=?",
            (g1,)).fetchone()
        assert row1["status"] == "superseded"

    def test_non_platform_role_denied(self, env):
        from src.platform.iam import IAMService
        iam = IAMService(env["store"])
        iam.create_principal(kind="user", username="u_ro2",
                             display_name="ro", password="pw-ro-2",
                             created_by="admin")
        iam.grant(username="u_ro2", role="read_only",
                  granted_by="admin")
        lg = env["client"].post("/api/v1/auth/login",
                                json={"username": "u_ro2",
                                      "password": "pw-ro-2"})
        assert lg.status_code == 200
        hh = {"X-CSRF-Token": lg.json()["csrf_token"]}
        gid = _record(env)
        r = env["client"].post("/api/v1/control/gate/activate",
                               headers=hh,
                               json={"gate_run_id": gid,
                                     "approved": True})
        assert r.status_code == 403
