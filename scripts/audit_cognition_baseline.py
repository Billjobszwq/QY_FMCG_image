#!/usr/bin/env python3
"""Task 1（G0）：认知内核开工基线只读审计脚本。

只做只读复核（git / SQLite mode=ro / ps / CURRENT.json），输出 JSON：
HEAD、分支、DB 指纹、迁移、关键表计数、进程与 production 事实。
不得写任何文件、不得修改 DB、不得启停进程。

用法：python scripts/audit_cognition_baseline.py [--db PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

TARGET_TABLES = (
    "agent_manifest_v1", "agent_definition_v1", "memory_entry_v1",
    "agent_memory_v1", "blackboard_event_v1", "knowledge_document_v1",
    "agent_asset_v1", "agent_run_v1", "business_run_v1", "work_item_v2",
    "event_envelope_v1", "usage_event_v2", "evidence_bundle_v1",
    "workflow_definition_v1", "import_batch_v1", "uat_test_run_v1",
    "gate_run_v1", "scope_attribution_ledger_v1",
)

TRAINING_MARKERS = ("ultralytics", "train_v1", "qlora", "finetune_qwen",
                    "mlx_lm")


def _git(*args: str) -> str:
    out = subprocess.run(("git", *args), cwd=REPO_ROOT,
                         capture_output=True, text=True, timeout=30)
    return out.stdout.strip() if out.returncode == 0 else ""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def audit(db_path: Path) -> dict:
    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "repo_root": str(REPO_ROOT),
    }
    # ---- git ----
    report["git"] = {
        "head": _git("rev-parse", "HEAD"),
        "branch": _git("branch", "--show-current"),
        "status_short": _git("status", "--short", "--branch"),
    }
    # ---- DB ----
    db: dict = {"path": str(db_path), "exists": db_path.exists()}
    if db_path.exists():
        db["sha256"] = _sha256(db_path)
        db["size_bytes"] = db_path.stat().st_size
        conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro",
                               uri=True)
        conn.row_factory = sqlite3.Row
        db["integrity_check"] = conn.execute(
            "PRAGMA integrity_check").fetchone()[0]
        mig = conn.execute("SELECT name FROM schema_migrations"
                           " ORDER BY id").fetchall()
        db["migration_count"] = len(mig)
        db["latest_migration"] = mig[-1]["name"] if mig else ""
        db["table_count"] = conn.execute(
            "SELECT count(*) c FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%'").fetchone()["c"]
        counts = {}
        for t in TARGET_TABLES:
            try:
                counts[t] = conn.execute(
                    f"SELECT count(*) c FROM {t}").fetchone()["c"]
            except sqlite3.Error as e:
                counts[t] = f"ERROR:{e}"
        db["table_counts"] = counts
        defs = conn.execute(
            "SELECT agent_id, max(version) v FROM agent_definition_v1"
            " GROUP BY agent_id ORDER BY agent_id").fetchall()
        db["agent_definitions"] = [
            {"agent_id": r["agent_id"], "max_version": r["v"]}
            for r in defs]
        conn.close()
    report["database"] = db
    # ---- processes（只读 ps，不启停） ----
    try:
        ps = subprocess.run(["ps", "aux"], capture_output=True,
                            text=True, timeout=10).stdout
        hits = [ln.split()[1] for ln in ps.splitlines()
                if any(m in ln for m in TRAINING_MARKERS)
                and "grep" not in ln and "audit_cognition" not in ln]
        report["training_processes"] = hits
    except Exception:
        report["training_processes"] = "unavailable"
    # ---- production bundle ----
    cur = REPO_ROOT / ".models" / "bundles" / "CURRENT.json"
    try:
        report["production_bundle"] = json.loads(
            cur.read_text(encoding="utf-8"))
    except Exception:
        report["production_bundle"] = None
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="cognition baseline audit")
    ap.add_argument("--db",
                    default=str(REPO_ROOT / "runtime" / "platform" /
                                "platform.sqlite"))
    args = ap.parse_args()
    print(json.dumps(audit(Path(args.db)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
