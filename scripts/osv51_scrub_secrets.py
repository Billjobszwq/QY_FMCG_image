#!/usr/bin/env python3
"""OSV51 C-2：存量导入批次 JSON 的秘密清洗（递归、安全、幂等）。

扫描 import_batch_v1 全部 JSON 列（mapping/dry_run/error_report/
commit），对敏感键（password/token/api_key/secret/credential/
private_key 等，子串匹配、大小写不敏感）的非 [REDACTED] 字符串值
原位替换为 [REDACTED]；每个被清洗批次追加一条审计
（import.secret.scrubbed），只记键路径与指纹（sha256 前 8 位），
绝不打印/记录原值。

用法：
    python3 scripts/osv51_scrub_secrets.py [--db PATH] [--apply]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import sqlite3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.platform.import_center import redact_secrets  # noqa: E402

COLUMNS = ("mapping_json", "dry_run_json", "error_report_json",
           "commit_json")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _collect_paths(obj, paths: list, prefix="$") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if any(s in kl for s in ("password", "passwd", "token",
                                     "api_key", "apikey", "secret",
                                     "credential", "private_key")) \
                    and isinstance(v, str) and v and v != "[REDACTED]":
                paths.append((f"{prefix}.{k}", _fingerprint(v)))
            _collect_paths(v, paths, f"{prefix}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _collect_paths(v, paths, f"{prefix}[{i}]")


def scrub_conn(conn: sqlite3.Connection, *, apply: bool) -> dict:
    scrubbed: list[str] = []
    total_paths = 0
    for row in conn.execute(
            "SELECT batch_id, mapping_json, dry_run_json,"
            " error_report_json, commit_json FROM import_batch_v1"):
        updates: dict = {}
        paths: list = []
        for col in COLUMNS:
            raw = row[col] or "{}"
            try:
                parsed = json.loads(raw)
            except Exception:
                continue
            found: list = []
            _collect_paths(parsed, found)
            if not found:
                continue
            paths.extend(found)
            if apply:
                updates[col] = json.dumps(redact_secrets(parsed),
                                          ensure_ascii=False)
        if paths:
            scrubbed.append(row["batch_id"])
            total_paths += len(paths)
            if apply:
                for col, val in updates.items():
                    conn.execute(
                        f"UPDATE import_batch_v1 SET {col}=?"
                        " WHERE batch_id=?", (val, row["batch_id"]))
                conn.execute(
                    "INSERT INTO iam_audit_event_v1 (occurred_at,"
                    " actor_id, action, resource, detail_json,"
                    " tenant_id, customer_id) VALUES (?,?,?,?,?,?,?)",
                    (_utcnow(), "osv51_correction",
                     "import.secret.scrubbed",
                     f"import:{row['batch_id']}",
                     json.dumps({
                         "batch_id": row["batch_id"],
                         "redacted_key_paths": [p for p, _ in paths],
                         "value_fingerprints": [f for _, f in paths],
                         "note": "值不回显；仅存指纹"},
                         ensure_ascii=False),
                     "local", ""))
                conn.commit()
    return {"scrubbed_batches": scrubbed,
            "redacted_key_paths": total_paths,
            "applied": apply}


def scrub_store(store) -> dict:
    """供测试/服务内调用（store._conn 直连）。"""
    return scrub_conn(store._conn, apply=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / ".platform" /
                                        "platform.sqlite"))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    report = scrub_conn(conn, apply=args.apply)
    # 只输出批次数与路径数，不输出任何键路径/值
    print(json.dumps({"applied": report["applied"],
                      "scrubbed_count": len(report["scrubbed_batches"]),
                      "redacted_key_paths":
                          report["redacted_key_paths"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
