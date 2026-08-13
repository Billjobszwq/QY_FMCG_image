#!/usr/bin/env python3
"""OSV5 T6：Gate 3.2 负例账本（指令第八节）。任一负例成立 Gate 必须
非 READY。全部在临时库/临时 app 上机器执行，输出
.eval/scope_v5/gate_negative_tests.json。

负例清单：
 1 fixture import 被写成 operational
 2 fixture import 缺 test_run_id
 3 archived Test Run 被用于新导入
 4 read_only 读取其他客户批次
 5 read_only 提交其他客户批次
 6 DTO 泄漏 mapping_json
 7 Registry 声明不存在字段
 8 Registry 漏 archive handler
 9 新 scoped 表未被 scanner 消费
10 Browser 运营页显示 fixture（证据缺失/视图未分离）
11 BI 将 fixture import 计入运营
12 Gate evidence 使用旧 HEAD / 旧 DB fingerprint → STALE
13 OSV51 quarantine 批次执行逃逸（commit/dry-run 必须 409 + 零写入）
14 OSV51 隔离后被改写的 quarantine 批次 → Gate quarantine_execution_escape 拦截
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / ".eval" / "scope_v5" / "gate_negative_tests.json"

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.api.app import create_app
from src.platform.gate_evaluator import evaluate_gate_from_evidence
from src.platform.iam import IAMService
from src.platform.test_data import FixtureTestDataService

PW = "osv5-neg-pw"
NS = "uatv7_neg"
results: list[dict] = []


class _NoRec:
    def recognize(self, data, conf=0.25):
        return {"count": 0, "products": []}


def _mk(tmp: Path):
    bundle = build_production_bundle(
        db_path=tmp / "p.sqlite", cas_root=tmp / "cas",
        recognition_adapter=_NoRec(), probe=lambda spec: None)
    profiles = build_profiles_service(bundle)
    app = create_app(services=(), probe=lambda spec: None,
                     bundle=bundle, recognition_adapter=_NoRec(),
                     profiles_service=profiles,
                     web_dist=tmp / "none")
    return bundle, TestClient(app)


def _failed_checks(res: dict) -> list[str]:
    return [c["check"] for c in res["checks"] if not c["ok"]]


def _eval(store) -> dict:
    return evaluate_gate_from_evidence(store=store)


def neg(name: str, ok: bool, evidence: str) -> None:
    results.append({"negative": name, "blocked": ok,
                    "evidence": evidence[:300]})
    print(("PASS" if ok else "FAIL"), name, "|", evidence[:120])


def main() -> int:
    import os
    import tempfile
    os.environ["PLATFORM_ADMIN_PASSWORD"] = PW
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        bundle, client = _mk(tmp)
        store = bundle.store
        conn = store._conn
        r = client.post("/api/v1/auth/login",
                        json={"username": "admin", "password": PW})
        assert r.status_code == 200, r.text
        h = {"X-CSRF-Token": r.json()["csrf_token"]}
        iam = IAMService(store)
        tds = FixtureTestDataService(store)
        tds.create_test_run_context(NS, customer_ids=[])

        # 1) fixture import 写成 operational
        conn.execute(
            "INSERT INTO import_batch_v1 (batch_id, template_id,"
            " filename, file_format, file_hash, status, actor,"
            " row_count, mapping_json, dry_run_json, error_report_json,"
            " commit_json, created_at, updated_at, data_scope,"
            " test_run_id) VALUES ('neg1','customers_v1','n.csv','csv',"
            "'h','uploaded','x',0,'{}','{}','[]','{}','','',"
            "'uat_fixture','" + NS + "')")
        conn.execute(
            "UPDATE import_batch_v1 SET data_scope='operational'"
            " WHERE batch_id='neg1'")
        conn.commit()
        res = _eval(store)
        neg("fixture_import_written_operational",
            res["gate"] != "READY_FOR_REAL_DATA_UAT"
            and "import_batch_scope_complete" in _failed_checks(res),
            f"gate={res['gate']}")
        conn.execute("DELETE FROM import_batch_v1 WHERE batch_id='neg1'")
        conn.commit()

        # 2) fixture import 缺 test_run_id
        conn.execute(
            "INSERT INTO import_batch_v1 (batch_id, template_id,"
            " filename, file_format, file_hash, status, actor,"
            " row_count, mapping_json, dry_run_json, error_report_json,"
            " commit_json, created_at, updated_at, data_scope,"
            " test_run_id) VALUES ('neg2','customers_v1','n.csv','csv',"
            "'h','uploaded','x',0,'{}','{}','[]','{}','','',"
            "'uat_fixture','')")
        conn.commit()
        res = _eval(store)
        neg("fixture_import_missing_test_run",
            "import_batch_scope_complete" in _failed_checks(res),
            f"gate={res['gate']}")
        conn.execute("DELETE FROM import_batch_v1 WHERE batch_id='neg2'")
        conn.commit()

        # 3) archived Test Run 被用于新导入
        tds.archive_namespace(NS)
        up = client.post("/api/v1/import/upload", headers=h,
                         data={"template_id": "customers_v1",
                               "test_run_id": NS},
                         files={"file": ("f.csv", io.BytesIO(
                             b"customer_id,name\nx,Y\n"), "text/csv")})
        neg("archived_test_run_import_rejected", up.status_code == 409,
            f"status={up.status_code}")
        tds.create_test_run_context(NS, customer_ids=[])  # 恢复上下文

        # 4/5) read_only 跨客户读取/提交
        for cid in ("neg-cust-a", "neg-cust-b"):
            client.post("/api/v1/master/customers", headers=h,
                        json={"customer_id": cid, "name": cid})
        up = client.post("/api/v1/import/upload", headers=h,
                         data={"template_id": "stores_addresses_v1"},
                         files={"file": ("f.csv", io.BytesIO(
                             "customer_id,store_name,raw_address\n"
                             "neg-cust-a,店A,地址A\n".encode()),
                             "text/csv")})
        bid = up.json()["batch"]["batch_id"]
        client.post(f"/api/v1/import/batches/{bid}/dry-run", headers=h)
        iam.create_principal(kind="user", username="neg_low",
                             password="neg-pw-1", created_by="admin")
        iam.grant(username="neg_low", role="read_only",
                  granted_by="admin")
        lg = client.post("/api/v1/auth/login",
                         json={"username": "neg_low", "password":
                               "neg-pw-1"})
        lh = {"X-CSRF-Token": lg.json()["csrf_token"]}
        d = client.get(f"/api/v1/import/batches/{bid}", headers=lh)
        neg("readonly_cross_customer_detail_denied",
            d.status_code == 403, f"status={d.status_code}")
        cmm = client.post(f"/api/v1/import/batches/{bid}/commit",
                          headers=lh)
        neg("readonly_cross_customer_commit_denied",
            cmm.status_code == 403, f"status={cmm.status_code}")

        # 恢复 admin 会话（TestClient 共享 cookie，neg_low 登录已
        # 覆盖 platform_session）。
        r = client.post("/api/v1/auth/login",
                        json={"username": "admin", "password": PW})
        h = {"X-CSRF-Token": r.json()["csrf_token"]}

        # 6) DTO 泄漏 mapping_json
        dr = client.get(f"/api/v1/import/batches/{bid}", headers=h)
        assert dr.status_code == 200, f"detail {dr.status_code}: {dr.text[:200]}"
        dto = dr.json()["batch"]
        neg("dto_leaks_mapping_json",
            all(k not in dto for k in ("mapping_json", "dry_run_json",
                                       "error_report_json",
                                       "commit_json", "rows")),
            f"dto_keys={sorted(dto)[:8]}…")

        # 7) Registry 声明不存在字段
        from src.platform.scope_registry import (SCOPE_REGISTRY,
                                                 validate_registry)
        orig = SCOPE_REGISTRY["md_customer_v1"]["pk"]
        SCOPE_REGISTRY["md_customer_v1"]["pk"] = "no_such_column"
        probs = validate_registry(conn)
        SCOPE_REGISTRY["md_customer_v1"]["pk"] = orig
        neg("registry_fake_field_detected",
            any("no_such_column" in p for p in probs),
            f"problems={probs[:2]}")

        # 8) Registry 漏 archive handler
        from src.platform.scope_registry import ARCHIVE_HANDLERS
        saved = ARCHIVE_HANDLERS.pop("import_batch_v1")
        res = _eval(store)
        ARCHIVE_HANDLERS["import_batch_v1"] = saved
        neg("registry_missing_archive_handler_detected",
            "import_batch_archive_handler_registered" in
            _failed_checks(res), f"gate={res['gate']}")

        # 9) 新 scoped 表未被 scanner 消费
        conn.execute("CREATE TABLE neg_scoped_v1 (id TEXT PRIMARY KEY,"
                     " data_scope TEXT, test_run_id TEXT)")
        conn.commit()
        res = _eval(store)
        neg("new_scoped_table_unregistered_detected",
            "registry_runtime_scanner_complete" in _failed_checks(res),
            f"gate={res['gate']}")
        conn.execute("DROP TABLE neg_scoped_v1")
        conn.commit()

        # 10) Browser 运营页显示 fixture（视图未分离证据）
        res = evaluate_gate_from_evidence(
            store=store,
            browser_report_path=str(tmp / "brow.json"))
        neg("browser_fixture_surface_unverified",
            "browser_evidence_present" in _failed_checks(res)
            or "browser_import_current_history_separated" in
            _failed_checks(res), f"gate={res['gate']}")

        # 11) BI 将 fixture import 计入运营
        conn.execute(
            "INSERT INTO import_batch_v1 (batch_id, template_id,"
            " filename, file_format, file_hash, status, actor,"
            " row_count, mapping_json, dry_run_json, error_report_json,"
            " commit_json, created_at, updated_at, data_scope,"
            " test_run_id) VALUES ('neg11','customers_v1','n.csv',"
            "'csv','h','uploaded','x',0,'{}','{}','[]','{}','','',"
            "'operational','" + NS + "')")
        conn.commit()
        res = _eval(store)
        neg("bi_counts_fixture_import_operational",
            "import_batch_api_effective_consistent" in
            _failed_checks(res)
            or "import_batch_scope_complete" in _failed_checks(res),
            f"gate={res['gate']}")
        conn.execute("DELETE FROM import_batch_v1 WHERE batch_id='neg11'")
        conn.commit()

        # 12) Gate evidence 绑定旧 HEAD / 旧 DB fingerprint → STALE
        good = evaluate_gate_from_evidence(
            store=store, source_commit="x", current_head="y")
        neg("stale_head_binding_detected",
            good["gate"] == "STALE_GATE_EVIDENCE",
            f"gate={good['gate']}")

        # 13) OSV51 C-1：quarantine 批次执行逃逸——API 写路径必须 409
        conn.execute(
            "INSERT INTO import_batch_v1 (batch_id, template_id,"
            " filename, file_format, file_hash, status, actor,"
            " row_count, mapping_json, dry_run_json, error_report_json,"
            " commit_json, created_at, updated_at, data_scope,"
            " visibility, archived_at) VALUES ('neg13','customers_v1',"
            "'q.csv','csv','h','dry_run_passed','admin',0,"
            "'{\"rows\": []}','{}','[]','{}',"
            "'2026-08-11T00:00:00+00:00','2026-08-11T00:00:00+00:00',"
            "'quarantine','current','2026-08-13T05:28:36+00:00')")
        conn.commit()
        before_cust = conn.execute(
            "SELECT count(*) c FROM md_customer_v1").fetchone()["c"]
        rcm = client.post("/api/v1/import/batches/neg13/commit",
                          headers=h)
        rdm = client.post("/api/v1/import/batches/neg13/dry-run",
                          headers=h)
        after_cust = conn.execute(
            "SELECT count(*) c FROM md_customer_v1").fetchone()["c"]
        code = "IMPORT_BATCH_WRITE_BLOCKED"
        neg("quarantine_execution_escape",
            rcm.status_code == 409 and rdm.status_code == 409
            and code in str(rcm.json().get("detail", ""))
            and code in str(rdm.json().get("detail", ""))
            and after_cust == before_cust,
            f"commit={rcm.status_code} dry_run={rdm.status_code}"
            f" writes={after_cust - before_cust}")
        # 14) OSV51 C-1：隔离后被改写的 quarantine 批次 → Gate 必须拦
        conn.execute(
            "UPDATE import_batch_v1 SET"
            " updated_at='2026-08-13T08:07:41+00:00'"
            " WHERE batch_id='neg13'")
        conn.commit()
        res = _eval(store)
        neg("quarantine_post_isolation_mutation_detected",
            "quarantine_execution_escape" in _failed_checks(res)
            and res["gate"] != "READY_FOR_REAL_DATA_UAT",
            f"gate={res['gate']}")
        conn.execute("DELETE FROM import_batch_v1"
                     " WHERE batch_id='neg13'")
        conn.commit()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"gate_negative_tests": results,
         "all_blocked": all(r["blocked"] for r in results)},
        ensure_ascii=False, indent=2), encoding="utf-8")
    ok = all(r["blocked"] for r in results)
    print("ALL_BLOCKED:", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
