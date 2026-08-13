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
15 OSV51 批次 JSON 列嵌套明文密码 → Gate recursive_secret_scan 拦截
16 OSV51 quarantine 批次可归因的 operational 对象写入 →
   Gate quarantine_no_operational_writes 拦截
17 OSV51 证据缺 binding 块 → Gate 不得 READY（missing_binding）
18-20 OSV51 代码/DB/前端变化后不重跑测试/UAT/浏览器证据 → STALE
21 OSV51 自比较注入（recorded==current 且证据无 binding）→ 不得放行
"""
from __future__ import annotations

import hashlib
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
    from datetime import datetime, timezone
    started_at = datetime.now(timezone.utc).isoformat()
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

        # 15) OSV51 C-2：递归 secret 扫描——嵌套明文密码必须被 Gate 拦
        conn.execute(
            "INSERT INTO import_batch_v1 (batch_id, template_id,"
            " filename, file_format, file_hash, status, actor,"
            " row_count, mapping_json, dry_run_json, error_report_json,"
            " commit_json, created_at, updated_at, data_scope)"
            " VALUES ('neg15','users_v1','s.csv','csv','h','committed',"
            "'admin',1,'{}','{}','[]',"
            "'{\"receipts\":[{\"username\":\"u\",\"nested\":"
            "{\"initial_password_once\":\"Init-leak\"}}]}',"
            "'','' ,'operational')")
        conn.commit()
        res = _eval(store)
        neg("recursive_secret_scan",
            "recursive_secret_scan" in _failed_checks(res)
            and res["gate"] != "READY_FOR_REAL_DATA_UAT",
            f"gate={res['gate']}")
        conn.execute("DELETE FROM import_batch_v1"
                     " WHERE batch_id='neg15'")
        conn.commit()

        # 16) OSV51 W2-a：quarantine 批次可归因的 operational 对象写入
        #     → Gate quarantine_no_operational_writes 必须拦（C-1 §8）
        client.post("/api/v1/master/customers", headers=h,
                    json={"customer_id": "neg16-cust", "name": "逃逸客户"})
        conn.execute(
            "INSERT INTO import_batch_v1 (batch_id, template_id,"
            " filename, file_format, file_hash, status, actor,"
            " row_count, mapping_json, dry_run_json, error_report_json,"
            " commit_json, created_at, updated_at, data_scope,"
            " visibility, archived_at) VALUES ('neg16','customers_v1',"
            "'q.csv','csv','h','committed','admin',1,"
            "'{\"header\": [\"customer_id\"],"
            " \"rows\": [[\"neg16-cust\"]]}','{}','[]','{}',"
            "'2026-08-11T00:00:00+00:00','2026-08-11T00:00:00+00:00',"
            "'quarantine','current','2026-08-13T05:28:36+00:00')")
        conn.commit()
        res = _eval(store)
        neg("quarantine_operational_object_write_detected",
            "quarantine_no_operational_writes" in _failed_checks(res)
            and res["gate"] != "READY_FOR_REAL_DATA_UAT",
            f"gate={res['gate']}")
        conn.execute("DELETE FROM import_batch_v1"
                     " WHERE batch_id='neg16'")
        conn.execute("DELETE FROM md_customer_v1"
                     " WHERE customer_id='neg16-cust'")
        conn.commit()

        # 17) OSV51 C-6：证据缺 binding 块 → 不得 READY
        res = evaluate_gate_from_evidence(
            store=store, evidence_bindings={
                "uat": None, "test": None, "browser": None,
                "negative": None})
        bad = _failed_checks(res)
        neg("missing_binding_detected",
            all(f"{k}_evidence_binding_fresh" in bad
                for k in ("uat", "test", "browser", "negative"))
            and res["gate"] != "READY_FOR_REAL_DATA_UAT",
            f"gate={res['gate']}")

        # 18-20) OSV51 C-6：代码/DB/前端变化后不重跑对应证据 → STALE
        from src.platform import binding_core as _bc
        cur_tree = _bc.tree_hash(ROOT)
        cur_head = _bc.git_head(ROOT) or "x"
        cur_mig = _bc.migration_hash(conn)
        res = evaluate_gate_from_evidence(
            store=store, current_head=cur_head,
            current_tree_hash=cur_tree,
            current_migration_hash=cur_mig,
            evidence_bindings={"test": {
                "source_commit": cur_head,
                "code_tree_hash": "stale0stale0stale0",
                "migration_hash": cur_mig}})
        neg("stale_code_without_rerun_tests",
            res["gate"] == "STALE_GATE_EVIDENCE",
            f"gate={res['gate']}")
        from src.platform.gate_evaluator import db_fingerprint
        fp = db_fingerprint(store)
        stale_fp = dict(fp)
        stale_fp["event_watermark"] = int(fp.get("event_watermark",
                                                  0)) + 999
        res = evaluate_gate_from_evidence(
            store=store, current_head=cur_head,
            current_tree_hash=cur_tree,
            current_migration_hash=cur_mig,
            evidence_bindings={"uat": {
                "source_commit": cur_head,
                "code_tree_hash": cur_tree,
                "migration_hash": cur_mig,
                "database_fingerprint": stale_fp}})
        neg("stale_db_without_rerun_uat",
            res["gate"] == "STALE_GATE_EVIDENCE",
            f"gate={res['gate']}")
        res = evaluate_gate_from_evidence(
            store=store, current_head=cur_head,
            current_tree_hash=cur_tree,
            current_migration_hash=cur_mig,
            evidence_bindings={"browser": {
                "source_commit": cur_head,
                "code_tree_hash": "stale1stale1stale1",
                "migration_hash": cur_mig}})
        neg("stale_frontend_without_rerun_browser",
            res["gate"] == "STALE_GATE_EVIDENCE",
            f"gate={res['gate']}")

        # 21) OSV51 C-6：自比较注入——recorded==current 但证据无
        # binding 块时不得放行（旧行为是恒真）
        res = evaluate_gate_from_evidence(
            store=store, source_commit=cur_head, current_head=cur_head,
            recorded_tree_hash=cur_tree, current_tree_hash=cur_tree,
            recorded_migration_hash=cur_mig,
            current_migration_hash=cur_mig,
            evidence_bindings={"uat": None, "test": None,
                               "browser": None, "negative": None})
        neg("self_compare_injection_still_blocked",
            res["gate"] != "READY_FOR_REAL_DATA_UAT",
            f"gate={res['gate']}")

        # ---- OSV52 负例 22-27：证据文件篡改必须被实时 freshness
        # 复评（与 live /api/v1/control/gate 同一代码路径）阻断 ----
        from src.platform import binding_core as _bc3
        from src.platform.gate_evaluator import (
            BLOCKED_HASH_DRIFT, _result_payload_for)
        evdir = tmp / "osv52_ev"
        evdir.mkdir(exist_ok=True)

        def _mk_ev(name, kind, payload, head):
            d = dict(payload)
            rp = _result_payload_for(kind, payload)
            d["binding"] = {"source_commit": head,
                            "code_tree_hash": "",
                            "migration_hash": "",
                            "result_hash": _bc3.result_hash(rp)
                            if rp is not None else ""}
            p = evdir / name
            p.write_text(json.dumps(d, ensure_ascii=False),
                         encoding="utf-8")
            return p

        def _mk_gate(manifest, head):
            gp = evdir / "gate.json"
            gp.write_text(json.dumps({
                "gate": "READY_FOR_REAL_DATA_UAT", "reasons": [],
                "checks": [], "evidence_hashes": {},
                "evaluator_version": "3.4.0", "source_commit": head,
                "code_tree_hash": "", "migration_hash": "",
                "db_fingerprint": db_fingerprint(store),
                "evidence_manifest": manifest}), encoding="utf-8")
            return gp

        def _man(files):
            return {k: {"path": str(p),
                        "sha256": hashlib.sha256(
                            p.read_bytes()).hexdigest(),
                        "size": p.stat().st_size,
                        "generated_at": "2026-08-14T00:00:00+00:00"}
                    for k, p in files.items()}

        def _fresh2(gate_path):
            return evaluate_gate_from_evidence(
                store=store, recorded_gate_path=gate_path,
                current_head=cur_head,
                evidence_root=evdir)

        cur_head = _bc.git_head(ROOT) or "hcur"
        base_files = {
            "uat_report": _mk_ev("uat.json", "uat_report",
                                 {"protocol": "uatv7", "total": 23,
                                  "failed": 0, "namespace": "ns",
                                  "ids": {}}, cur_head),
            "test_report": _mk_ev("test.json", "test_report",
                                  {"suite": "hermetic", "failed": 0,
                                   "passed": 1, "skipped": 0,
                                   "deselected": 0,
                                   "marker": "not host_mps",
                                   "generated_by": "x"}, cur_head),
            "browser_report": _mk_ev("browser.json", "browser_report",
                                     {"pages": [],
                                      "browser_test_run": "nsb"},
                                     cur_head),
            "negative_report": _mk_ev("negative.json",
                                      "negative_report",
                                      {"gate_negative_tests": [],
                                       "all_blocked": True}, cur_head),
        }
        led = evdir / "ISSUES.md"
        led.write_text("# none\n", encoding="utf-8")
        base_files["issue_ledger"] = led
        base = _mk_gate(_man(base_files), cur_head)
        base_res = _fresh2(base)
        base_ok = base_res["gate"] == "READY_FOR_REAL_DATA_UAT"

        def _restore_base():
            # 从载荷重建全部基线证据（上一次篡改可能删除/替换文件）
            base_files["uat_report"] = _mk_ev(
                "uat.json", "uat_report",
                {"protocol": "uatv7", "total": 23, "failed": 0,
                 "namespace": "ns", "ids": {}}, cur_head)
            base_files["test_report"] = _mk_ev(
                "test.json", "test_report",
                {"suite": "hermetic", "failed": 0, "passed": 1,
                 "skipped": 0, "deselected": 0,
                 "marker": "not host_mps", "generated_by": "x"},
                cur_head)
            base_files["browser_report"] = _mk_ev(
                "browser.json", "browser_report",
                {"pages": [], "browser_test_run": "nsb"}, cur_head)
            base_files["negative_report"] = _mk_ev(
                "negative.json", "negative_report",
                {"gate_negative_tests": [], "all_blocked": True},
                cur_head)
            led.write_text("# none\n", encoding="utf-8")
            link = evdir / "neg_link.json"
            if link.is_symlink() or link.exists():
                link.unlink()
            _mk_gate(_man(base_files), cur_head)

        def _tamper_reset(mutate):
            _restore_base()
            mutate()

        if base_ok:
            _tamper_reset(lambda: base_files["negative_report"]
                          .write_text(json.dumps(
                              {"gate_negative_tests": [],
                               "all_blocked": True, "x": 1}),
                              encoding="utf-8"))
            neg("tamper_rewrite_negative_report_after_gate",
                _fresh2(base)["gate"] == BLOCKED_HASH_DRIFT,
                f"gate={_fresh2(base)['gate']}")
            _tamper_reset(lambda: base_files["test_report"]
                          .write_text(json.dumps(
                              {"suite": "hermetic", "failed": 0,
                               "passed": 999999}), encoding="utf-8"))
            neg("tamper_rewrite_test_report_after_gate",
                _fresh2(base)["gate"] == BLOCKED_HASH_DRIFT,
                f"gate={_fresh2(base)['gate']}")
            _tamper_reset(lambda: base_files["browser_report"]
                          .write_bytes(b'{"pages":[1,2,3]}'))
            neg("tamper_replace_browser_evidence_after_gate",
                _fresh2(base)["gate"] == BLOCKED_HASH_DRIFT,
                f"gate={_fresh2(base)['gate']}")
            _tamper_reset(lambda: base_files["uat_report"].unlink())
            neg("tamper_delete_uat_report_after_gate",
                _fresh2(base)["gate"] == "STALE_GATE_EVIDENCE",
                f"gate={_fresh2(base)['gate']}")

            def _keep_binding_tamper_body():
                p = base_files["negative_report"]
                d = json.loads(p.read_text(encoding="utf-8"))
                d["all_blocked"] = False
                p.write_text(json.dumps(d, ensure_ascii=False),
                             encoding="utf-8")
            _tamper_reset(_keep_binding_tamper_body)
            neg("tamper_body_keep_binding_after_gate",
                _fresh2(base)["gate"] == BLOCKED_HASH_DRIFT,
                f"gate={_fresh2(base)['gate']}")

            def _symlink_escape():
                outside = tmp / "outside_ev.json"
                outside.write_text(
                    base_files["negative_report"].read_text(),
                    encoding="utf-8")
                link = evdir / "neg_link.json"
                try:
                    import os as _os
                    if link.exists() or link.is_symlink():
                        link.unlink()
                    _os.symlink(outside, link)
                    man = _man(base_files)
                    man["negative_report"] = {
                        "path": str(link),
                        "sha256": hashlib.sha256(
                            link.read_bytes()).hexdigest(),
                        "size": link.stat().st_size,
                        "generated_at": "2026-08-14T00:00:00+00:00"}
                    _mk_gate(man, cur_head)
                except OSError:
                    pass
            _tamper_reset(_symlink_escape)
            neg("tamper_symlink_escape_evidence_path",
                _fresh2(base)["gate"] != "READY_FOR_REAL_DATA_UAT",
                f"gate={_fresh2(base)['gate']}")
        else:
            neg("tamper_base_state_setup", False,
                f"基线构造失败 gate={base_res['gate']}")

    from datetime import datetime as _dt, timezone as _tz
    from src.platform import binding_core as _bc2
    finished_at = _dt.now(_tz.utc).isoformat()
    payload = {"gate_negative_tests": results,
               "all_blocked": all(r["blocked"] for r in results)}
    # 负例账本为 hermetic（临时库）产物：binding 只绑代码状态，不绑
    # database_fingerprint（临时库指纹与 live 库不可比；评估器对缺失
    # 指纹跳过 DB 比对）。
    payload["binding"] = _bc2.make_binding(
        root=ROOT, conn=conn,
        argv=[sys.executable, "scripts/osv5_gate_negative.py"],
        result_payload={"all_blocked": payload["all_blocked"],
                        "count": len(results)},
        started_at=started_at, finished_at=finished_at)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    ok = all(r["blocked"] for r in results)
    print("ALL_BLOCKED:", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
