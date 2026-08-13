#!/usr/bin/env python3
"""OSV51 C-4：历史导入批次客户血缘回填（追加式、确定性、守恒）。

规则（01-ROOT-CAUSES-AND-CONTRACTS.md C-4）：
- 仅当 batch.test_run_id → uat_test_run_v1 唯一行 → customer_ids_json
  且 md_customer_v1 交叉印证全部客户存在时才绑定（结构化证据，禁止
  名称模糊猜测）；
- 关联写入 import_batch_customer_scope_v1（scope_source=
  'backfill_osv51'，INSERT OR IGNORE 防重）；
- 逐批写入 scope_backfill_audit_v1，detail_json 必须含 batch_id；
- data_scope=quarantine 批次一律不绑定（未绑定/待裁决，走裁决流程）；
- 不可唯一确定 → pending（UI/API 显示“未绑定/待裁决”，不得显示“全局”）；
- 输出 before/after 守恒报告（--out 可落盘 JSON）。

用法：
    python3 scripts/osv51_backfill_batch_customer_scope.py [--db PATH]
        [--apply] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import sqlite3

ROOT = Path(__file__).resolve().parents[1]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def backfill_conn(conn: sqlite3.Connection, *, apply: bool) -> dict:
    report: dict = {"bound": {}, "pending": [],
                    "quarantine_pending": [], "conservation": {}}
    before = conn.execute(
        "SELECT COUNT(*) c FROM"
        " import_batch_customer_scope_v1").fetchone()["c"]
    inserted = 0
    batches = conn.execute(
        "SELECT batch_id, template_id, data_scope, test_run_id FROM"
        " import_batch_v1 ORDER BY created_at").fetchall()
    for b in batches:
        bid = b["batch_id"]
        has = conn.execute(
            "SELECT COUNT(*) c FROM import_batch_customer_scope_v1"
            " WHERE batch_id=?", (bid,)).fetchone()["c"]
        if has:
            continue
        if (b["data_scope"] or "") == "quarantine":
            report["quarantine_pending"].append(bid)
            continue
        trid = b["test_run_id"] or ""
        if not trid:
            report["pending"].append(bid)
            continue
        trs = conn.execute(
            "SELECT customer_ids_json FROM uat_test_run_v1"
            " WHERE test_run_id=?", (trid,)).fetchall()
        if len(trs) != 1:
            report["pending"].append(bid)
            continue
        try:
            cids = json.loads(trs[0]["customer_ids_json"] or "[]")
        except Exception:
            cids = []
        if not cids:
            report["pending"].append(bid)
            continue
        ok = True
        for cid in cids:
            n = conn.execute(
                "SELECT COUNT(*) c FROM md_customer_v1"
                " WHERE customer_id=?", (cid,)).fetchone()["c"]
            if n < 1:
                ok = False
                break
        if not ok:
            report["pending"].append(bid)
            continue
        if apply:
            now = _utcnow()
            for cid in cids:
                rc = conn.execute(
                    "INSERT OR IGNORE INTO"
                    " import_batch_customer_scope_v1 (batch_id,"
                    " customer_id, project_id, scope_source,"
                    " authorization_decision, created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (bid, cid, "", "backfill_osv51", "granted",
                     now)).rowcount
                inserted += rc
            conn.execute(
                "INSERT INTO scope_backfill_audit_v1 (occurred_at,"
                " actor, table_name, matched_by, matched_count,"
                " assigned_scope, assigned_test_run_id, detail_json)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (now, "osv51_correction",
                 "import_batch_customer_scope_v1", "osv51_backfill",
                 len(cids), "uat_fixture", trid,
                 json.dumps({"batch_id": bid, "template_id":
                             b["template_id"], "test_run_id": trid,
                             "customer_ids": cids,
                             "rule": "test_run→registry 唯一客户集"
                                     "（md_customer 交叉印证）"},
                            ensure_ascii=False)))
            conn.commit()
        report["bound"][bid] = list(cids)
    after = conn.execute(
        "SELECT COUNT(*) c FROM"
        " import_batch_customer_scope_v1").fetchone()["c"]
    report["conservation"] = {
        "association_rows_before": before,
        "association_rows_after": after,
        "inserted": inserted,
        "batches_bound": len(report["bound"]),
        "pending": len(report["pending"]),
        "quarantine_pending": len(report["quarantine_pending"]),
    }
    return report


def backfill_store(store, *, apply: bool) -> dict:
    return backfill_conn(store._conn, apply=apply)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / ".platform" /
                                        "platform.sqlite"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rep = backfill_conn(conn, apply=args.apply)
    text = json.dumps(rep, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"报告已写入 {args.out}")
    print(text[:2000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
