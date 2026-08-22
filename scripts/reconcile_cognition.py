#!/usr/bin/env python3
"""认知内核对账（Task 13 / 05 Task 12）：--read-only 只读核对。

用法：python scripts/reconcile_cognition.py --read-only [--json]

核对项：
- SQLite integrity_check；
- 认知各表行数（source/document/chunk/span/knowledge/skill/memory/research）；
- 知识发布一致性：published 知识是否都有 ≥1 真实 span；
- 索引激活与 build 记录一致性。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "runtime" / "platform" / "platform.sqlite"

TABLES = ("cognition_source_artifact_v1", "cognition_document_version_v1",
          "cognition_chunk_v1", "cognition_evidence_span_v1",
          "knowledge_item_version", "skill_definition_version",
          "memory_l1_event", "memory_l2_episode",
          "memory_l3_methodology_version", "research_run_v1",
          "research_query_v1", "research_claim_v1", "claim_evidence_v1",
          "research_report_v1", "cognition_index_build_v1",
          "cognition_index_activation_v1")


def reconcile(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro",
                           uri=True)
    conn.row_factory = sqlite3.Row
    out: dict = {"db": str(db_path), "exists": db_path.exists()}
    if not db_path.exists():
        return out
    out["integrity_check"] = conn.execute(
        "PRAGMA integrity_check").fetchone()[0]
    counts = {}
    for t in TABLES:
        try:
            counts[t] = conn.execute(
                f"SELECT count(*) c FROM {t}").fetchone()["c"]
        except sqlite3.Error:
            counts[t] = None  # 表尚未创建（迁移未应用）
    out["table_counts"] = counts
    # 知识发布一致性：published 知识是否都有 ≥1 真实 span
    try:
        rows = conn.execute(
            "SELECT knowledge_id, version, source_span_ids_json FROM"
            " knowledge_item_version WHERE status='published'").fetchall()
        missing = []
        for r in rows:
            ids = json.loads(r["source_span_ids_json"] or "[]")
            if not ids:
                missing.append(f"{r['knowledge_id']}@v{r['version']}")
                continue
            marks = ",".join("?" * len(ids))
            n = conn.execute(
                f"SELECT count(DISTINCT span_id) c FROM"
                f" cognition_evidence_span_v1 WHERE span_id IN ({marks})",
                tuple(ids)).fetchone()["c"]
            if n == 0:
                missing.append(f"{r['knowledge_id']}@v{r['version']}")
        out["published_knowledge_without_span"] = missing
    except sqlite3.Error:
        out["published_knowledge_without_span"] = None
    # 索引激活与 build 一致性
    try:
        acts = conn.execute(
            "SELECT index_snapshot_id FROM cognition_index_activation_v1"
            " WHERE status='active'").fetchall()
        orphan = []
        for a in acts:
            b = conn.execute(
                "SELECT 1 FROM cognition_index_build_v1 WHERE"
                " index_snapshot_id=?", (a["index_snapshot_id"],)
            ).fetchone()
            if b is None:
                orphan.append(a["index_snapshot_id"])
        out["active_index_without_build"] = orphan
    except sqlite3.Error:
        out["active_index_without_build"] = None
    # R2-04：Research 终态对账（假成功/账本漂移/孤儿检测；任一非空即
    # gate_ok=False，G9 不得放行）。
    try:
        succ = conn.execute(
            "SELECT research_run_id, business_run_id FROM research_run_v1"
            " WHERE status='succeeded'").fetchall()
        no_report, no_evidence, drift = [], [], []
        for r in succ:
            rid, bid = r["research_run_id"], r["business_run_id"]
            if conn.execute(
                    "SELECT 1 FROM research_report_v1 WHERE"
                    " research_run_id=?", (rid,)).fetchone() is None:
                no_report.append(rid)
            if conn.execute(
                    "SELECT 1 FROM evidence_bundle_v1 WHERE run_id=?",
                    (bid,)).fetchone() is None:
                no_evidence.append(rid)
            biz = conn.execute(
                "SELECT status FROM business_run_v1 WHERE run_id=?",
                (bid,)).fetchone()
            work = conn.execute(
                "SELECT w.status s FROM work_item_v2 w JOIN"
                " business_run_v1 b ON b.work_id=w.work_id WHERE"
                " b.run_id=?", (bid,)).fetchone()
            if biz is None or biz["status"] != "succeeded":
                drift.append({"research_run_id": rid, "kind": "business",
                              "expected": "succeeded",
                              "actual": biz["status"] if biz else None})
            if work is None or work["s"] != "completed":
                drift.append({"research_run_id": rid, "kind": "work",
                              "expected": "completed",
                              "actual": work["s"] if work else None})

        def _orphans(table: str) -> list[str]:
            rows = conn.execute(
                f"SELECT DISTINCT t.research_run_id id FROM {table} t"
                " LEFT JOIN research_run_v1 r ON"
                " r.research_run_id=t.research_run_id WHERE"
                " r.research_run_id IS NULL").fetchall()
            return sorted(r["id"] for r in rows)

        out["research_terminal_drift"] = {
            "succeeded_without_report": sorted(no_report),
            "succeeded_without_evidence": sorted(no_evidence),
            "status_drift": drift,
            "orphan_steps": _orphans("research_step_v1"),
            "orphan_queries": _orphans("research_query_v1"),
            "orphan_claims": _orphans("research_claim_v1"),
        }
    except sqlite3.Error:
        out["research_terminal_drift"] = None
    # 综合 Gate：任一一致性项缺失/漂移即 False（G9 fail 依据）
    def _bad(key: str) -> bool:
        v = out.get(key)
        return v is None or bool(v)
    td = out["research_terminal_drift"]
    drift_bad = (td is None or _bad_drift(td))
    out["gate_ok"] = not (_bad("published_knowledge_without_span")
                          or _bad("active_index_without_build")
                          or drift_bad)
    conn.close()
    return out


def _bad_drift(td: dict) -> bool:
    return any(td.get(k) for k in ("succeeded_without_report",
                                   "succeeded_without_evidence",
                                   "status_drift", "orphan_steps",
                                   "orphan_queries", "orphan_claims"))


def main() -> None:
    ap = argparse.ArgumentParser(description="cognition reconciliation")
    ap.add_argument("--read-only", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    args = ap.parse_args()
    result = reconcile(Path(args.db))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for k, v in result.items():
            print(f"{k}: {v}")
    # R2-04：终态漂移/孤儿/假成功存在时以非零退出（G9 fail 依据）。
    if result.get("gate_ok") is False or result.get(
            "integrity_check") not in (None, "ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
