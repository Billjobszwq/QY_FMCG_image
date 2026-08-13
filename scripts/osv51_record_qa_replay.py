#!/usr/bin/env python3
"""OSV51 C-1.9：imp-bf333d101db6 QA 重放事件对账入账（追加式）。

独立 QA 期间（2026-08-13T08:07:41Z）隔离批次 imp-bf333d101db6 被
重放 commit：commit_json 被覆写（inserted:1 → skipped:1）、新增
evid-dca91a51476a 与第二条 import.committed 审计。任务要求：不得
静默回写历史；从事件、审计和备份对账，追加 QA_REPLAY_DETECTED
证据并明确 supersedes 关系。

本脚本只做追加（INSERT），绝不 UPDATE/DELETE 任何历史行；幂等
（按固定 evidence_id / 规则标记查重）。默认 dry-run，--apply 执行。
用法：
    python3 scripts/osv51_record_qa_replay.py [--db PATH] [--apply]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / ".platform" / "platform.sqlite"

BATCH_ID = "imp-bf333d101db6"
EVIDENCE_ID = "evid-osv51-qa-replay-bf333d101db6"
REPLAYED_EVIDENCE_ID = "evid-dca91a51476a"
REPLAY_AT = "2026-08-13T08:07:41+00:00"
QUARANTINE_AT = "2026-08-13T05:28:36+00:00"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_detail(conn: sqlite3.Connection) -> dict:
    """从现存事件/审计/批次行对账（只读）。"""
    audits = conn.execute(
        "SELECT audit_id, actor_id, action, resource, detail_json,"
        " occurred_at FROM iam_audit_event_v1 WHERE resource=?"
        " ORDER BY audit_id", (f"import:{BATCH_ID}",)).fetchall()
    batch = conn.execute(
        "SELECT status, commit_json, created_at, updated_at,"
        " archived_at, data_scope FROM import_batch_v1"
        " WHERE batch_id=?", (BATCH_ID,)).fetchone()
    evid = conn.execute(
        "SELECT evidence_id, kind, source_uri, created_at"
        " FROM evidence_bundle_v1 WHERE source_uri=?"
        " ORDER BY created_at", (f"import_batch:{BATCH_ID}",)).fetchall()
    return {
        "batch_id": BATCH_ID,
        "event": "QA_REPLAY_DETECTED",
        "supersedes": {
            "replayed_evidence_id": REPLAYED_EVIDENCE_ID,
            "semantics": ("重放产生的证据被本条对账证据取代为权威口径；"
                          "原行不回写"),
        },
        "quarantined_at": QUARANTINE_AT,
        "replayed_at": REPLAY_AT,
        "facts": {
            "iam_audit_events": [dict(a) for a in audits],
            "batch_row": dict(batch) if batch else None,
            "evidence_rows": [dict(e) for e in evid],
            "app_log_hint": (".platform/logs/app.log 两处"
                             " POST /api/v1/import/batches/"
                             f"{BATCH_ID}/commit（行 7001/18504）"),
        },
        "reconciliation": {
            "commit_json_overwritten": "inserted:1 → skipped:1",
            "new_operational_objects": 0,
            "reason": "地址已存在被幂等跳过；无守卫，属运气非设计",
            "historical_rows_unchanged": True,
        },
        "recorded_by": "osv51_correction",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--apply", action="store_true",
                    help="实际写入（默认 dry-run 只打印）")
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    batch = conn.execute(
        "SELECT batch_id FROM import_batch_v1 WHERE batch_id=?",
        (BATCH_ID,)).fetchone()
    if not batch:
        print(f"批次 {BATCH_ID} 不存在于 {args.db}，跳过")
        return 0

    detail = build_detail(conn)
    already_ev = conn.execute(
        "SELECT evidence_id FROM evidence_bundle_v1 WHERE evidence_id=?",
        (EVIDENCE_ID,)).fetchone()
    already_audit = conn.execute(
        "SELECT id FROM scope_backfill_audit_v1 WHERE table_name="
        "'import_batch_v1' AND matched_by='QA_REPLAY_DETECTED' AND"
        " detail_json LIKE ?", (f'%"batch_id": "{BATCH_ID}"%',)
    ).fetchone()

    print("QA_REPLAY_DETECTED 对账摘要：")
    print(json.dumps(detail["reconciliation"], ensure_ascii=False,
                     indent=2))
    print(f"evidence 已存在: {bool(already_ev)}；"
          f"audit 已存在: {bool(already_audit)}")
    if not args.apply:
        print("dry-run（--apply 才写入）")
        return 0

    if not already_ev:
        conn.execute(
            "INSERT INTO evidence_bundle_v1 (evidence_id, run_id,"
            " work_id, kind, source_uri, cas_hash, content_type,"
            " producer, input_hash, config_version, data_scope,"
            " test_run_id, created_at) VALUES"
            " (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (EVIDENCE_ID, "", "", "qa_replay_detection",
             f"import_batch:{BATCH_ID}", "", "application/json",
             "osv51_correction", "", "osv51",
             "quarantine", "", _utcnow()))
        print(f"+ evidence_bundle_v1 {EVIDENCE_ID}")
    if not already_audit:
        conn.execute(
            "INSERT INTO scope_backfill_audit_v1 (occurred_at, actor,"
            " table_name, matched_by, matched_count, assigned_scope,"
            " assigned_test_run_id, detail_json) VALUES"
            " (?,?,?,?,?,?,?,?)",
            (_utcnow(), "osv51_correction", "import_batch_v1",
             "QA_REPLAY_DETECTED", 1, "quarantine", "",
             json.dumps(detail, ensure_ascii=False)))
        print("+ scope_backfill_audit_v1 QA_REPLAY_DETECTED")
    conn.commit()
    print("done（未修改任何历史行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
