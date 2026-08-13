#!/usr/bin/env python3
"""OSV5 T0：开工现场只读复现（before 态证据，不得修改任何数据）。

复现指令第四节全部问题的机器证据：
- P0-001 import_batch_v1 20 条 UAT 批次污染运营面（SQL + API + BI）；
- P0-002 upload 链无 test_run_id（静态签名事实）；
- P0-005/P0-006 Scope Registry 平行清单与假语义统计；
- P1-004 evaluator_version 与文档口径漂移。

输出：.eval/scope_v5/before/before_audit_v5.json（覆盖式；before 态
只允许生成一次，重复执行前先确认文件不存在）。
"""
from __future__ import annotations

import inspect
import json
import re
import sqlite3
import sys
import urllib.error
import urllib.request
import http.cookiejar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / ".platform" / "platform.sqlite"
OUT = ROOT / ".eval" / "scope_v5" / "before"
OUT.mkdir(parents=True, exist_ok=True)
REPORT = OUT / "before_audit_v5.json"
if REPORT.exists() and "--force" not in sys.argv:
    print(f"before 证据已存在（不得覆盖 before 态）：{REPORT}")
    sys.exit(0)

env = {}
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1)
        env[k] = v.strip().strip('"').strip("'")
m = re.search(r"(\w+)[:/]([\w\-!@#$%^&*.]+)",
              env.get("PLATFORM_ADMIN_CREDENTIALS", ""))
OWNER, OWNER_PW = m.group(1), m.group(2)
BASE = "http://127.0.0.1:8400"

_JAR = http.cookiejar.CookieJar()
_OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(_JAR))


def api(method: str, path: str, body: dict | None = None,
        csrf: str = "") -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("content-type", "application/json")
    if csrf:
        req.add_header("X-CSRF-Token", csrf)
    try:
        with _OPENER.open(req) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


out: dict = {}

# ---------- P0-001：DB 侧 ----------
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
row = conn.execute(
    "SELECT COUNT(*) AS total,"
    " SUM(CASE WHEN data_scope='operational' AND COALESCE(test_run_id,"
    " '')='' THEN 1 ELSE 0 END) AS operational,"
    " SUM(CASE WHEN lower(filename) LIKE '%uat%' OR lower(mapping_json)"
    " LIKE '%uat%' THEN 1 ELSE 0 END) AS uat_semantic FROM"
    " import_batch_v1").fetchone()
out["p0001_db_counts"] = {"total": row["total"],
                          "operational": row["operational"],
                          "uat_semantic": row["uat_semantic"]}

# ---------- P0-002：创建链无作用域（静态签名事实） ----------
from src.platform.import_center import ImportCenter
sig_upload = str(inspect.signature(ImportCenter.upload))
sig_save = str(inspect.signature(ImportCenter._save_batch))
out["p0002_create_chain_unscoped"] = {
    "upload_signature": sig_upload,
    "upload_accepts_test_run_id": "test_run_id" in sig_upload,
    "save_batch_signature": sig_save,
    "save_batch_writes_scope": any(k in sig_save for k in (
        "data_scope", "test_run_id")),
}

# ---------- P0-005：平行清单 ----------
from src.platform.scope import _SCOPED_TABLES
from src.platform.scope_registry import SCOPE_REGISTRY
from src.platform.test_data import _SCOPED_DOMAIN_TABLES
out["p0005_parallel_lists"] = {
    "scope_registry": len(SCOPE_REGISTRY),
    "scope_py_scoped_tables": len(_SCOPED_TABLES),
    "test_data_scoped_domain_tables": len(_SCOPED_DOMAIN_TABLES),
    "import_batch_in_scoped_tables": "import_batch_v1" in _SCOPED_TABLES,
    "import_batch_in_domain_tables":
        "import_batch_v1" in _SCOPED_DOMAIN_TABLES,
}

# ---------- P0-006：Registry 假语义（schema 对账） ----------
schema = {}
for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name"
        " NOT LIKE 'sqlite_%'"):
    schema[name] = {r[1] for r in conn.execute(
        f"PRAGMA table_info({name})")}
bad_pk, bad_cust, bad_tenant = [], [], []
for t, e in SCOPE_REGISTRY.items():
    if t not in schema:
        continue
    cols = schema[t]
    if e.get("pk") and e["pk"] not in cols:
        bad_pk.append(f"{t}.{e['pk']}")
    if e.get("customer_col") and e["customer_col"] not in cols:
        bad_cust.append(f"{t}.{e['customer_col']}")
    if e.get("tenant_col") and e["tenant_col"] not in cols:
        bad_tenant.append(t)
out["p0006_registry_false_semantics"] = {
    "bad_pk_declarations": len(bad_pk), "bad_pk": bad_pk,
    "bad_customer_col_declarations": len(bad_cust),
    "bad_customer_col": bad_cust,
    "phantom_tenant_col_tables": len(bad_tenant),
    "import_batch_declares_missing_customer_id":
        "import_batch_v1.customer_id" in bad_cust,
}

# ---------- live API（只读） ----------
st, r = api("POST", "/api/v1/auth/login",
            {"username": OWNER, "password": OWNER_PW})
out["login"] = st
csrf = r.get("csrf_token", "")

st, r = api("GET", "/api/v1/import/batches")
out["p0001_api_default_list"] = {
    "status": st, "count": r.get("count"),
    "expected_polluted": r.get("count") == 20}

st, r = api("GET", "/api/v1/analytics/data-products")
imp = next((p for p in r.get("products", [])
            if p["product"] == "import.batches_v1"), {})
out["p0001_bi_data_products"] = {
    "status": st, "import_batches_rows": imp.get("rows"),
    "expected_polluted": imp.get("rows") == 20}

st, r = api("GET", "/api/v1/control/gate")
out["p1004_gate_version_drift"] = {
    "status": st, "gate": r.get("gate"),
    "evaluator_version": r.get("evaluator_version"),
    "docs_claim": "Gate 3.1",
    "wrongly_ready": r.get("gate") == "READY_FOR_REAL_DATA_UAT"}

# P0-004：详情接口原始 payload 泄漏面（只读采样第一条）
st, r = api("GET", "/api/v1/import/batches")
batches = r.get("batches") or []
if batches:
    st2, d = api("GET", f"/api/v1/import/batches/{batches[0]['batch_id']}")
    b = d.get("batch") or {}
    out["p0004_detail_leak_surface"] = {
        "status": st2,
        "returns_mapping_json": "mapping_json" in b,
        "returns_dry_run_json": "dry_run_json" in b,
        "returns_error_report_json": "error_report_json" in b,
        "returns_commit_json": "commit_json" in b,
        "mapping_json_size": len(b.get("mapping_json") or ""),
    }
conn.close()

REPORT.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                  encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2))
print("written:", REPORT)
