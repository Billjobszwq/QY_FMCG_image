"""OSV5 T1 红测试：Import Center 越权/测试污染/可执行 Registry/Gate 3.2。

对应指令第四节 OSV5-001…012 与第五~十二节契约。本文件先于实现
存在（红），不得为通过而删改断言语义；名称判断只允许出现在历史
纠偏的辅助诊断位，运行时断言全部结构化。

覆盖（指令第十一节 30 类）：
1-3  旧 20 条污染复现/纠偏 dry-run/quarantine
4-9  UAT upload 作用域/archived 拒绝/operational 不得伪造/
     多客户关联/全客户授权/整批拒绝
10-14 read_only list/detail/dry-run/commit/error-csv 越权
15-16 DTO 无原始 payload/preview 权限与脱敏
17-18 fixture 默认排除/history 显式授权
19-20 BI effective/Test Center 计数
21   归档幂等与归档后拒提交
22-28 Registry 字段/主键/parent/handler/scanner/archiver/漏注册阻断
29-31 Gate import 负例/版本一致/UAT V7 validator
32   Session 过期清理（bill 豁免）
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.api.app import create_app
from src.platform.iam import IAMService
from src.platform.test_data import FixtureTestDataService

ROOT = Path(__file__).resolve().parents[2]
PW = "osv5-admin-pw"
NS = "uatv7_osv5_red"
USER_PW = "osv5-user-pw"


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


def _upload(c, h, tid: str, data: bytes, name="f.csv", **fields):
    form = {"template_id": tid, **fields}
    return c.post("/api/v1/import/upload", headers=h, data=form,
                  files={"file": (name, io.BytesIO(data), "text/csv")})


def _mk_user(env, uname: str, role: str, customer_id: str = ""):    # noqa: E501
    env["iam"].create_principal(kind="user", username=uname,
                                display_name=uname, password=USER_PW,
                                created_by="admin")
    env["iam"].grant(username=uname, role=role,
                     customer_id=customer_id, granted_by="admin")
    r = env["client"].post("/api/v1/auth/login",
                           json={"username": uname, "password": USER_PW})
    assert r.status_code == 200, r.text
    return r


def _cust_csv(*cids):
    rows = "".join(f"{cid},客户{cid},月结30天,,\n" for cid in cids)
    return ("customer_id,name,payment_terms,retention_policy,tags\n"
            + rows).encode("utf-8-sig")


def _db_hash(conn, table="import_batch_v1"):
    rows = conn.execute(
        f"SELECT * FROM {table} ORDER BY batch_id").fetchall()
    return hashlib.sha256(
        json.dumps([dict(r) for r in rows], ensure_ascii=False,
                   default=str).encode()).hexdigest()


# --------------------------------------------------------------------
# 1-3 历史 20 条污染复现与纠偏（OSV5-001）
# --------------------------------------------------------------------

class TestLegacyReconciliation:
    def _seed_legacy(self, env, n=20):
        """在临时库复刻现场：operational 批次但内容属 fixture 客户。"""
        conn = env["store"]._conn
        fx = env["tds"].create_test_run_context(
            "uat_hist_run", customer_ids=[f"{NS}_hist_cust"])
        for i in range(n):
            conn.execute(
                "INSERT INTO import_batch_v1 (batch_id, template_id,"
                " filename, file_format, file_hash, status, actor,"
                " row_count, mapping_json, dry_run_json,"
                " error_report_json, commit_json, created_at,"
                " updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"imp-legacy-{i:02d}", "customers_v1",
                 f"uat_customers_{i}.csv", "csv", "h" + str(i),
                 "committed", "bill", 1,
                 json.dumps({"header": ["customer_id", "name"],
                             "rows": [[f"{NS}_hist_cust", "历史客户"]]}),
                 "{}", "[]", "{}", "2026-08-01T00:00:00+00:00",
                 "2026-08-01T00:00:00+00:00"))
        conn.commit()
        return fx

    def test_r01_legacy_batches_reconciled_out_of_operational(self, env):
        self._seed_legacy(env)
        from scripts.scope_reconcile_imports_v5 import (
            apply_reconciliation, plan_reconciliation)
        conn = env["store"]._conn
        plan = plan_reconciliation(conn)
        assert plan["total"] == 20
        apply_reconciliation(conn, plan, actor="osv5-red-test")
        op = conn.execute(
            "SELECT count(*) c FROM import_batch_v1 WHERE"
            " COALESCE(data_scope,'operational')='operational'"
        ).fetchone()["c"]
        assert op == 0, "纠偏后运营面不得残留历史 UAT 批次"
        audited = conn.execute(
            "SELECT count(*) c FROM scope_backfill_audit_v1 WHERE"
            " table_name='import_batch_v1'").fetchone()["c"]
        assert audited >= 20, "逐批 decision evidence 必须入账"

    def test_r02_reconcile_dry_run_is_read_only(self, env):
        self._seed_legacy(env, n=3)
        from scripts.scope_reconcile_imports_v5 import plan_reconciliation
        conn = env["store"]._conn
        before = _db_hash(conn)
        plan_reconciliation(conn)  # plan 只读
        assert _db_hash(conn) == before, "classification plan 不得写库"

    def test_r03_unassignable_batch_quarantined(self, env):
        conn = env["store"]._conn
        conn.execute(
            "INSERT INTO import_batch_v1 (batch_id, template_id,"
            " filename, file_format, file_hash, status, actor,"
            " row_count, mapping_json, dry_run_json,"
            " error_report_json, commit_json, created_at, updated_at)"
            " VALUES ('imp-orphan','customers_v1','misc.csv','csv','h',"
            " 'committed','bill',1,"
            " '{\"header\":[\"customer_id\"],\"rows\":[[\"no_such_c\"]]}'"
            ",'{}','[]','{}','2026-08-01T00:00:00+00:00',"
            " '2026-08-01T00:00:00+00:00')")
        conn.commit()
        from scripts.scope_reconcile_imports_v5 import (
            apply_reconciliation, plan_reconciliation)
        plan = plan_reconciliation(conn)
        hit = [d for d in plan["decisions"]
               if d["batch_id"] == "imp-orphan"]
        assert hit and hit[0]["decision"] == "quarantine"
        apply_reconciliation(conn, plan, actor="osv5-red-test")
        row = conn.execute(
            "SELECT data_scope FROM import_batch_v1 WHERE"
            " batch_id='imp-orphan'").fetchone()
        assert row["data_scope"] == "quarantine"


# --------------------------------------------------------------------
# 4-9 创建链作用域（OSV5-002 / 指令第五节）
# --------------------------------------------------------------------

class TestUploadScope:
    def test_r04_uat_upload_writes_fixture_scope(self, env):
        r = _upload(env["client"], env["h"], "customers_v1",
                    _cust_csv(f"{NS}_c1"), test_run_id=NS)
        assert r.status_code == 200, r.text
        bid = r.json()["batch"]["batch_id"]
        row = env["store"]._conn.execute(
            "SELECT data_scope, test_run_id FROM import_batch_v1"
            " WHERE batch_id=?", (bid,)).fetchone()
        assert row["data_scope"] == "uat_fixture"
        assert row["test_run_id"] == NS

    def test_r05_archived_or_unknown_test_run_rejected(self, env):
        r = _upload(env["client"], env["h"], "customers_v1",
                    _cust_csv("x1"), test_run_id="no_such_run")
        assert r.status_code == 409, r.text
        env["tds"].archive_namespace(NS)
        r2 = _upload(env["client"], env["h"], "customers_v1",
                     _cust_csv("x2"), test_run_id=NS)
        assert r2.status_code == 409, r2.text

    def test_r06_operational_upload_cannot_forge_test_run(self, env):
        # 普通运营上传不得携带 test_run 语义之外的作用域漂移；
        # 已提交 operational 批次不得再绑定 Test Run。
        r = _upload(env["client"], env["h"], "customers_v1",
                    _cust_csv(f"{NS}_op1"))
        bid = r.json()["batch"]["batch_id"]
        row = env["store"]._conn.execute(
            "SELECT data_scope, COALESCE(test_run_id,'') tr FROM"
            " import_batch_v1 WHERE batch_id=?", (bid,)).fetchone()
        assert row["data_scope"] == "operational" and row["tr"] == ""
        rb = env["client"].post(
            f"/api/v1/import/batches/{bid}/bind-test-run",
            headers=env["h"], json={"test_run_id": NS})
        assert rb.status_code in (403, 404, 409), \
            "operational 批次禁止后补绑定 Test Run"

    def test_r07_multi_customer_associations(self, env):
        r = _upload(env["client"], env["h"], "customers_v1",
                    _cust_csv(f"{NS}_c1", f"{NS}_c2"), test_run_id=NS)
        bid = r.json()["batch"]["batch_id"]
        rows = env["store"]._conn.execute(
            "SELECT customer_id, authorization_decision FROM"
            " import_batch_customer_scope_v1 WHERE batch_id=?"
            " ORDER BY customer_id", (bid,)).fetchall()
        assert {x["customer_id"] for x in rows} == {
            f"{NS}_c1", f"{NS}_c2"}
        assert all(x["authorization_decision"] == "granted"
                   for x in rows)

    def test_r08_committed_objects_inherit_batch_scope(self, env):
        r = _upload(env["client"], env["h"], "customers_v1",
                    _cust_csv(f"{NS}_c1"), test_run_id=NS)
        bid = r.json()["batch"]["batch_id"]
        env["client"].post(f"/api/v1/import/batches/{bid}/dry-run",
                           headers=env["h"])
        cm = env["client"].post(f"/api/v1/import/batches/{bid}/commit",
                                headers=env["h"])
        assert cm.status_code == 200, cm.text
        row = env["store"]._conn.execute(
            "SELECT data_scope, test_run_id FROM md_customer_v1 WHERE"
            f" customer_id='{NS}_c1'").fetchone()
        assert row is not None
        assert row["data_scope"] == "uat_fixture"
        assert row["test_run_id"] == NS


class TestCustomerAuthorization:
    def _setup_two_customer_users(self, env):
        # admin 先建两个运营客户
        for cid in ("osv5-cust-a", "osv5-cust-b"):
            r = env["client"].post("/api/v1/master/customers",
                                   headers=env["h"],
                                   json={"customer_id": cid,
                                         "name": cid})
            assert r.status_code == 200, r.text
        _mk_user(env, "low_user", "read_only")
        _mk_user(env, "cust_a_user", "customer_admin", "osv5-cust-a")

    def test_r09_any_unauthorized_customer_rejects_whole_batch(
            self, env):
        self._setup_two_customer_users(env)
        lg = env["client"].post(
            "/api/v1/auth/login",
            json={"username": "cust_a_user", "password": USER_PW})
        h2 = {"X-CSRF-Token": lg.json()["csrf_token"]}
        # cust_a_user 仅授权 cust-a：批次含 cust-b → 整批拒绝
        r = _upload(env["client"], h2, "stores_addresses_v1",
                    ("customer_id,store_name,raw_address\n"
                     "osv5-cust-a,店A,地址A\n"
                     "osv5-cust-b,店B,地址B\n").encode("utf-8-sig"),
                    name="mixed.csv")
        assert r.status_code == 403, \
            f"任一客户无权必须整批拒绝，实际 {r.status_code}"
        n = env["store"]._conn.execute(
            "SELECT count(*) c FROM import_batch_v1 WHERE actor="
            "'cust_a_user'").fetchone()["c"]
        assert n == 0, "整批拒绝时批次不得落库"


# --------------------------------------------------------------------
# 10-14 越权（OSV5-003）
# --------------------------------------------------------------------

class TestPrivilegeEscalation:
    @pytest.fixture()
    def setup(self, env):
        for cid in ("osv5-cust-a", "osv5-cust-b"):
            env["client"].post("/api/v1/master/customers",
                               headers=env["h"],
                               json={"customer_id": cid, "name": cid})
        # admin 上传并 dry-run 一个 cust-a 批次
        r = _upload(env["client"], env["h"], "stores_addresses_v1",
                    ("customer_id,store_name,raw_address\n"
                     "osv5-cust-a,店A,地址A\n").encode("utf-8-sig"))
        bid = r.json()["batch"]["batch_id"]
        env["client"].post(f"/api/v1/import/batches/{bid}/dry-run",
                           headers=env["h"])
        _mk_user(env, "low_user", "read_only")
        _mk_user(env, "cust_b_user", "customer_admin", "osv5-cust-b")
        lg = env["client"].post(
            "/api/v1/auth/login",
            json={"username": "low_user", "password": USER_PW})
        lh = {"X-CSRF-Token": lg.json()["csrf_token"]}
        lg2 = env["client"].post(
            "/api/v1/auth/login",
            json={"username": "cust_b_user", "password": USER_PW})
        bh = {"X-CSRF-Token": lg2.json()["csrf_token"]}
        return {"env": env, "bid": bid, "lh": lh, "bh": bh}

    def test_r10_readonly_list_denied(self, setup):
        env, lh = setup["env"], setup["lh"]
        r = env["client"].get("/api/v1/import/batches", headers=lh)
        assert r.status_code == 403 or r.json().get("count") == 0

    def test_r11_readonly_detail_cross_customer_403(self, setup):
        env, lh, bh, bid = (setup["env"], setup["lh"], setup["bh"],
                            setup["bid"])
        for h in (lh, bh):
            r = env["client"].get(f"/api/v1/import/batches/{bid}",
                                  headers=h)
            assert r.status_code == 403, \
                f"跨客户/无权详情必须 403，实际 {r.status_code}"

    def test_r12_readonly_dry_run_403(self, setup):
        env, lh, bid = setup["env"], setup["lh"], setup["bid"]
        r = env["client"].post(
            f"/api/v1/import/batches/{bid}/dry-run", headers=lh)
        assert r.status_code == 403

    def test_r13_readonly_commit_403_and_no_write(self, setup):
        env, lh, bid = setup["env"], setup["lh"], setup["bid"]
        r = env["client"].post(
            f"/api/v1/import/batches/{bid}/commit", headers=lh)
        assert r.status_code == 403
        n = env["store"]._conn.execute(
            "SELECT count(*) c FROM geo_address_v1").fetchone()["c"]
        assert n == 0, "越权提交不得写入业务表"

    def test_r14_errors_csv_permission(self, setup):
        env, lh, bh, bid = (setup["env"], setup["lh"], setup["bh"],
                            setup["bid"])
        for h in (lh, bh):
            r = env["client"].get(
                f"/api/v1/import/batches/{bid}/errors.csv", headers=h)
            assert r.status_code == 403


# --------------------------------------------------------------------
# 15-16 DTO 与脱敏（OSV5-004）
# --------------------------------------------------------------------

class TestDtoAndRedaction:
    def test_r15_detail_returns_dto_not_raw_payloads(self, env):
        r = _upload(env["client"], env["h"], "customers_v1",
                    _cust_csv(f"{NS}_c1"), test_run_id=NS)
        bid = r.json()["batch"]["batch_id"]
        d = env["client"].get(f"/api/v1/import/batches/{bid}",
                              headers=env["h"]).json()["batch"]
        for k in ("mapping_json", "dry_run_json", "error_report_json",
                  "commit_json", "mapping", "rows"):
            assert k not in d, f"DTO 不得返回原始 payload：{k}"
        for k in ("batch_id", "template_id", "filename", "actor",
                  "status", "data_scope", "test_run_id",
                  "customer_scopes", "created_at"):
            assert k in d, f"DTO 缺少必要字段：{k}"

    def test_r16_raw_preview_requires_audit_scope(self, env):
        r = _upload(env["client"], env["h"], "customers_v1",
                    _cust_csv(f"{NS}_c1"), test_run_id=NS)
        bid = r.json()["batch"]["batch_id"]
        # 创建者/管理员可见（脱敏 + 行数上限）
        ok = env["client"].get(
            f"/api/v1/import/batches/{bid}/preview", headers=env["h"])
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert body.get("redacted") is True
        assert len(body.get("rows", [])) <= 50
        # 无 data.import.audit 的第三方 → 403
        _mk_user(env, "cust_a_user", "customer_admin", "osv5-x")
        lg = env["client"].post(
            "/api/v1/auth/login",
            json={"username": "cust_a_user", "password": USER_PW})
        h2 = {"X-CSRF-Token": lg.json()["csrf_token"]}
        deny = env["client"].get(
            f"/api/v1/import/batches/{bid}/preview", headers=h2)
        assert deny.status_code == 403


# --------------------------------------------------------------------
# 17-18 列表隔离（OSV5-007 配套 API 口径）
# --------------------------------------------------------------------

class TestListIsolation:
    def test_r17_fixture_excluded_from_default_list_and_bi(self, env):
        before = env["client"].get(
            "/api/v1/analytics/data-products",
            headers=env["h"]).json()
        imp0 = next(p["rows"] for p in before["products"]
                    if p["product"] == "import.batches_v1")
        r = _upload(env["client"], env["h"], "customers_v1",
                    _cust_csv(f"{NS}_c1"), test_run_id=NS)
        bid = r.json()["batch"]["batch_id"]
        lst = env["client"].get("/api/v1/import/batches",
                                headers=env["h"]).json()
        assert bid not in [b["batch_id"] for b in lst["batches"]], \
            "运营默认列表不得出现 fixture 批次"
        after = env["client"].get(
            "/api/v1/analytics/data-products",
            headers=env["h"]).json()
        imp1 = next(p["rows"] for p in after["products"]
                    if p["product"] == "import.batches_v1")
        assert imp1 == imp0, "BI operational import count 不得增加"

    def test_r18_history_requires_explicit_authorization(self, env):
        r = _upload(env["client"], env["h"], "customers_v1",
                    _cust_csv(f"{NS}_c1"), test_run_id=NS)
        bid = r.json()["batch"]["batch_id"]
        # 平台管理员显式 include_fixture 可见
        hist = env["client"].get(
            "/api/v1/import/batches?view=history&include_fixture=1",
            headers=env["h"]).json()
        assert bid in [b["batch_id"] for b in hist["batches"]]
        # 低权限用户显式请求也不得放行
        _mk_user(env, "low_user", "read_only")
        lg = env["client"].post(
            "/api/v1/auth/login",
            json={"username": "low_user", "password": USER_PW})
        lh = {"X-CSRF-Token": lg.json()["csrf_token"]}
        deny = env["client"].get(
            "/api/v1/import/batches?view=history&include_fixture=1",
            headers=lh)
        assert deny.status_code == 403 or \
            bid not in [b["batch_id"]
                        for b in deny.json().get("batches", [])]


# --------------------------------------------------------------------
# 19-20 BI effective / Test Center（OSV5-008）
# --------------------------------------------------------------------

class TestBiAndTestCenter:
    def test_r19_bi_effective_excludes_fixture_imports(self, env):
        _upload(env["client"], env["h"], "customers_v1",
                _cust_csv(f"{NS}_c1"), test_run_id=NS)
        from src.platform.analytics import bi_effective_counts
        conn = env["store"]._conn
        eff = bi_effective_counts(conn)
        total = conn.execute(
            "SELECT count(*) c FROM import_batch_v1").fetchone()["c"]
        assert eff["import_batch_v1"] == total - 1

    def test_r20_test_center_counts_import_batches(self, env):
        r = _upload(env["client"], env["h"], "customers_v1",
                    _cust_csv(f"{NS}_c1"), test_run_id=NS)
        summary = env["tds"].center_summary()
        run = next(t for t in summary["test_runs"]
                   if t["test_run_id"] == NS)
        assert run["objects"].get("import_batches", 0) >= 1


# --------------------------------------------------------------------
# 21 归档（OSV5-008）
# --------------------------------------------------------------------

class TestArchive:
    def test_r21_archive_import_batches_idempotent(self, env):
        r = _upload(env["client"], env["h"], "customers_v1",
                    _cust_csv(f"{NS}_c1"), test_run_id=NS)
        bid = r.json()["batch"]["batch_id"]
        env["tds"].archive_namespace(NS)
        row = env["store"]._conn.execute(
            "SELECT data_scope, COALESCE(visibility,'current') v,"
            " archived_at FROM import_batch_v1 WHERE batch_id=?",
            (bid,)).fetchone()
        assert row["data_scope"] == "uat_fixture"
        assert row["v"] == "history" and row["archived_at"]
        # 归档后批次不得再次提交
        rc = env["client"].post(f"/api/v1/import/batches/{bid}/commit",
                                headers=env["h"])
        assert rc.status_code == 409


# --------------------------------------------------------------------
# 22-28 可执行 Registry（OSV5-005/006）
# --------------------------------------------------------------------

class TestExecutableRegistry:
    def test_r22_registry_schema_validator_zero_errors(self, env):
        from src.platform.scope_registry import validate_registry
        problems = validate_registry(env["store"]._conn)
        assert problems == [], f"Registry 声明必须全部可执行: {problems[:8]}"

    def test_r23_registry_pk_declarations_real(self, env):
        from src.platform.scope_registry import SCOPE_REGISTRY
        conn = env["store"]._conn
        bad = []
        for t, e in SCOPE_REGISTRY.items():
            cols = {r[1] for r in conn.execute(
                f"PRAGMA table_info({t})")}
            pk = e.get("pk") or ""
            if pk and pk not in cols and not pk.startswith(
                    "composite:") and pk != "none":
                bad.append(f"{t}.{pk}")
        assert bad == [], bad[:8]

    def test_r24_registry_parent_edges_resolve(self, env):
        from src.platform.scope_registry import SCOPE_REGISTRY
        conn = env["store"]._conn
        bad = []
        for t, e in SCOPE_REGISTRY.items():
            p = e.get("parent") or ""
            if not p or "(" in p:
                continue
            try:
                pt, pcol = p.split(".")
            except ValueError:
                bad.append(f"{t}: parent 格式 {p}")
                continue
            pcols = {r[1] for r in conn.execute(
                f"PRAGMA table_info({pt})")}
            if pcol not in pcols:
                bad.append(f"{t} → {p}")
        assert bad == [], bad[:8]

    def test_r25_registry_archive_handlers_registered(self, env):
        from src.platform.scope_registry import archive_handler_for
        h = archive_handler_for("import_batch_v1")
        assert callable(h), "import_batch_v1 必须有可执行归档 handler"

    def test_r26_scanner_derived_detects_import_leak(self, env):
        conn = env["store"]._conn
        conn.execute(
            "INSERT INTO import_batch_v1 (batch_id, template_id,"
            " filename, file_format, file_hash, status, actor,"
            " row_count, mapping_json, dry_run_json,"
            " error_report_json, commit_json, created_at, updated_at,"
            " data_scope, test_run_id) VALUES"
            " ('imp-leak','customers_v1','x.csv','csv','h','uploaded',"
            " 'admin',0,'{}','{}','[]','{}','','','operational',"
            " 'some_test_run')")
        conn.commit()
        from src.platform.scope import ScopedQuery
        leak = ScopedQuery(env["store"]).operational_leakage()
        assert leak.get("import_batch_v1", 0) >= 1, \
            "scanner 必须由 Registry 派生并覆盖 import_batch_v1"

    def test_r27_archiver_table_set_derived_from_registry(self, env):
        from src.platform.scope_registry import archivable_tables
        from src.platform.test_data import _SCOPED_DOMAIN_TABLES
        tables = set(archivable_tables())
        assert "import_batch_v1" in tables
        # 平行清单必须收敛为 Registry 派生
        assert set(_SCOPED_DOMAIN_TABLES) <= tables

    def test_r28_unregistered_scoped_table_blocks_gate(self, env):
        conn = env["store"]._conn
        conn.execute(
            "CREATE TABLE osv5_unregistered_v1 (id TEXT PRIMARY KEY,"
            " data_scope TEXT, test_run_id TEXT)")
        conn.commit()
        from src.platform.scope_registry import registry_coverage
        cov = registry_coverage(conn)
        assert "osv5_unregistered_v1" in cov["missing"], \
            "新 scoped 表未登记必须被覆盖率对账捕获"


# --------------------------------------------------------------------
# 29-31 Gate 3.2（OSV5-009/010）
# --------------------------------------------------------------------

class TestGate32:
    def test_r29_gate_blocks_on_operational_fixture_import(self, env):
        conn = env["store"]._conn
        conn.execute(
            "INSERT INTO import_batch_v1 (batch_id, template_id,"
            " filename, file_format, file_hash, status, actor,"
            " row_count, mapping_json, dry_run_json,"
            " error_report_json, commit_json, created_at, updated_at,"
            " data_scope, test_run_id) VALUES"
            " ('imp-neg','customers_v1','x.csv','csv','h','uploaded',"
            " 'admin',0,'{}','{}','[]','{}','','','uat_fixture','')")
        conn.commit()
        from src.platform.gate_evaluator import \
            evaluate_gate_from_evidence
        res = evaluate_gate_from_evidence(store=env["store"])
        assert res["gate"] != "READY_FOR_REAL_DATA_UAT"
        names = [c["check"] for c in res["checks"] if not c["ok"]]
        assert any("import_batch" in n for n in names)

    def test_r30_evaluator_version_320(self, env):
        from src.platform.gate_evaluator import EVALUATOR_VERSION
        # OSV51：3.2.0 → 3.3.0；OSV52：→ 3.4.0（证据哈希实时重校验 +
        # Active Gate Registry）
        assert EVALUATOR_VERSION == "3.4.0"

    def test_r31_uatv7_validator_requires_import_ids(self, env):
        from scripts.uat_report_validator import validate_report
        rep = {"protocol": "uatv7", "namespace": "uatv7_x",
               "failed": 0, "checks": [], "ids": {"test_run": "x"}}
        problems = validate_report(rep)
        for k in ("import_batch_customer", "import_batch_project",
                  "import_batch_address", "import_scope_associations",
                  "import_evidence", "import_audit_events"):
            assert any(k in p for p in problems), \
                f"V7 validator 必须强制 ids.{k}"


# --------------------------------------------------------------------
# 32 Session 过期治理（OSV5-011）
# --------------------------------------------------------------------

class TestSessionCleanup:
    def test_r32_expired_sessions_cleaned_active_and_bill_kept(
            self, env):
        from datetime import datetime, timedelta, timezone
        store = env["store"]
        now = datetime.now(timezone.utc)
        past = (now - timedelta(hours=1)).isoformat()
        future = (now + timedelta(hours=6)).isoformat()
        store.create_auth_session(session_id="s-expired", actor="old1",
                                  role="operator", csrf_token="c1",
                                  created_at=past, expires_at=past)
        store.create_auth_session(session_id="s-active", actor="admin",
                                  role="admin", csrf_token="c2",
                                  created_at=past, expires_at=future)
        store.create_auth_session(session_id="s-bill", actor="bill",
                                  role="admin", csrf_token="c3",
                                  created_at=past, expires_at=future)
        from src.platform.auth import purge_expired_sessions
        removed = purge_expired_sessions(store)
        assert removed == 1
        ids = {r["session_id"] for r in store._conn.execute(
            "SELECT session_id FROM auth_sessions").fetchall()}
        assert "s-expired" not in ids
        assert {"s-active", "s-bill"} <= ids  # 环境自身的未过期
        # 会话（如 admin 登录）不受影响
