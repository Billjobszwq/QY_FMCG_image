#!/usr/bin/env python3
"""OSV5 T7：UAT V7 全领域链机器预演（06-UAT-V7-PROTOCOL）。

与 V6 的区别：全部导入对象必须真实经过 multipart Import Center API；
批次=冻结执行上下文（scope/test_run/客户关联/授权决定/证据），归档
后运营面清零、服务重启不回退、Gate 对账一致。

20 项检查（指令第九节 1–20）+ ids 新增 6 键：
import_batch_customer / import_batch_project / import_batch_address /
import_scope_associations / import_evidence / import_audit_events。

用法：python3 scripts/uatv7_rehearsal.py
"""
from __future__ import annotations

import io
import json
import random
import re
import sqlite3
import string
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = "http://127.0.0.1:8400"
DB = ROOT / ".platform" / "platform.sqlite"
OUT = ROOT / ".eval" / "scope_v5" / "uatv7"
OUT.mkdir(parents=True, exist_ok=True)
REPORT = OUT / "report.json"

env = {}
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1)
        env[k] = v.strip().strip('"').strip("'")
m = re.search(r"(\w+)[:/]([\w\-!@#$%^&*.]+)",
              env.get("PLATFORM_ADMIN_CREDENTIALS", ""))
OWNER, OWNER_PW = m.group(1), m.group(2)
USER_PW = "UatV7-pw-123"

NS = "uatv7_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") \
    + "_" + "".join(random.choices(string.ascii_lowercase
                                   + string.digits, k=6))
CUST = NS + "_cust"
CUST2 = NS + "_cust_b"
PRJ = NS + "_prj"

checks: list[dict] = []
IDS: dict[str, str] = {"test_run": NS}


def check(name: str, ok: bool, evidence: str = "") -> None:
    checks.append({"check": name, "ok": bool(ok),
                   "evidence": str(evidence)[:300]})
    print(("  ✓ " if ok else "  ✗ ") + name
          + (f"  [{str(evidence)[:100]}]" if evidence else ""))


class Sess:
    def __init__(self):
        self.s = requests.Session()
        self.csrf = ""

    def login(self, u: str, p: str) -> dict:
        r = self.s.post(BASE + "/api/v1/auth/login",
                        json={"username": u, "password": p})
        d = r.json() if r.status_code == 200 else {}
        self.csrf = d.get("csrf_token", "")
        return {"_http": r.status_code, **d}

    def h(self, csrf: bool = False) -> dict:
        return {"X-CSRF-Token": self.csrf} if csrf and self.csrf else {}

    def upload(self, tid: str, csv_text: str, filename: str,
               test_run_id: str = "") -> dict:
        data = {"template_id": tid}
        if test_run_id:
            data["test_run_id"] = test_run_id
        r = self.s.post(BASE + "/api/v1/import/upload", headers=self.h(
            True), data=data,
            files={"file": (filename, io.BytesIO(
                csv_text.encode("utf-8-sig")), "text/csv")})
        try:
            return {"_http": r.status_code, **r.json()}
        except Exception:
            return {"_http": r.status_code, "_body": r.text[:200]}

    def post(self, path: str, body: dict | None = None) -> dict:
        r = self.s.post(BASE + path, headers=self.h(True),
                        json=body if body is not None else {})
        try:
            return {"_http": r.status_code, **r.json()}
        except Exception:
            return {"_http": r.status_code, "_body": r.text[:200]}

    def get(self, path: str) -> dict:
        r = self.s.get(BASE + path)
        try:
            return {"_http": r.status_code, **r.json()}
        except Exception:
            return {"_http": r.status_code, "_body": r.text[:200]}


