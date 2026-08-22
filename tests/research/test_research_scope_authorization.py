"""R2-03（R2-P0-02）：Research API 的 IAM action permission + 持久化
run scope 授权红测试。

契约（round-2-hardening/01 §4）：
- run ID 不是授权凭证；所有端点必须 session → IAM action permission
  → ScopeResolver → CognitiveContext → run 持久化 scope 对比；
- start 可接收 requested customer/project/test_run，但必须由 IAM
  membership 与 ScopeResolver 验证；
- citations/synthesize 使用 run 持久化 scope，不接受 query 参数改写；
- 跨主体/客户/项目/data_scope/test_run 负例零泄漏：无权与不存在统一
  安全响应，不得泄露 question/state/counts/scope。

修复前这些测试必须红：现状是 status/resume/cancel/decide/claims 只要
登录即可按 run ID 访问；citations/synthesize 接受调用者自带 scope。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import build_production_bundle
from src.platform.api.app import create_app
from src.platform.iam import IAMService, MasterDataService

ADMIN_PW = "r2scoop-admin-pw"
PW = {"user-a": "r2scoop-a-pw", "user-b": "r2scoop-b-pw",
      "user-ro": "r2scoop-ro-pw"}
SECRET_QUESTION = "机密研究问题-甲：客户A内部报销口径"


@pytest.fixture()
def app_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", ADMIN_PW)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("PLATFORM_USERS", raising=False)
    monkeypatch.delenv("PLATFORM_ADMIN_CREDENTIALS", raising=False)
    monkeypatch.setenv("COGNITION_CAS_ROOT", str(tmp_path / "cas"))
    monkeypatch.setenv("COGNITION_INDEX_ROOT", str(tmp_path / "index"))
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=None, probe=lambda spec: None)
    iam = IAMService(bundle.store)
    master = MasterDataService(bundle.store, iam)
    for cust, proj in (("cust-a", "proj-a"), ("cust-b", "proj-b")):
        master.create_customer(customer_id=cust, name=cust,
                               created_by="admin")
        master.create_project(project_id=proj, customer_id=cust,
                              name=proj, created_by="admin")
    role_map = {"user-a": "customer_admin", "user-b": "customer_admin",
                "user-ro": "read_only"}
    scope_map = {"user-a": ("cust-a", "proj-a"),
                 "user-b": ("cust-b", "proj-b"),
                 "user-ro": ("cust-a", "proj-a")}
    for name in PW:
        iam.create_principal(kind="user", username=name, password=PW[name],
                             created_by="admin")
        cust, proj = scope_map[name]
        iam.grant(username=name, role=role_map[name], customer_id=cust,
                  project_id=proj, granted_by="admin")
    app = create_app(services=(), probe=lambda spec: None, bundle=bundle,
                     web_dist=Path("/nonexistent"))
    return app, bundle


def _login(app, username):
    c = TestClient(app)
    pw = ADMIN_PW if username == "admin" else PW[username]
    r = c.post("/api/v1/auth/login",
               json={"username": username, "password": pw})
    assert r.status_code == 200, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


def _start(client, h, *, question=SECRET_QUESTION, customer_id="cust-a",
           project_id="proj-a"):
    return client.post("/api/v1/research/runs", headers=h, json={
        "question": question, "mode": "lookup",
        "customer_id": customer_id, "project_id": project_id})


class TestStartScopeValidation:
    def test_start_with_membership_persists_server_scope(self, app_bundle):
        app, _ = app_bundle
        c, h = _login(app, "user-a")
        r = _start(c, h)
        assert r.status_code == 200, r.text
        d = r.json()
        # run 持久化 scope 必须由服务端固化并可回查
        assert d["customer_id"] == "cust-a"
        assert d["project_id"] == "proj-a"
        assert d["data_scope"] == "operational"

    def test_start_unknown_customer_rejected(self, app_bundle):
        app, _ = app_bundle
        c, h = _login(app, "user-a")
        r = _start(c, h, customer_id="cust-unknown", project_id="")
        assert r.status_code == 403, r.text

    def test_start_without_run_permission_rejected(self, app_bundle):
        """read_only 有 research.read 但无 research.run → 拒绝。"""
        app, _ = app_bundle
        c, h = _login(app, "user-ro")
        r = _start(c, h)
        assert r.status_code == 403, r.text

    def test_start_fixture_customer_without_test_run_rejected(
            self, app_bundle):
        """fixture 客户缺 test_run → ScopeResolver fail-closed。"""
        app, bundle = app_bundle
        iam = IAMService(bundle.store)
        bundle.store._conn.execute(
            "INSERT INTO md_customer_v1 (customer_id, name,"
            " is_test_fixture, retention_policy, created_by, created_at,"
            " updated_at, data_scope, test_run_id) VALUES"
            " ('cust-fix','脏fixture',1,'','admin',"
            " '2026-08-20T00:00:00+00:00','2026-08-20T00:00:00+00:00',"
            " 'uat_fixture','')")
        bundle.store._conn.commit()
        iam.grant(username="user-a", role="customer_admin",
                  customer_id="cust-fix", granted_by="admin")
        c, h = _login(app, "user-a")
        r = _start(c, h, customer_id="cust-fix", project_id="")
        assert r.status_code == 403, r.text


class TestCrossScopeZeroLeakage:
    def _user_a_run(self, app):
        c, h = _login(app, "user-a")
        r = _start(c, h)
        assert r.status_code == 200, r.text
        return r.json()["research_run_id"]

    def test_cross_customer_access_denied_on_all_endpoints(
            self, app_bundle):
        app, _ = app_bundle
        run_id = self._user_a_run(app)
        cb, hb = _login(app, "user-b")
        own = {"customer_id": "cust-b", "project_id": "proj-b"}
        got = {
            "status": cb.get(f"/api/v1/research/runs/{run_id}",
                             params=own),
            "claims": cb.get(f"/api/v1/research/runs/{run_id}/claims",
                             params=own),
            "citations": cb.get(
                f"/api/v1/research/runs/{run_id}/citations", params=own),
            "resume": cb.post(
                f"/api/v1/research/runs/{run_id}/resume", headers=hb,
                params=own),
            "cancel": cb.post(
                f"/api/v1/research/runs/{run_id}/cancel", headers=hb,
                params=own),
            "decide": cb.post(
                f"/api/v1/research/runs/{run_id}/decide-conflict",
                headers=hb, json={"resolution": "x", **own}),
            "synthesize": cb.post(
                f"/api/v1/research/runs/{run_id}/synthesize", headers=hb,
                params=own),
        }
        details = set()
        for name, r in got.items():
            assert r.status_code == 404, f"{name} 应为统一 404: {r.text}"
            # 零泄漏：响应不得包含问题、状态、计数或 scope
            assert SECRET_QUESTION not in r.text
            assert "succeeded" not in r.text
            assert "stop_reason" not in r.text
            assert "cust-a" not in r.text
            details.add(r.json()["detail"])
        # 所有端点使用同一安全消息（不可区分）
        assert len(details) == 1

    def test_denied_and_not_found_are_indistinguishable(self, app_bundle):
        app, _ = app_bundle
        run_id = self._user_a_run(app)
        cb, _ = _login(app, "user-b")
        own = {"customer_id": "cust-b", "project_id": "proj-b"}
        denied = cb.get(f"/api/v1/research/runs/{run_id}", params=own)
        missing = cb.get("/api/v1/research/runs/rrun-does-not-exist",
                         params=own)
        assert denied.status_code == 404
        assert missing.status_code == 404
        assert denied.json()["detail"] == missing.json()["detail"]

    def test_no_scope_params_also_denied_for_non_platform(
            self, app_bundle):
        app, _ = app_bundle
        run_id = self._user_a_run(app)
        cb, hb = _login(app, "user-b")
        assert cb.get(f"/api/v1/research/runs/{run_id}").status_code == 404
        assert cb.get(
            f"/api/v1/research/runs/{run_id}/claims").status_code == 404
        assert cb.post(f"/api/v1/research/runs/{run_id}/cancel",
                       headers=hb).status_code == 404

    def test_owner_and_platform_admin_allowed(self, app_bundle):
        app, _ = app_bundle
        run_id = self._user_a_run(app)
        # 属主（同 scope membership）带 scope 参数可访问
        ca, ha = _login(app, "user-a")
        own = {"customer_id": "cust-a", "project_id": "proj-a"}
        assert ca.get(f"/api/v1/research/runs/{run_id}",
                      params=own).status_code == 200
        assert ca.get(f"/api/v1/research/runs/{run_id}/claims",
                      params=own).status_code == 200
        # 平台管理员（env admin）跨客户可访问
        cadm, _ = _login(app, "admin")
        r = cadm.get(f"/api/v1/research/runs/{run_id}")
        assert r.status_code == 200
        assert r.json()["question"] == SECRET_QUESTION

    def test_decide_requires_research_decide_permission(self, app_bundle):
        """customer_admin 无 research.decide → 统一 404，即使 run 属于
        其客户。"""
        app, _ = app_bundle
        run_id = self._user_a_run(app)
        ca, ha = _login(app, "user-a")
        r = ca.post(f"/api/v1/research/runs/{run_id}/decide-conflict",
                    headers=ha, json={"resolution": "x",
                                      "customer_id": "cust-a",
                                      "project_id": "proj-a"})
        assert r.status_code == 404
        assert SECRET_QUESTION not in r.text


class TestRunScopeLockedForCitationsSynthesize:
    def test_citations_query_params_cannot_rewrite_scope(self, app_bundle):
        """citations/synthesize 的有效 scope 必须来自 run 持久化 scope：
        平台管理员携带错误 customer 参数也不得改变核验 scope；非平台
        主体携带他人 customer 参数先被访问检查拒绝。"""
        app, _ = app_bundle
        ca, ha = _login(app, "user-a")
        r = _start(ca, ha)
        run_id = r.json()["research_run_id"]
        own = {"customer_id": "cust-a", "project_id": "proj-a"}
        base = ca.get(f"/api/v1/research/runs/{run_id}/citations",
                      params=own)
        assert base.status_code == 200, base.text
        # 属主携带他人 customer → 访问检查拒绝（统一 404）
        assert ca.get(f"/api/v1/research/runs/{run_id}/citations",
                      params={"customer_id": "cust-b",
                              "project_id": "proj-b"}).status_code == 404
        # 平台管理员携带错误 customer：访问通过，但核验 scope 仍为
        # run 持久化 scope → 结果与无参数一致
        cadm, hadm = _login(app, "admin")
        rw = cadm.get(f"/api/v1/research/runs/{run_id}/citations",
                      params={"customer_id": "cust-b"})
        assert rw.status_code == 200
        assert rw.json()["gate_ok"] == base.json()["gate_ok"]
        assert rw.json()["verdicts"] == base.json()["verdicts"]
