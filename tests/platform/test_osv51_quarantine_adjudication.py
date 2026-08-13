"""OSV51 C-3 红测试：隔离区人工裁决状态机（API/权限/审计/CAS/双人审批）。

契约 03-QUARANTINE-STATE-MACHINE.md：
- 状态集 quarantined → retained_for_evidence | bound_to_test_run |
  soft_discarded | release_requested → release_approved |
  superseded_by_new_batch；
- release_to_operational 双人审批（审批人≠申请人），创建新批次
  revision（不原地改 quarantine 行）；
- CAS/版本号，重复提交幂等；
- 无权限 403；非 quarantine 409；非法迁移 409；重启不丢状态；
- 每次迁移追加裁决证据 + iam 审计。
"""
from __future__ import annotations

import io
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.api.app import create_app
from src.platform.data.store import PlatformStore
from src.platform.iam import IAMService
from src.platform.test_data import FixtureTestDataService

PW = "osv51-adj-pw"
NS = "uatv7_osv51_adj"
NS2 = "uatv7_osv51_adj_b"
UPW = "osv51-adj-user-pw"


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
    headers = {"X-CSRF-Token": r.json()["csrf_token"]}
    tds = FixtureTestDataService(bundle.store)
    tds.create_test_run_context(NS, customer_ids=[f"{NS}_cust"])
    tds.create_test_run_context(NS2, customer_ids=[f"{NS2}_cust"])
    iam = IAMService(bundle.store)
    # 两个平台审批人 + 一个审计员 + 一个只读
    for u, role in (("u_approve1", "platform_admin"),
                    ("u_approve2", "platform_admin"),
                    ("u_auditor", "auditor"),
                    ("u_ro", "read_only")):
        iam.create_principal(kind="user", username=u, display_name=u,
                             password=UPW, created_by="admin")
        iam.grant(username=u, role=role, granted_by="admin")
    logins = {}
    for u in ("u_approve1", "u_approve2", "u_auditor", "u_ro"):
        rr = client.post("/api/v1/auth/login",
                         json={"username": u, "password": UPW})
        assert rr.status_code == 200, rr.text
        logins[u] = {"X-CSRF-Token": rr.json()["csrf_token"]}
    return {"store": bundle.store, "client": client, "h": headers,
            "iam": iam, "tds": tds, "logins": logins,
            "db_path": tmp_path / "p.sqlite"}


def _cust_csv(*cids):
    rows = "".join(f"{cid},客户{cid},月结30天,,\n" for cid in cids)
    return ("customer_id,name,payment_terms,retention_policy,tags\n"
            + rows).encode("utf-8-sig")


def _mk_quarantined(env, cid_suffix="q1"):
    r = env["client"].post(
        "/api/v1/import/upload", headers=env["h"],
        data={"template_id": "customers_v1"},
        files={"file": ("q.csv", io.BytesIO(
            _cust_csv(f"{NS}_{cid_suffix}")), "text/csv")})
    assert r.status_code == 200, r.text
    bid = r.json()["batch"]["batch_id"]
    env["store"]._conn.execute(
        "UPDATE import_batch_v1 SET data_scope='quarantine',"
        " archived_at='2026-08-13T05:28:36+00:00' WHERE batch_id=?",
        (bid,))
    env["store"]._conn.commit()
    return bid


def _adj(client, h, bid, body):
    return client.post(f"/api/v1/import/batches/{bid}/adjudication",
                       headers=h, json=body)


def _state(client, h, bid):
    r = client.get(f"/api/v1/import/batches/{bid}/adjudication",
                   headers=h)
    assert r.status_code == 200, r.text
    return r.json()["adjudication"]


def _relogin_admin(env):
    r = env["client"].post("/api/v1/auth/login",
                           json={"username": "admin", "password": PW})
    env["h"] = {"X-CSRF-Token": r.json()["csrf_token"]}
    return env["h"]


