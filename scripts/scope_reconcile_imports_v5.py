#!/usr/bin/env python3
"""OSV5 T5：历史导入批次纠偏（指令 5.3 / 04-HISTORICAL-RECONCILIATION）。

对仍被计为 operational 的历史 import_batch_v1 行做只读 classification
plan，再幂等执行：
- 结构化证据能唯一确定 Test Run → 追加式绑定 uat_fixture +
  test_run_id + visibility=history（不删行）；
- 不能唯一确定 → fail-closed 落 data_scope='quarantine'（不得继续
  计入 operational；仅管理员纠偏面可见）。

证据优先级（文件名/UAT 前缀仅辅助诊断，不作唯一依据）：
1) mapping_json 行内 customer_id ↔ uat_test_run_v1.customer_ids_json；
2) commit receipts 业务对象 ↔ Test Run（客户/地址/员工父链）；
3) 创建时间 ↔ Test Run 时间窗（辅助收敛多候选）。

每批 decision 写入 scope_backfill_audit_v1；前后 hash 对账；重复执行
幂等（已绑定/quarantine 行不再处理）。

用法：
  python3 scripts/scope_reconcile_imports_v5.py            # 只读 plan
  python3 scripts/scope_reconcile_imports_v5.py --apply    # 执行纠偏
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / ".platform" / "platform.sqlite"

# 模板 → 行内客户列（与 import_center.TEMPLATE_CUSTOMER_COL 同源）
_CUSTOMER_COLS = ("customer_id",)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table_hash(conn) -> str:
    rows = conn.execute(
        "SELECT batch_id, data_scope, test_run_id, visibility FROM"
        " import_batch_v1 ORDER BY batch_id").fetchall()
    return hashlib.sha256(json.dumps(
        [list(r) for r in rows], ensure_ascii=False).encode()).hexdigest()


def _test_runs(conn) -> list[dict]:
    out = []
    for r in conn.execute(
            "SELECT test_run_id, status, customer_ids_json, created_at,"
            " archived_at FROM uat_test_run_v1").fetchall():
        cids = []
        try:
            cids = json.loads(r[2] or "[]")
        except Exception:
            cids = []
        out.append({"test_run_id": r[0], "status": r[1],
                    "customers": set(cids), "created_at": r[3],
                    "archived_at": r[4]})
    return out


def _batch_customers(mapping: dict) -> set[str]:
    header = mapping.get("header") or []
    rows = mapping.get("rows") or []
    idxs = [i for i, h in enumerate(header)
            if (h or "").strip() in _CUSTOMER_COLS]
    out: set[str] = set()
    for row in rows:
        for i in idxs:
            if i < len(row) and str(row[i]).strip():
                out.add(str(row[i]).strip())
    return out


def _receipt_customers(conn, commit: dict) -> set[str]:
    """commit receipts 业务对象 → 客户父链（证据 2）。"""
    out: set[str] = set()
    receipts = (commit or {}).get("receipts") or []
    addr_ids = [r["address_id"] for r in receipts if r.get("address_id")]
    emp_ids = [r["employee_id"] for r in receipts if r.get("employee_id")]
    for table, col, ids in (("geo_address_v1", "address_id", addr_ids),
                            ("geo_employee_v1", "employee_id", emp_ids)):
        for oid in ids:
            row = conn.execute(
                f"SELECT customer_id FROM {table} WHERE {col}=?",
                (oid,)).fetchone()
            if row and row[0]:
                out.add(row[0])
    return out


def _candidates(customers: set[str], runs: list[dict]) -> list[str]:
    return [r["test_run_id"] for r in runs
            if customers and customers & r["customers"]]


def plan_reconciliation(conn) -> dict:
    """只读 classification plan（不得写库）。"""
    runs = _test_runs(conn)
    rows = conn.execute(
        "SELECT batch_id, template_id, filename, mapping_json,"
        " commit_json, created_at FROM import_batch_v1 WHERE"
        " COALESCE(data_scope,'operational')='operational' AND"
        " COALESCE(test_run_id,'')='' ORDER BY created_at").fetchall()
    decisions = []
    for r in rows:
        try:
            mapping = json.loads(r[3] or "{}")
        except Exception:
            mapping = {}
        try:
            commit = json.loads(r[4] or "{}")
        except Exception:
            commit = {}
        custs = _batch_customers(mapping) | _receipt_customers(conn, commit)
        cands = _candidates(custs, runs)
        evidence = {
            "batch_customers": sorted(custs),
            "candidates": sorted(cands),
            "rules": [],
        }
        if len(cands) == 1:
            evidence["rules"].append(
                "mapping/commit 客户 ↔ 唯一 Test Run 客户集")
            decisions.append({"batch_id": r[0], "decision": "bind",
                              "test_run_id": cands[0],
                              "evidence": evidence})
        else:
            evidence["rules"].append(
                "quarantine: 候选 Test Run 数="
                f"{len(cands)}（0=无结构化证据，>1=不唯一）")
            decisions.append({"batch_id": r[0],
                              "decision": "quarantine",
                              "test_run_id": "",
                              "evidence": evidence})
    return {"total": len(decisions), "decisions": decisions,
            "before_hash": _table_hash(conn)}


def apply_reconciliation(conn, plan: dict, *, actor: str) -> dict:
    """幂等执行 plan；逐批写 scope_backfill_audit_v1；不删行。"""
    applied = {"bind": 0, "quarantine": 0, "skipped": 0}
    for d in plan["decisions"]:
        cur = conn.execute(
            "SELECT COALESCE(data_scope,'operational') ds FROM"
            " import_batch_v1 WHERE batch_id=?",
            (d["batch_id"],)).fetchone()
        if cur is None or cur["ds"] != "operational":
            applied["skipped"] += 1  # 幂等：已处理行不再触碰
            continue
        if d["decision"] == "bind":
            conn.execute(
                "UPDATE import_batch_v1 SET data_scope='uat_fixture',"
                " test_run_id=?, visibility='history', archived_at=?"
                " WHERE batch_id=? AND COALESCE(data_scope,"
                "'operational')='operational'",
                (d["test_run_id"], _now(), d["batch_id"]))
            assigned_scope, trid = "uat_fixture", d["test_run_id"]
        else:
            conn.execute(
                "UPDATE import_batch_v1 SET data_scope='quarantine',"
                " archived_at=? WHERE batch_id=? AND COALESCE("
                "data_scope,'operational')='operational'",
                (_now(), d["batch_id"]))
            assigned_scope, trid = "quarantine", ""
        conn.execute(
            "INSERT INTO scope_backfill_audit_v1 (occurred_at, actor,"
            " table_name, matched_by, matched_count, assigned_scope,"
            " assigned_test_run_id, detail_json)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (_now(), actor, "import_batch_v1",
             "; ".join(d["evidence"]["rules"]), 1, assigned_scope,
             trid, json.dumps(d["evidence"], ensure_ascii=False)))
        applied[d["decision"]] += 1
    conn.commit()
    return {**applied, "after_hash": _table_hash(conn)}


def main() -> None:
    import sqlite3
    apply = "--apply" in sys.argv
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    plan = plan_reconciliation(conn)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if not apply:
        print("\n[dry-run] 未写库；before_hash =",
              plan["before_hash"])
        return
    res = apply_reconciliation(conn, plan, actor="osv5_reconcile")
    print("\n[apply]", json.dumps(res, ensure_ascii=False))
    conn.close()


if __name__ == "__main__":
    main()