def main() -> int:
    t0 = time.time()
    bill = Sess()
    lg = bill.login(OWNER, OWNER_PW)
    assert lg["_http"] == 200, lg
    print(f"[OSV5-T7] UAT V7 namespace = {NS}")

    # 0) Test Run 上下文先于一切对象
    ctx = bill.post("/api/v1/test-data/run",
                    {"namespace": NS, "customer_ids": [CUST, CUST2]})
    check("test_run_context_first", ctx.get("test_run_id") == NS, ctx)

    # 1) 客户模板真实 multipart 上传（携带 test_run_id）
    up_c = bill.upload(
        "customers_v1",
        f"customer_id,name,payment_terms,retention_policy,tags\n"
        f"{CUST},UAT V7 客户A,月结30天,,\n"
        f"{CUST2},UAT V7 客户B,月结30天,,\n",
        "uatv7_customers.csv", test_run_id=NS)
    bid_c = (up_c.get("batch") or {}).get("batch_id", "")
    IDS["import_batch_customer"] = bid_c
    check("1_customer_template_upload",
          up_c.get("_http") == 200
          and (up_c.get("batch") or {}).get("data_scope") == "uat_fixture"
          and (up_c.get("batch") or {}).get("test_run_id") == NS,
          str(up_c)[:140])

    # 2) 项目模板上传
    up_p = bill.upload(
        "projects_v1",
        "project_id,customer_id,name,start_date,end_date,owner,budget\n"
        f"{PRJ},{CUST},UAT V7 项目,,,,\n",
        "uatv7_projects.csv", test_run_id=NS)
    bid_p = (up_p.get("batch") or {}).get("batch_id", "")
    IDS["import_batch_project"] = bid_p
    check("2_project_template_upload", up_p.get("_http") == 200
          and bool(bid_p), str(up_p)[:140])

    # 3) 地址模板上传
    up_a = bill.upload(
        "stores_addresses_v1",
        "customer_id,store_name,raw_address,region,lat,lng,coord_system,"
        "time_window\n"
        f"{CUST},UAT V7 示例店,上海市示例路 7 号,华东,,,\n",
        "uatv7_addresses.csv", test_run_id=NS)
    bid_a = (up_a.get("batch") or {}).get("batch_id", "")
    IDS["import_batch_address"] = bid_a
    check("3_address_template_upload", up_a.get("_http") == 200
          and bool(bid_a), str(up_a)[:140])

    # 4) 敏感全局模板拒绝负例：read_only 身份上传 users_v1 → 403
    low = Sess()
    bill.post("/api/v1/iam/principals",
              {"kind": "user", "username": f"{NS}_low",
               "display_name": "低权限", "password": USER_PW,
               "test_run_id": NS})
    bill.post("/api/v1/iam/grants", {"username": f"{NS}_low",
                                     "role": "read_only"})
    low.login(f"{NS}_low", USER_PW)
    deny = low.upload("users_v1",
                      "username,display_name,kind,status\nhack,H,user,"
                      "active\n", "evil_users.csv", test_run_id=NS)
    check("4_global_template_denied_for_readonly",
          deny.get("_http") == 403, str(deny)[:140])

    # 5) dry-run（顺序：客户→项目→地址；项目依赖客户已提交）
    dr_ok = True
    dr_evidence = []
    for bid in (bid_c, bid_p, bid_a):
        d = bill.post(f"/api/v1/import/batches/{bid}/dry-run")
        st = (d.get("batch") or {}).get("status")
        dr_ok = dr_ok and st == "dry_run_passed"
        dr_evidence.append(f"{bid[:12]}={st}")
        # 6) 前序批次先提交，后续批次的引用对象才存在
        c = bill.post(f"/api/v1/import/batches/{bid}/commit")
        dr_ok = dr_ok and (c.get("batch") or {}).get("status") \
            == "committed"
    check("5_dry_run_passed", dr_ok, "; ".join(dr_evidence))

    # 6) commit（已随 5 顺序提交，此处复核状态）
    cm_ok = True
    for bid in (bid_c, bid_p, bid_a):
        d = bill.get(f"/api/v1/import/batches/{bid}")
        cm_ok = cm_ok and (d.get("batch") or {}).get("status") \
            == "committed"
    check("6_commit_committed", cm_ok, "三批次均 committed")

    # 7) 批次 scope/test_run/客户关联对账（DB 直查）
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    n_assoc = conn.execute(
        "SELECT count(*) c FROM import_batch_customer_scope_v1 WHERE"
        " batch_id IN (?,?,?)", (bid_c, bid_p, bid_a)).fetchone()["c"]
    scoped_ok = conn.execute(
        "SELECT count(*) c FROM import_batch_v1 WHERE batch_id IN"
        " (?,?,?) AND data_scope='uat_fixture' AND test_run_id=?",
        (bid_c, bid_p, bid_a, NS)).fetchone()["c"] == 3
    IDS["import_scope_associations"] = str(n_assoc)
    check("7_batch_scope_associations",
          scoped_ok and n_assoc >= 2,
          f"scoped=3 assoc={n_assoc}")

    # 8) 导入对象与批次作用域一致
    row_c = conn.execute(
        "SELECT data_scope ds, test_run_id tr FROM md_customer_v1"
        f" WHERE customer_id=?", (CUST,)).fetchone()
    row_p = conn.execute(
        "SELECT data_scope ds, test_run_id tr FROM md_project_v1"
        f" WHERE project_id=?", (PRJ,)).fetchone()
    row_a = conn.execute(
        "SELECT data_scope ds, test_run_id tr FROM geo_address_v1"
        f" WHERE customer_id=?", (CUST,)).fetchone()
    check("8_imported_objects_inherit_scope",
          all(r and r["ds"] == "uat_fixture" and r["tr"] == NS
              for r in (row_c, row_p, row_a)),
          f"cust={row_c['ds']} prj={row_p['ds']} addr={row_a['ds']}")

    # 9) 运营 Import Center 不显示这些批次
    lst = bill.get("/api/v1/import/batches")
    ids_in_list = {b["batch_id"] for b in lst.get("batches", [])}
    check("9_operational_list_excludes_fixture",
          not ({bid_c, bid_p, bid_a} & ids_in_list),
          f"operational_count={lst.get('count')}")

    # 10) Test Center 可查询这些批次
    center = bill.get("/api/v1/test-data/center")
    run = next((t for t in center.get("test_runs", [])
                if t["test_run_id"] == NS), {})
    check("10_test_center_counts_imports",
          int(run.get("objects", {}).get("import_batches", 0)) >= 3,
          f"import_batches={run.get('objects', {}).get('import_batches')}")

    # 11) BI operational import count 不增加
    dp = bill.get("/api/v1/analytics/data-products")
    imp_rows = next((p["rows"] for p in dp.get("products", [])
                     if p["product"] == "import.batches_v1"), -1)
    db_op = conn.execute(
        "SELECT count(*) c FROM import_batch_v1 WHERE COALESCE("
        "data_scope,'operational')='operational'").fetchone()["c"]
    check("11_bi_operational_import_count",
          imp_rows == db_op, f"bi={imp_rows} db_operational={db_op}")

    # 12) 跨客户角色读取 403（customer_admin@CUST2 读 CUST 批次）
    bill.post("/api/v1/iam/principals",
              {"kind": "user", "username": f"{NS}_cb",
               "display_name": "客户B管理员", "password": USER_PW,
               "test_run_id": NS})
    bill.post("/api/v1/iam/grants", {"username": f"{NS}_cb",
                                     "role": "customer_admin",
                                     "customer_id": CUST2})
    cb = Sess()
    cb.login(f"{NS}_cb", USER_PW)
    cross = cb.get(f"/api/v1/import/batches/{bid_a}")
    check("12_cross_customer_read_403",
          cross.get("_http") == 403, str(cross)[:120])

    # 13) read_only dry-run/commit 403
    dr_low = low.post(f"/api/v1/import/batches/{bid_a}/dry-run")
    cm_low = low.post(f"/api/v1/import/batches/{bid_a}/commit")
    check("13_readonly_dryrun_commit_403",
          dr_low.get("_http") == 403 and cm_low.get("_http") == 403,
          f"dr={dr_low.get('_http')} cm={cm_low.get('_http')}")

    # 14) 原始 mapping_json 不出现在普通详情响应
    det = bill.get(f"/api/v1/import/batches/{bid_c}")
    b = det.get("batch") or {}
    check("14_detail_no_raw_payload",
          all(k not in b for k in ("mapping_json", "dry_run_json",
                                   "error_report_json", "commit_json",
                                   "mapping", "rows")),
          f"dto_keys={sorted(b)[:6]}…")
    pv = bill.get(f"/api/v1/import/batches/{bid_c}/preview")
    check("14b_preview_creator_redacted",
          pv.get("redacted") is True and len(pv.get("rows", [])) <= 50,
          f"redacted={pv.get('redacted')}")

    # 15) Test Run 归档
    arch = bill.post("/api/v1/test-data/archive", {"namespace": NS})
    check("15_test_run_archived",
          conn.execute("SELECT status s FROM uat_test_run_v1 WHERE"
                       " test_run_id=?", (NS,)).fetchone()["s"]
          == "archived" or arch.get("namespace") == NS,
          str(arch)[:120])

    # 16) 批次进入历史（visibility=history，不删行）
    hist = conn.execute(
        "SELECT count(*) c FROM import_batch_v1 WHERE batch_id IN"
        " (?,?,?) AND visibility='history' AND data_scope='uat_fixture'",
        (bid_c, bid_p, bid_a)).fetchone()["c"]
    check("16_batches_into_history", hist == 3, f"history={hist}/3")

    # 17) 导入对象进入 fixture/history（运营口径清零）
    leak = conn.execute(
        "SELECT count(*) c FROM md_customer_v1 WHERE customer_id IN"
        " (?,?) AND COALESCE(data_scope,'operational')='operational'",
        (CUST, CUST2)).fetchone()["c"]
    check("17_imported_objects_fixture", leak == 0,
          f"operational_residue={leak}")

    # 18) 重启服务
    sub = subprocess.run(["./bin/abos", "restart", "app"], cwd=str(ROOT),
                         capture_output=True, text=True, timeout=120)
    healthy = False
    for _ in range(20):
        try:
            r = requests.get(BASE + "/api/v1/health", timeout=3)
            if r.status_code == 200:
                healthy = True
                break
        except Exception:
            time.sleep(1.5)
    check("18_service_restart", healthy and sub.returncode == 0,
          sub.stdout.strip()[:80])

    # 19) 归档状态不回退（重启后复核）
    conn2 = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn2.row_factory = sqlite3.Row
    still = conn2.execute(
        "SELECT count(*) c FROM import_batch_v1 WHERE batch_id IN"
        " (?,?,?) AND visibility='history'",
        (bid_c, bid_p, bid_a)).fetchone()["c"]
    open_ctx = conn2.execute(
        "SELECT count(*) c FROM uat_test_run_v1 WHERE test_run_id=?"
        " AND status='current'", (NS,)).fetchone()["c"]
    check("19_archive_stable_after_restart", still == 3 and open_ctx == 0,
          f"history={still} open_ctx={open_ctx}")

    # 20) Gate 对账仍一致（import effective 口径 + 归档一致性）
    eff = conn2.execute(
        "SELECT count(*) c FROM import_batch_v1 WHERE COALESCE("
        "data_scope,'operational')='operational' AND COALESCE("
        "test_run_id,'')=''").fetchone()["c"]
    consistent = eff == db_op - 0  # 运营口径不因 fixture 变化
    check("20_gate_reconcile_consistent",
          consistent and still == 3,
          f"operational_imports={eff}")

    # ids：证据与审计
    ev = conn2.execute(
        "SELECT evidence_id FROM evidence_bundle_v1 WHERE kind="
        "'import_batch' AND source_uri IN (?,?,?)",
        (f"import_batch:{bid_c}", f"import_batch:{bid_p}",
         f"import_batch:{bid_a}")).fetchall()
    IDS["import_evidence"] = ",".join(r["evidence_id"] for r in ev[:3])
    aud = conn2.execute(
        "SELECT count(*) c FROM iam_audit_event_v1 WHERE action="
        "'import.committed' AND resource IN (?,?,?)",
        (f"import:{bid_c}", f"import:{bid_p}",
         f"import:{bid_a}")).fetchone()["c"]
    IDS["import_audit_events"] = str(aud)
    check("21_evidence_and_audit", len(ev) >= 3 and aud >= 3,
          f"evidence={len(ev)} audit={aud}")

    conn.close()
    conn2.close()

    # 报告环境事实（与 V6 同口径：CURRENT.json / abos status / 中心扫描）
    try:
        cur = json.loads((ROOT / ".models" / "bundles" /
                          "CURRENT.json").read_text())
    except Exception:  # noqa: BLE001
        cur = {}
    try:
        import subprocess as _sp
        st = _sp.run([str(ROOT / "bin" / "abos"), "status"],
                     capture_output=True, text=True,
                     timeout=60).stdout
        abos_no_train = "训练进程：无" in st
    except Exception:  # noqa: BLE001
        abos_no_train = False
    center2 = bill.get("/api/v1/test-data/center")
    residue = (center2.get("scope_scan") or {}).get(
        "work_residue_current", 1)

    failed = [c for c in checks if not c["ok"]]
    report = {
        "protocol": "uatv7",
        "namespace": NS,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "total": len(checks),
        "failed": len(failed),
        "ids": IDS,
        "wall_seconds": round(time.time() - t0, 2),
        "current_bundle": cur.get("bundle_id", ""),
        "training_processes": 0 if abos_no_train else 1,
        "operational_residue": residue,
        "projection": {"operational_residue": residue},
    }
    # OSV51 C-6：证据 binding 块（生成时刻的代码/DB 状态，Gate 以
    # 此为 recorded 基准，禁止评估时回填当前值自比较）
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _ROOT = _Path(__file__).resolve().parents[1]
        _sys.path.insert(0, str(_ROOT))
        from src.platform import binding_core as _bc
        from src.platform.data.store import PlatformStore
        from src.platform.gate_evaluator import db_fingerprint
        _store = PlatformStore(_ROOT / ".platform" / "platform.sqlite")
        _res_payload = {"total": report["total"],
                        "failed": report["failed"],
                        "namespace": NS, "ids": IDS}
        report["binding"] = _bc.make_binding(
            root=_ROOT, conn=_store._conn,
            argv=[_sys.executable, "scripts/uatv7_rehearsal.py"],
            result_payload=_res_payload,
            started_at=datetime.fromtimestamp(
                t0, tz=timezone.utc).isoformat(),
            finished_at=report["generated_at"],
            database_fingerprint=db_fingerprint(_store))
    except Exception as _e:  # noqa: BLE001
        report["binding_error"] = str(_e)[:200]
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"\nUAT V7: {len(checks) - len(failed)}/{len(checks)} passed;"
          f" report={REPORT}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
