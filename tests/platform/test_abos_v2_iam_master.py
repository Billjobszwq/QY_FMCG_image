"""ABOSV2 Phase D 红测试：IAM 与主数据（Gate G4）。

要求（任务书 §八 / 03-DOMAIN-PACKS-SPEC §1–§2）：
1. 账号开设（user/service_account/agent 独立身份）、内置角色模板、
   permission bundle、tenant/customer/project 作用域、批准矩阵、审计；
2. SKU/客户/项目主数据库：SKU 新旧包装、别名、客户显示名、有效期；
3. 两个本地测试客户证明数据/任务/Usage/Agent 查询相互隔离；
   test fixture 显式标记，不得混入生产数据。
"""
from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.api.app import create_app
from src.platform.api.health import ServiceSpec, ServiceStatus
from src.platform.control_plane import CommandGateway
from src.platform.iam import IAMService, MasterDataService

IMG = base64.b64encode(b"\xff\xd8fake-jpeg").decode()


def _fake_probe(spec: ServiceSpec) -> ServiceStatus:
    return ServiceStatus(name=spec.name, status="healthy", latency_ms=1,
                         detail="fake")


class _FakeRec:
    def recognize(self, data: bytes, conf: float = 0.25):
        return {"count": 1, "products": [{"name": "SKU-X", "count": 1}]}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "v2-admin-pw")
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=_FakeRec(), probe=_fake_probe)
    profiles = build_profiles_service(bundle)
    gateway = CommandGateway(bundle.store, profiles,
                             recognition_adapter=_FakeRec())
    app = create_app(services=(), probe=_fake_probe, bundle=bundle,
                     recognition_adapter=_FakeRec(),
                     profiles_service=profiles,
                     web_dist=tmp_path / "none")
    c = TestClient(app)
    r = c.post("/api/v1/auth/login",
               json={"username": "admin", "password": "v2-admin-pw"})
    h = {"X-CSRF-Token": r.json()["csrf_token"]}
    return {"client": c, "h": h, "store": bundle.store,
            "gateway": gateway,
            "iam": IAMService(bundle.store),
            "master": MasterDataService(bundle.store,
                                        IAMService(bundle.store))}


