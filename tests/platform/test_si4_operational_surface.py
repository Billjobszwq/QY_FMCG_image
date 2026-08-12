"""SI4 T1 红测试：IAM/BI/Finance 运营面 fixture 污染清零与 Gate 3.1。

对应指令第六节 P0-001…P2-002 与第七~十一节契约。本文件先于实现
存在（红），不得为通过而删改断言语义。

覆盖：
- IAM 测试身份生命周期（provenance/归档/登录拒绝/列表隔离）
- BI effective operational（data-products 对账/metric/dashboard）
- Finance/前端测试默认值清除
- Registry 语义覆盖（生命周期声明）
- Gate 3.1 新检查 + 浏览器 12 页覆盖 + validator v6 ids
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.api.app import create_app
from src.platform.iam import IAMService
from src.platform.test_data import FixtureTestDataService

ROOT = Path(__file__).resolve().parents[2]
PW = "si4-admin-pw"
NS = "uatv6_si4_red"


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
    store = bundle.store
    app = create_app(services=(), probe=lambda spec: None,
                     bundle=bundle, recognition_adapter=_OkRecognition(),
                     profiles_service=profiles,
                     web_dist=tmp_path / "none")
    client = TestClient(app)
    r = client.post("/api/v1/auth/login",
                    json={"username": "admin", "password": PW})
    headers = {"X-CSRF-Token": r.json()["csrf_token"]}
    FixtureTestDataService(store).create_test_run_context(
        NS, customer_ids=[])
    return {"store": store, "bundle": bundle, "client": client,
            "h": headers, "iam": IAMService(store),
            "tds": FixtureTestDataService(store)}


def _mk_fixture_customer(env, cid="si4-fx-cust"):
    r = env["client"].post("/api/v1/master/customers", headers=env["h"],
                           json={"customer_id": cid,
                                 "name": "SI4 测试客户",
                                 "is_test_fixture": True,
                                 "test_run_id": NS})
    assert r.status_code == 200, r.text
    return cid


# --------------------------------------------------------------------
# IAM：测试身份生命周期（P0-001 / 指令第七节）
# --------------------------------------------------------------------

class TestIamIdentityLifecycle:
    def test_r01_principal_created_with_test_run_provenance(self, env):
        """受信创建：携带 current test_run → 同事务写 provenance。"""
        r = env["client"].post("/api/v1/iam/principals",
                               headers=env["h"],
                               json={"kind": "user",
                                     "username": f"{NS}_fw",
                                     "display_name": "外勤",
                                     "password": "pw-fixture-1",
                                     "test_run_id": NS})
        assert r.status_code == 200, r.text
        row = env["store"]._conn.execute(
            "SELECT data_scope, test_run_id, origin, visibility FROM"
            " iam_principal_v1 WHERE username=?",
            (f"{NS}_fw",)).fetchone()
        assert row is not None
        assert row["data_scope"] == "uat_fixture"
        assert row["test_run_id"] == NS
        assert row["origin"] == "uat"

    def test_r02_invalid_or_archived_test_run_rejected(self, env):
        r = env["client"].post("/api/v1/iam/principals",
                               headers=env["h"],
                               json={"kind": "user",
                                     "username": f"{NS}_bad",
                                     "password": "pw-fixture-2",
                                     "test_run_id": "no_such_run"})
        assert r.status_code == 409, \
            f"未登记 test_run 必须 409，实际 {r.status_code}"
        env["tds"].archive_namespace(NS)
        r2 = env["client"].post("/api/v1/iam/principals",
                                headers=env["h"],
                                json={"kind": "user",
                                      "username": f"{NS}_bad2",
                                      "password": "pw-fixture-3",
                                      "test_run_id": NS})
        assert r2.status_code == 409, \
            f"archived test_run 必须 409，实际 {r2.status_code}"

    def test_r03_archive_converges_identity_and_blocks_login(self, env):
        """归档事务：principal 禁用 + membership 归档 + 会话失效 +
        登录拒绝（稳定错误码）+ 审计；历史行保留。"""
        cid = _mk_fixture_customer(env)
        env["client"].post("/api/v1/iam/principals", headers=env["h"],
                           json={"kind": "user",
                                 "username": f"{NS}_pm",
                                 "password": "pw-fixture-4",
                                 "test_run_id": NS})
        env["client"].post("/api/v1/iam/grants", headers=env["h"],
                           json={"username": f"{NS}_pm",
                                 "role": "project_manager",
                                 "customer_id": cid})
        ok = env["client"].post("/api/v1/auth/login",
                                json={"username": f"{NS}_pm",
                                      "password": "pw-fixture-4"})
        assert ok.status_code == 200, "Test Run 期间应可登录"
        env["tds"].archive_namespace(NS)
        row = env["store"]._conn.execute(
            "SELECT status, visibility, archived_at, disabled_reason"
            " FROM iam_principal_v1 WHERE username=?",
            (f"{NS}_pm",)).fetchone()
        assert row["status"] != "active", "归档后 principal 必须禁用"
        assert row["visibility"] == "history"
        mem = env["store"]._conn.execute(
            "SELECT visibility FROM iam_membership_v1 m JOIN"
            " iam_principal_v1 p ON p.principal_id=m.principal_id"
            " WHERE p.username=?", (f"{NS}_pm",)).fetchone()
        assert mem is None or mem["visibility"] == "history"
        denied = env["client"].post("/api/v1/auth/login",
                                    json={"username": f"{NS}_pm",
                                          "password": "pw-fixture-4"})
        assert denied.status_code in (401, 403), \
            f"归档身份登录必须拒绝，实际 {denied.status_code}"
        body = str(denied.json())
        assert "IDENTITY_ARCHIVED" in body or "已归档" in body, \
            f"必须给出稳定错误码：{body}"
        sess = env["store"]._conn.execute(
            "SELECT count(*) c FROM auth_sessions WHERE actor=?",
            (f"{NS}_pm",)).fetchone()["c"]
        assert sess == 0, "归档后会话必须失效"
        audit = env["store"]._conn.execute(
            "SELECT count(*) c FROM iam_audit_event_v1 WHERE action"
            " LIKE '%test_data%' OR detail_json LIKE ?",
            (f"%{NS}%",)).fetchone()["c"]
        assert audit >= 1, "归档必须写审计"
        kept = env["store"]._conn.execute(
            "SELECT count(*) c FROM iam_principal_v1 WHERE username=?",
            (f"{NS}_pm",)).fetchone()["c"]
        assert kept == 1, "历史 principal 行不得物理删除"

    def test_r04_list_principals_default_operational(self, env):
        env["client"].post("/api/v1/iam/principals", headers=env["h"],
                           json={"kind": "user",
                                 "username": f"{NS}_an",
                                 "password": "pw-fixture-5",
                                 "test_run_id": NS})
        rows = env["iam"].list_principals()
        assert all(r["username"] != f"{NS}_an" for r in rows), \
            "正常账号列表不得显示 fixture 身份"
        rows_all = env["iam"].list_principals(include_fixture=True)
        assert any(r["username"] == f"{NS}_an" for r in rows_all), \
            "测试中心口径（include_fixture）必须可见历史"

    def test_r05_archived_membership_out_of_operational_authz(self, env):
        cid = _mk_fixture_customer(env, cid="si4-fx-cust2")
        env["client"].post("/api/v1/iam/principals", headers=env["h"],
                           json={"kind": "user",
                                 "username": f"{NS}_fin",
                                 "password": "pw-fixture-6",
                                 "test_run_id": NS})
        env["client"].post("/api/v1/iam/grants", headers=env["h"],
                           json={"username": f"{NS}_fin",
                                 "role": "finance_operator",
                                 "customer_id": cid})
        env["tds"].archive_namespace(NS)
        assert env["iam"].roles_of(f"{NS}_fin") == [], \
            "归档后 membership 不得参与运营授权"
        assert not env["iam"].authorize(f"{NS}_fin", "finance.read",
                                        customer_id=cid), \
            "归档身份不得通过运营权限检查"


# --------------------------------------------------------------------
# BI：effective operational 口径（P0-002/003 / 指令第八节）
# --------------------------------------------------------------------

class TestBiEffectiveOperational:
    def test_r06_data_products_match_operational_apis(self, env):
        cid = _mk_fixture_customer(env, cid="si4-fx-cust3")
        env["client"].post("/api/v1/master/projects", headers=env["h"],
                           json={"project_id": "si4-fx-prj",
                                 "customer_id": cid, "name": "fx",
                                 "test_run_id": NS})
        dp = env["client"].get("/api/v1/analytics/data-products").json()
        prods = {p["product"]: p for p in dp.get("products", [])}
        cust_rows = env["client"].get(
            "/api/v1/master/customers").json()["count"]
        assert prods["master.customers_v1"]["rows"] == cust_rows, \
            (f"data-products customers={prods['master.customers_v1']}"
             f" vs 运营 API count={cust_rows}（禁止物理行数）")

    def test_r07_metric_created_with_provenance_and_hidden(self, env):
        r = env["client"].post("/api/v1/analytics/metrics/computed",
                               headers=env["h"],
                               json={"metric_id": f"{NS}_rate",
                                     "name": f"SI4 自检率 {NS}",
                                     "formula":
                                         "survey:submitted:count",
                                     "test_run_id": NS})
        assert r.status_code == 200, r.text
        row = env["store"]._conn.execute(
            "SELECT data_scope, test_run_id, status FROM bi_metric_v1"
            " WHERE metric_id=?", (f"{NS}_rate",)).fetchone()
        assert row is not None
        assert row["data_scope"] == "uat_fixture"
        assert row["test_run_id"] == NS
        metrics = env["client"].get(
            "/api/v1/analytics/metrics").json().get("metrics", [])
        assert all(m["metric_id"] != f"{NS}_rate" for m in metrics), \
            "运营指标目录不得显示 UAT metric"
        env["tds"].archive_namespace(NS)
        row2 = env["store"]._conn.execute(
            "SELECT status FROM bi_metric_v1 WHERE metric_id=?",
            (f"{NS}_rate",)).fetchone()
        assert row2["status"] == "archived", \
            "归档后 UAT metric 必须 archived（仅测试中心可追溯）"

    def test_r08_dashboard_inherits_test_run_scope(self, env):
        cid = _mk_fixture_customer(env, cid="si4-fx-cust4")
        r = env["client"].post("/api/v1/analytics/dashboards",
                               headers=env["h"],
                               json={"name": f"SI4 看板 {NS}",
                                     "customer_id": cid,
                                     "widgets": [], "filters": {},
                                     "test_run_id": NS})
        assert r.status_code == 200, r.text
        did = r.json()["dashboard_id"]
        row = env["store"]._conn.execute(
            "SELECT data_scope, test_run_id FROM bi_dashboard_v1 WHERE"
            " dashboard_id=?", (did,)).fetchone()
        assert row["data_scope"] == "uat_fixture"
        assert row["test_run_id"] == NS
        dashs = env["client"].get(
            "/api/v1/analytics/dashboards").json().get("dashboards", [])
        assert all(d.get("dashboard_id") != did for d in dashs), \
            "运营看板列表不得显示 fixture 看板"


# --------------------------------------------------------------------
# Finance / 前端默认值（P1-001/002 / 指令第九节）
# --------------------------------------------------------------------

class TestFrontendDefaults:
    def test_r09_no_hardcoded_fixture_customer_defaults(self):
        pat = re.compile(r"uat-cust-[ab]|demo-cust-[ab]|uat_cust|"
                         "demo_cust")
        hits = []
        for p in (ROOT / "web" / "src").rglob("*"):
            if p.is_file() and p.suffix in (".tsx", ".ts"):
                for i, line in enumerate(p.read_text(
                        encoding="utf-8").splitlines(), 1):
                    if pat.search(line):
                        hits.append(f"{p.name}:{i}")
        assert hits == [], f"前端不得硬编码测试客户默认值: {hits}"


# --------------------------------------------------------------------
# Registry 语义覆盖（P1-004 / 指令第十节）
# --------------------------------------------------------------------

class TestRegistrySemantics:
    def test_r10_registry_declares_lifecycle_for_sensitive_tables(self):
        from src.platform.scope_registry import SCOPE_REGISTRY
        for t in ("iam_principal_v1", "iam_membership_v1",
                  "bi_metric_v1", "bi_dashboard_v1", "auth_sessions",
                  "import_batch_v1", "fin_rate_card_v1",
                  "agent_definition_v1", "platform_flag"):
            e = SCOPE_REGISTRY.get(t)
            assert e is not None, f"{t} 未登记"
            for key in ("uat_creatable", "provenance", "archive_rule",
                        "login_impact", "billing_impact", "bi_impact",
                        "browser_surface"):
                assert key in e, f"{t} 缺生命周期声明: {key}"

    def test_r11_import_batch_scope_cols_exist(self, env):
        cols = {r[1] for r in env["store"]._conn.execute(
            "PRAGMA table_info(import_batch_v1)").fetchall()}
        assert "data_scope" in cols and "test_run_id" in cols, \
            "import_batch_v1 必须具备 scope 列（防分类逃逸）"


# --------------------------------------------------------------------
# Gate 3.1（P1-003/005 / 指令第十一节）
# --------------------------------------------------------------------

class TestGate31:
    def test_r12_gate_blocks_active_fixture_principal(self, env):
        from src.platform.gate_evaluator import \
            evaluate_gate_from_evidence
        env["client"].post("/api/v1/iam/principals", headers=env["h"],
                           json={"kind": "user",
                                 "username": f"{NS}_gate",
                                 "password": "pw-fixture-7",
                                 "test_run_id": NS})
        res = evaluate_gate_from_evidence(store=env["store"])
        assert res["gate"] != "READY_FOR_REAL_DATA_UAT", \
            "存在 active fixture principal 时 Gate 不得 READY"
        assert any("iam" in c["check"].lower() for c in
                   res["checks"] if not c["ok"]), \
            "必须有 IAM 检查项失败"

    def test_r13_gate_blocks_data_products_mismatch(self, env):
        from src.platform.gate_evaluator import \
            evaluate_gate_from_evidence
        cid = _mk_fixture_customer(env, cid="si4-fx-cust5")
        res = evaluate_gate_from_evidence(store=env["store"])
        assert res["gate"] != "READY_FOR_REAL_DATA_UAT"
        checks = {c["check"]: c for c in res["checks"]}
        assert any("data_product" in k for k in checks), \
            "Gate 必须包含 data-products 对账检查"

    def test_r14_gate_browser_requires_12_pages(self):
        from src.platform.gate_evaluator import \
            REQUIRED_BROWSER_ROUTES
        need = {"home", "data/import", "survey/design", "geo/addresses",
                "vision/recognize", "analytics/reports",
                "workflow/studio", "iam/accounts", "master/customers",
                "finance/contracts", "help", "status"}
        assert need.issubset(set(REQUIRED_BROWSER_ROUTES)), \
            "Gate 必须强制 12 个一级工作台覆盖"

    def test_r15_validator_v6_requires_new_ids(self):
        from scripts.uat_report_validator import validate_report
        rep = {"protocol": "uatv6", "namespace": "uatv6_x",
               "checks": [], "failed": 0, "ids": {}}
        problems = validate_report(rep)
        assert any("principal" in p for p in problems), \
            "V6 validator 必须要求 principal IDs"
        assert any("metric" in p for p in problems)
        assert any("dashboard" in p for p in problems)