class TestStateMachineBasics:
    def test_initial_state_quarantined_version0(self, env):
        bid = _mk_quarantined(env)
        a = _state(env["client"], env["h"], bid)
        assert a["state"] == "quarantined"
        assert a["version"] == 0

    def test_retain_and_idempotent_repeat(self, env):
        bid = _mk_quarantined(env)
        r1 = _adj(env["client"], env["h"], bid,
                  {"action": "retain", "reason": "留证"})
        assert r1.status_code == 200, r1.text
        a = _state(env["client"], env["h"], bid)
        assert a["state"] == "retained_for_evidence"
        v = a["version"]
        r2 = _adj(env["client"], env["h"], bid,
                  {"action": "retain", "reason": "留证"})
        assert r2.status_code == 200  # 幂等
        assert _state(env["client"], env["h"], bid)["version"] == v

    def test_soft_discard(self, env):
        bid = _mk_quarantined(env)
        r = _adj(env["client"], env["h"], bid,
                 {"action": "soft_discard", "reason": "无效数据"})
        assert r.status_code == 200, r.text
        assert _state(env["client"], env["h"], bid)["state"] == \
            "soft_discarded"
        # 软作废后仍写冻结
        rc = env["client"].post(
            f"/api/v1/import/batches/{bid}/commit", headers=env["h"])
        assert rc.status_code == 409

    def test_invalid_transition_direct_approve(self, env):
        bid = _mk_quarantined(env)
        r = _adj(env["client"], env["h"], bid,
                 {"action": "approve_release"})
        assert r.status_code == 409
        assert "ADJUDICATION_INVALID_TRANSITION" in r.json()["detail"]

    def test_non_quarantine_batch_rejected(self, env):
        r = env["client"].post(
            "/api/v1/import/upload", headers=env["h"],
            data={"template_id": "customers_v1"},
            files={"file": ("o.csv", io.BytesIO(
                _cust_csv(f"{NS}_op1")), "text/csv")})
        bid = r.json()["batch"]["batch_id"]
        rr = _adj(env["client"], env["h"], bid, {"action": "retain"})
        assert rr.status_code == 409
        assert "ADJUDICATION_NOT_QUARANTINE" in rr.json()["detail"]

    def test_read_only_denied_auditor_allowed(self, env):
        bid = _mk_quarantined(env)
        rr = _adj(env["client"], env["logins"]["u_ro"], bid,
                  {"action": "retain"})
        assert rr.status_code == 403
        ra = _adj(env["client"], env["logins"]["u_auditor"], bid,
                  {"action": "retain"})
        assert ra.status_code == 200, ra.text
        _relogin_admin(env)


class TestDualApprovalRelease:
    def test_release_flow_creates_revision_not_in_place(self, env):
        bid = _mk_quarantined(env, "rel1")
        # admin 申请
        r = _adj(env["client"], env["h"], bid,
                 {"action": "request_release", "reason": "业务确认有效"})
        assert r.status_code == 200, r.text
        a = _state(env["client"], env["h"], bid)
        assert a["state"] == "release_requested"
        assert a["requested_by"] == "admin"
        # 申请人自批 → 409
        rs = _adj(env["client"], env["h"], bid,
                  {"action": "approve_release"})
        assert rs.status_code == 409
        assert "ADJUDICATION_SAME_ACTOR" in rs.json()["detail"]
        # 第二人批准
        h1 = env["logins"]["u_approve1"]
        ra = _adj(env["client"], h1, bid, {"action": "approve_release"})
        assert ra.status_code == 200, ra.text
        a2 = _state(env["client"], h1, bid)
        assert a2["state"] == "release_approved"
        assert a2["approved_by"] == "u_approve1"
        rev = a2["revision_batch_id"]
        assert rev
        # 原行保持 quarantine，未原地改 operational
        row = env["store"]._conn.execute(
            "SELECT data_scope, visibility FROM import_batch_v1"
            " WHERE batch_id=?", (bid,)).fetchone()
        assert row["data_scope"] == "quarantine"
        # revision：operational + supersedes 关联
        rrow = env["store"]._conn.execute(
            "SELECT template_id, data_scope, source, correlation_id,"
            " status FROM import_batch_v1 WHERE batch_id=?",
            (rev,)).fetchone()
        assert rrow["data_scope"] == "operational"
        assert rrow["source"] == "quarantine_release"
        assert rrow["correlation_id"] == bid
        assert rrow["status"] == "uploaded"
        # 原批次仍写冻结；revision 可走完整导入生命周期
        _relogin_admin(env)
        assert env["client"].post(
            f"/api/v1/import/batches/{bid}/commit",
            headers=env["h"]).status_code == 409
        rd = env["client"].post(
            f"/api/v1/import/batches/{rev}/dry-run", headers=env["h"])
        assert rd.status_code == 200, rd.text
        rc = env["client"].post(
            f"/api/v1/import/batches/{rev}/commit", headers=env["h"])
        assert rc.status_code == 200, rc.text
        # revision 提交成功 → 原批次 superseded_by_new_batch
        a3 = _state(env["client"], env["h"], bid)
        assert a3["state"] == "superseded_by_new_batch"

    def test_concurrent_approvals_one_wins(self, env):
        bid = _mk_quarantined(env, "rel2")
        _adj(env["client"], env["h"], bid,
             {"action": "request_release"})
        a = _state(env["client"], env["h"], bid)
        results: list[int] = []
        lock = threading.Lock()

        def approve(u):
            rr = _adj(env["client"], env["logins"][u], bid,
                      {"action": "approve_release",
                       "version": a["version"]})
            with lock:
                results.append(rr.status_code)

        ths = [threading.Thread(target=approve, args=(u,))
               for u in ("u_approve1", "u_approve2")]
        [t.start() for t in ths]
        [t.join() for t in ths]
        assert sorted(results) == [200, 409], results
        _relogin_admin(env)

    def test_reject_release_back_to_quarantined(self, env):
        bid = _mk_quarantined(env, "rel3")
        _adj(env["client"], env["h"], bid,
             {"action": "request_release"})
        rr = _adj(env["client"], env["logins"]["u_approve2"], bid,
                  {"action": "reject_release", "reason": "证据不足"})
        assert rr.status_code == 200, rr.text
        a = _state(env["client"], env["logins"]["u_approve2"], bid)
        assert a["state"] == "quarantined"
        _relogin_admin(env)

    def test_stale_version_conflict(self, env):
        bid = _mk_quarantined(env, "rel4")
        r = _adj(env["client"], env["h"], bid,
                 {"action": "retain", "version": 99})
        assert r.status_code == 409
        assert "ADJUDICATION_VERSION_CONFLICT" in r.json()["detail"]