def _login(client: TestClient, username: str, password: str) -> dict:
    r = client.post("/api/v1/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


class TestIAM:
    def test_builtin_roles_and_bundles_seeded(self, env):
        iam = env["iam"]
        roles = {r["name"] for r in env["store"]._conn.execute(
            "SELECT name FROM iam_role_v1").fetchall()}
        for want in ("owner", "platform_admin", "customer_admin",
                     "project_manager", "survey_designer", "field_manager",
                     "reviewer", "analyst", "finance_operator", "read_only",
                     "agent_service"):
            assert want in roles, f"缺内置角色 {want}"
        scopes = {r["scope"] for r in env["store"]._conn.execute(
            "SELECT scope FROM iam_permission_bundle_v1").fetchall()}
        assert "master.read" in scopes and "iam.manage" in scopes

    def test_account_provisioning_and_login(self, env):
        c, h = env["client"], env["h"]
        r = c.post("/api/v1/iam/principals", headers=h, json={
            "kind": "user", "username": "alice_a",
            "display_name": "客户A管理员", "password": "pw-alice-1"})
        assert r.status_code == 200, r.text
        assert r.json()["principal"]["kind"] == "user"
        # agent 身份独立（不借用管理员账号），无口令不得登录
        r = c.post("/api/v1/iam/principals", headers=h, json={
            "kind": "agent", "username": "agent_a"})
        assert r.status_code == 200
        # 登录：口令正确/错误；agent 不得口令登录
        assert c.post("/api/v1/auth/login", json={
            "username": "alice_a", "password": "pw-alice-1"}
        ).status_code == 200
        assert c.post("/api/v1/auth/login", json={
            "username": "alice_a", "password": "wrong"}
        ).status_code == 401
        assert c.post("/api/v1/auth/login", json={
            "username": "agent_a", "password": "x"}
        ).status_code == 401

    def test_authorization_fail_closed_with_scope(self, env):
        iam = env["iam"]
        iam.create_principal(kind="user", username="bob_a",
                             password="pw", created_by="admin")
        # 无成员关系：fail-closed
        assert iam.authorize("bob_a", "master.read") is False
        iam.grant(username="bob_a", role="customer_admin",
                  customer_id="cust-a", granted_by="admin")
        # 作用域内通过；其他客户拒绝；未注册 scope 拒绝
        assert iam.authorize("bob_a", "master.read",
                             customer_id="cust-a") is True
        assert iam.authorize("bob_a", "master.read",
                             customer_id="cust-b") is False
        assert iam.authorize("bob_a", "no.such.scope",
                             customer_id="cust-a") is False

    def test_approval_matrix(self, env):
        iam = env["iam"]
        iam.create_principal(kind="user", username="fin1",
                             password="pw", created_by="admin")
        iam.grant(username="fin1", role="finance_operator",
                  granted_by="admin")
        assert iam.check_approval("fin1", "finance.finalize") is True
        assert iam.check_approval("fin1", "production.switch") is False
        # 矩阵未收录动作：fail-closed（非平台管理员一律拒绝）
        assert iam.check_approval("fin1", "unknown.action") is False

    def test_audit_append_only(self, env):
        env["iam"].audit("admin", "test.action", "res", {"k": 1})
        with pytest.raises(Exception):
            env["store"]._conn.execute("DELETE FROM iam_audit_event_v1")


class TestMasterData:
    def test_sku_library_lifecycle(self, env):
        m = env["master"]
        m.create_sku(sku_id="SKU-OLD", canonical_name="罐装魔爪330ml",
                     brand="魔爪", package_version="v1",
                     valid_from="2026-01-01", created_by="admin")
        m.create_sku(sku_id="SKU-NEW", canonical_name="罐装魔爪330ml",
                     brand="魔爪", package_version="v2",
                     valid_from="2026-07-01", created_by="admin")
        # 客户显示名与别名（SI3：测试客户必须绑定有效 test_run）
        from src.platform.test_data import FixtureTestDataService
        FixtureTestDataService(env["store"]).create_test_run_context(
            "uatv5_iam_sku_fx", customer_ids=[])
        m.create_customer(customer_id="cust-a", name="测试客户A",
                          is_test_fixture=True, created_by="admin",
                          test_run_id="uatv5_iam_sku_fx")
        m.add_alias(sku_id="SKU-NEW", alias="魔爪新包装", kind="alias",
                    actor="admin")
        m.add_alias(sku_id="SKU-NEW", alias="客户A叫法-魔爪",
                    kind="customer_display_name", customer_id="cust-a",
                    actor="admin")
        assert m.display_name_for("SKU-NEW", "cust-a") == "客户A叫法-魔爪"
        assert m.display_name_for("SKU-NEW") == "罐装魔爪330ml"
        # 新旧包装 supersede：身份不变，历史不删
        old = m.supersede_sku(old_sku_id="SKU-OLD", new_sku_id="SKU-NEW",
                              actor="admin")
        assert old["status"] == "superseded"
        assert old["superseded_by"] == "SKU-NEW"
        assert m.get_sku("SKU-OLD") is not None, "历史 SKU 不得删除"
        actives = {s["sku_id"] for s in m.list_skus()}
        assert "SKU-OLD" not in actives and "SKU-NEW" in actives
        # 不同 canonical 不得建立 supersede
        m.create_sku(sku_id="SKU-OTHER", canonical_name="其他商品",
                     created_by="admin")
        from src.platform.iam import MasterDataError
        with pytest.raises(MasterDataError):
            m.supersede_sku(old_sku_id="SKU-NEW", new_sku_id="SKU-OTHER",
                            actor="admin")

    def test_project_requires_customer(self, env):
        m = env["master"]
        from src.platform.iam import MasterDataError
        with pytest.raises(MasterDataError):
            m.create_project(project_id="pj-x", customer_id="no-such",
                             name="x", created_by="admin")


class TestCustomerIsolationG4:
    """两个 test fixture 客户：数据/任务/Usage/Agent 查询相互隔离。"""

    def _setup_two_customers(self, env):
        c, h = env["client"], env["h"]
        # SI3：先建 Test Run 上下文，fixture 客户必须绑定 test_run
        from src.platform.test_data import FixtureTestDataService
        FixtureTestDataService(env["store"]).create_test_run_context(
            "uatv5_iam_g4_fx", customer_ids=[])
        # 客户 A/B（显式 test fixture 标记）
        for cid, name in (("cust-a", "测试客户A"), ("cust-b", "测试客户B")):
            r = c.post("/api/v1/master/customers", headers=h, json={
                "customer_id": cid, "name": name,
                "is_test_fixture": True,
                "test_run_id": "uatv5_iam_g4_fx"})
            assert r.status_code == 200, r.text
        # 各建一个项目（SI3：fixture 客户下必须携带 test_run）
        for pid, cid in (("pj-a", "cust-a"), ("pj-b", "cust-b")):
            r = c.post("/api/v1/master/projects", headers=h, json={
                "project_id": pid, "customer_id": cid, "name": pid,
                "test_run_id": "uatv5_iam_g4_fx"})
            assert r.status_code == 200, r.text
        # 各开一个客户管理员 + 一个 agent 身份（独立，不借用 admin）
        for u, cid in (("alice", "cust-a"), ("bruno", "cust-b")):
            r = c.post("/api/v1/iam/principals", headers=h, json={
                "kind": "user", "username": u, "password": f"pw-{u}-123"})
            assert r.status_code == 200, r.text
            r = c.post("/api/v1/iam/grants", headers=h, json={
                "username": u, "role": "customer_admin",
                "customer_id": cid})
            assert r.status_code == 200, r.text
            r = c.post("/api/v1/iam/principals", headers=h, json={
                "kind": "agent", "username": f"agent-{u}"})
            assert r.status_code == 200
            r = c.post("/api/v1/iam/grants", headers=h, json={
                "username": f"agent-{u}", "role": "agent_service",
                "customer_id": cid})
            assert r.status_code == 200
        # 各客户跑一条真实识别（经 gateway，带 customer/project 作用域；
        # SI3：fixture 客户必须携带 test_run）
        for cid, pid in (("cust-a", "pj-a"), ("cust-b", "pj-b")):
            out = env["gateway"].submit(
                command_kind="vision.recognition.create",
                params={"images": [[f"{cid}.jpg", b"\xff\xd8fake"]]},
                actor="admin", source="api",
                customer_id=cid, project_id=pid,
                test_run_id="uatv5_iam_g4_fx")
            assert out["status"] == "succeeded"

    def test_full_isolation_matrix(self, env):
        self._setup_two_customers(env)
        c = env["client"]
        ha = _login(c, "alice", "pw-alice-123")

        # 1) 数据：alice 只见 cust-a（客户列表被作用域过滤）；
        # SI3：fixture 客户默认不进运营列表，需显式 include_fixture
        custs = c.get("/api/v1/master/customers?include_fixture=true"
                      ).json()["customers"]
        assert {x["customer_id"] for x in custs} == {"cust-a"}
        assert all(x["is_test_fixture"] for x in custs), \
            "测试数据必须显式标记 test fixture"

        # 2) 任务/Usage/事件概览：A 可见自己，越权 B 被 403
        ov = c.get("/api/v1/master/customers/cust-a/overview").json()
        assert ov["runs"] == 1 and ov["tasks"] == 1
        assert any(u["unit"] == "recognition_photo"
                   for u in ov["usage"])
        r = c.get("/api/v1/master/customers/cust-b/overview")
        assert r.status_code == 403, "客户 A 不得访问客户 B 的概览"

        # 3) 项目：alice 查 B 的项目被拒
        assert c.get("/api/v1/master/projects?customer_id=cust-a"
                     ).json()["count"] == 1
        assert c.get("/api/v1/master/projects?customer_id=cust-b"
                     ).status_code == 403

        # 4) Agent 查询隔离：agent-alice 仅 cust-a 作用域（fail-closed）
        iam = env["iam"]
        assert iam.authorize("agent-alice", "agent.query",
                             customer_id="cust-a") is True
        assert iam.authorize("agent-alice", "agent.query",
                             customer_id="cust-b") is False
        assert iam.authorize("agent-bruno", "agent.query",
                             customer_id="cust-a") is False

        # 5) admin（平台角色）可见全部并含 fixture 标记
        r = c.get("/api/v1/master/customers").json()
        pass  # alice 视图已在 1) 断言；admin 视图另行：
        admin_all = env["master"].list_customers(include_fixture=True)
        assert {x["customer_id"] for x in admin_all} == {"cust-a", "cust-b"}
        # SI3：运营默认口径不得返回 fixture 客户（指令三.11）
        assert env["master"].list_customers() == []

    def test_usage_lines_scoped_by_customer(self, env):
        self._setup_two_customers(env)
        rows = env["store"]._conn.execute(
            "SELECT customer_id, count(*) c FROM usage_event_v2"
            " GROUP BY customer_id").fetchall()
        scoped = {r["customer_id"]: r["c"] for r in rows}
        assert scoped.get("cust-a", 0) == 2
        assert scoped.get("cust-b", 0) == 2
        assert scoped.get("", 0) == 0, "Phase D 后 usage 必须带客户作用域"
