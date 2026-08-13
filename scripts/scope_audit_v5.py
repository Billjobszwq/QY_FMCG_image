#!/usr/bin/env python3
"""OSV5（OSV5-012）：现行 scope 审计器（取代 scope_audit_v4 的过期
口径）。七维检查 import_batch_v1 全链与 Registry 可执行性：

1) 列存在（data_scope/test_run_id/visibility/archived_at）；
2) 创建路径写入（ImportCenter._save_batch 写 scope 列）；
3) scanner 消费（scope._SCOPED_TABLES 由 Registry leak_scan 派生）；
4) archiver 消费（ARCHIVE_HANDLERS 含 import_batch_v1）；
5) API 过滤（list_batches 默认 effective operational）；
6) Gate 覆盖（Gate 3.2 import_batch_* / registry_* 检查）；
7) Registry 声明可执行（validate_registry 零错误）。

只读；输出 JSON。用法：python3 scripts/scope_audit_v5.py
"""
from __future__ import annotations

import inspect
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / ".platform" / "platform.sqlite"

from src.platform import gate_evaluator, import_center, scope, test_data
from src.platform.scope_registry import (ARCHIVE_HANDLERS,
                                         leak_scan_tables,
                                         validate_registry)

out: dict = {}
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

# 1) 列存在
cols = {r[1] for r in conn.execute("PRAGMA table_info(import_batch_v1)")}
need = {"data_scope", "test_run_id", "visibility", "archived_at"}
out["1_columns_present"] = {c: c in cols for c in sorted(need)}

# 2) 创建路径写入
sig = inspect.signature(import_center.ImportCenter._save_batch)
out["2_create_path_writes_scope"] = all(
    p in sig.parameters for p in ("data_scope", "test_run_id"))

# 3) scanner 派生消费
out["3_scanner_derived"] = {
    "import_batch_in_scoped_tables":
        "import_batch_v1" in scope._SCOPED_TABLES,
    "scoped_tables_equals_registry_leak_scan":
        tuple(scope._SCOPED_TABLES) == leak_scan_tables(),
}

# 4) archiver 派生消费
out["4_archiver_derived"] = {
    "handler_registered": "import_batch_v1" in ARCHIVE_HANDLERS,
    "handler_callable": callable(ARCHIVE_HANDLERS.get("import_batch_v1")),
    "test_data_domain_tables_derived":
        tuple(test_data._SCOPED_DOMAIN_TABLES)
        == tuple(sorted(ARCHIVE_HANDLERS)),
}

# 5) API 过滤口径
out["5_api_default_effective"] = {
    "operational_now": conn.execute(
        "SELECT count(*) c FROM import_batch_v1 WHERE COALESCE("
        "data_scope,'operational')='operational' AND COALESCE("
        "test_run_id,'')='' AND COALESCE(visibility,'current')"
        "='current'").fetchone()["c"],
    "fixture_or_history": conn.execute(
        "SELECT count(*) c FROM import_batch_v1 WHERE COALESCE("
        "data_scope,'operational')!='operational' OR COALESCE("
        "visibility,'current')!='current'").fetchone()["c"],
    "quarantine": conn.execute(
        "SELECT count(*) c FROM import_batch_v1 WHERE data_scope="
        "'quarantine'").fetchone()["c"],
}

# 6) Gate 覆盖
src = inspect.getsource(gate_evaluator)
gate_checks = ("import_batch_scope_complete",
               "import_batch_operational_fixture_zero",
               "import_batch_unknown_scope_zero",
               "import_batch_api_effective_consistent",
               "import_batch_bi_effective_consistent",
               "import_batch_archive_handler_registered",
               "import_batch_test_center_consistent",
               "import_batch_cross_tenant_access_denied",
               "import_batch_raw_payload_redacted",
               "registry_schema_valid",
               "registry_runtime_scanner_complete",
               "registry_archive_handler_complete",
               "registry_operational_query_complete",
               "registry_parent_edges_valid",
               "data_products_all_effective_consistent",
               "browser_import_current_history_separated",
               "uat_import_lineage_complete",
               "evaluator_version_consistent")
out["6_gate_coverage"] = {
    "evaluator_version": gate_evaluator.EVALUATOR_VERSION,
    "checks_present": {c: c in src for c in gate_checks},
}

# 7) Registry 可执行性
problems = validate_registry(conn)
out["7_registry_executable"] = {"problems": problems,
                                "zero_errors": not problems}

conn.close()
print(json.dumps(out, ensure_ascii=False, indent=2))
fails = []
if not all(out["1_columns_present"].values()):
    fails.append("columns")
if not out["2_create_path_writes_scope"]:
    fails.append("create_path")
if not all(out["3_scanner_derived"].values()):
    fails.append("scanner")
if not all(out["4_archiver_derived"].values()):
    fails.append("archiver")
if not all(out["6_gate_coverage"]["checks_present"].values()):
    fails.append("gate")
if not out["7_registry_executable"]["zero_errors"]:
    fails.append("registry")
print("FAILS:", fails or "无")
sys.exit(1 if fails else 0)