class TestBindTestRun:
    def test_bind_creates_fixture_revision(self, env):
        bid = _mk_quarantined(env, "bind1")
        r = _adj(env["client"], env["h"], bid,
                 {"action": "bind_test_run", "target_test_run_id": NS})
        assert r.status_code == 200, r.text
        a = _state(env["client"], env["h"], bid)
        assert a["state"] == "bound_to_test_run"
        rev = a["revision_batch_id"]
        rrow = env["store"]._conn.execute(
            "SELECT data_scope, test_run_id FROM import_batch_v1"
            " WHERE batch_id=?", (rev,)).fetchone()
        assert rrow["data_scope"] == "uat_fixture"
        assert rrow["test_run_id"] == NS
        # 客户关联物化（单一关联源）
        sc = env["store"]._conn.execute(
            "SELECT customer_id FROM"
            " import_batch_customer_scope_v1 WHERE batch_id=?",
            (rev,)).fetchall()
        assert [s["customer_id"] for s in sc] == [f"{NS}_cust"]

    def test_bind_unknown_test_run_fail_closed(self, env):
        bid = _mk_quarantined(env, "bind2")
        r = _adj(env["client"], env["h"], bid,
                 {"action": "bind_test_run",
                  "target_test_run_id": "no_such_run"})
        assert r.status_code == 409
        assert "ADJUDICATION_TEST_RUN_NOT_FOUND" in r.json()["detail"]


class TestDurabilityAndAudit:
    def test_restart_keeps_state(self, env):
        bid = _mk_quarantined(env, "dur1")
        _adj(env["client"], env["h"], bid, {"action": "retain"})
        store2 = PlatformStore(env["db_path"])
        row = store2._conn.execute(
            "SELECT state FROM quarantine_adjudication_v1"
            " WHERE batch_id=?", (bid,)).fetchone()
        assert row["state"] == "retained_for_evidence"

    def test_evidence_and_audit_trail(self, env):
        bid = _mk_quarantined(env, "aud1")
        _adj(env["client"], env["h"], bid,
             {"action": "retain", "reason": "r1"})
        _adj(env["client"], env["h"], bid,
             {"action": "request_release", "reason": "r2"})
        conn = env["store"]._conn
        evs = conn.execute(
            "SELECT kind, actor FROM"
            " quarantine_adjudication_evidence_v1 WHERE batch_id=?"
            " ORDER BY id", (bid,)).fetchall()
        assert [e["kind"] for e in evs] == ["retain", "request_release"]
        auds = conn.execute(
            "SELECT action FROM iam_audit_event_v1 WHERE resource=?"
            " ORDER BY audit_id", (f"import:{bid}",)).fetchall()
        actions = [a["action"] for a in auds]
        assert "import.quarantine.retain" in actions
        assert "import.quarantine.request_release" in actions

    def test_read_only_cannot_get_adjudication_mutate(self, env):
        bid = _mk_quarantined(env, "ro1")
        # 只读可见隔离详情（审计视角由权限控制），但裁决动作 403
        rr = _adj(env["client"], env["logins"]["u_ro"], bid,
                  {"action": "soft_discard"})
        assert rr.status_code == 403
        _relogin_admin(env)
