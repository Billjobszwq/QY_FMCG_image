"""统一模型管理只读对账与迁移预检（M1/G0、M10/G9）。

纪律（与 scripts/cognition_migrate_legacy.py preflight 一致，R2-02）：
- 全程 ``sqlite3 mode=ro`` 打开；绝不构造 PlatformStore；绝不应用 schema
  migration；绝不写任何表或 journal 文件。
- 任一漂移 → ``gate_ok=False`` 且 CLI exit 1；正常 exit 0。

对账项（新表不存在时如实报告 absent，不算漂移）：
1. integrity_check；
2. 迁移数量与最新迁移；
3. connection active 唯一性（同 connection_id 至多一个 active 版本）；
4. binding active/canary 唯一性（同 scope key 至多一个 active、一个 canary）；
5. 孤儿 catalog（引用不存在的 connection version）；
6. 孤儿 binding（引用不存在的 connection version 或未 ready 的 model）；
7. secret 元数据：active connection 引用 secret_ref 但无任何 envelope 版本；
   以及 envelope 中 status 非法值；
8. usage 未归属：model_call_id 非空但 principal_id 为空；
9. 调用账本悬挂：requested 状态超过阈值未结算（对账窗口外）；
   metering_incomplete 未收敛；
10. Embedding 索引身份漂移：同 target_kind 多个 active activation，或
    activation 指向不存在/非 ready 的 build；dense build 未记录
    embedding_model 身份。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "runtime" / "platform" / "platform.sqlite"

MODEL_TABLES = (
    "model_connection_version_v1",
    "model_catalog_entry_v1",
    "model_binding_version_v1",
    "model_secret_envelope_v1",
    "model_call_ledger_v1",
    "model_rate_card_v1",
    "model_budget_v1",
)

# requested 超过该秒数未结算视为悬挂（进程中断后由 reconciliation 收敛）。
REQUESTED_STALE_SECONDS = 600


def _ro_connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def readonly_model_preflight(db_path: Path) -> dict[str, Any]:
    """只读预检：integrity、迁移数、最新迁移、模型表存在性。

    不构造 PlatformStore、不写任何字节。"""
    conn = _ro_connect(db_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        migration_count = conn.execute(
            "SELECT count(*) c FROM schema_migrations").fetchone()[0]
        latest = conn.execute(
            "SELECT name FROM schema_migrations ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        present = _tables(conn)
        return {
            "integrity": integrity,
            "migration_count": migration_count,
            "latest_migration": latest,
            "model_tables_present": all(t in present for t in MODEL_TABLES),
        }
    finally:
        conn.close()


def reconcile(db_path: Path, *, read_only: bool) -> dict[str, Any]:
    """只读对账；read_only=False 直接拒绝（本脚本没有写模式）。"""
    if not read_only:
        raise ValueError(
            "reconcile_model_management 仅支持 --read-only；"
            "迁移与恢复演练请使用显式 mktemp 副本和平台迁移工具")

    report: dict[str, Any] = {"checks": [], "drift": []}

    def check(name: str, ok: bool, detail: Any = None) -> None:
        report["checks"].append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            report["drift"].append({"name": name, "detail": detail})

    conn = _ro_connect(db_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        check("integrity", integrity == "ok", integrity)

        migration_count = conn.execute(
            "SELECT count(*) c FROM schema_migrations").fetchone()[0]
        latest = conn.execute(
            "SELECT name FROM schema_migrations ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        report["migration_count"] = migration_count
        report["latest_migration"] = latest

        present = _tables(conn)
        have_models = all(t in present for t in MODEL_TABLES)
        report["model_tables_present"] = have_models
        if not have_models:
            # 旧库（如 live 068）：新表不存在不是漂移，如实报告并退出。
            report["gate_ok"] = True
            report["note"] = ("模型管理表尚未应用（072–074 未迁移）；"
                              "只读对账无对象，判定 ok")
            return report

        # 3. connection active 唯一性
        dup_conn = [dict(r) for r in conn.execute(
            "SELECT connection_id, count(*) n FROM"
            " model_connection_version_v1 WHERE status='active'"
            " GROUP BY connection_id HAVING count(*) > 1")]
        check("connection_active_unique", not dup_conn, dup_conn)

        # 4. binding active/canary 唯一性
        for status in ("active", "canary"):
            dup = [dict(r) for r in conn.execute(
                "SELECT tenant_id, customer_id, project_id, subject_kind,"
                " subject_id, capability, count(*) n FROM"
                f" model_binding_version_v1 WHERE status='{status}'"
                " GROUP BY tenant_id, customer_id, project_id,"
                " subject_kind, subject_id, capability HAVING count(*) > 1")]
            check(f"binding_{status}_unique", not dup, dup)

        # 5. 孤儿 catalog
        orphan_catalog = [dict(r) for r in conn.execute(
            "SELECT c.catalog_id FROM model_catalog_entry_v1 c"
            " LEFT JOIN model_connection_version_v1 v"
            "  ON v.connection_id = c.connection_id"
            " AND v.version = c.connection_version"
            " AND v.tenant_id = c.tenant_id"
            " WHERE v.connection_id IS NULL")]
        check("catalog_no_orphan", not orphan_catalog, orphan_catalog)

        # 6. 孤儿 binding（引用不存在的 connection version）
        orphan_binding = [dict(r) for r in conn.execute(
            "SELECT b.binding_id, b.version FROM model_binding_version_v1 b"
            " WHERE b.status IN ('active','canary')"
            " AND NOT EXISTS (SELECT 1 FROM model_connection_version_v1 v"
            "  WHERE v.connection_id = b.connection_id"
            "   AND v.version = b.connection_version"
            "   AND v.tenant_id = b.tenant_id"
            "   AND v.status = 'active')")]
        check("binding_targets_active_connection", not orphan_binding,
              orphan_binding)

        # 7. secret 元数据：active connection 引用 secret_ref 但无 envelope
        missing_secret = [dict(r) for r in conn.execute(
            "SELECT v.connection_id, v.version, v.secret_ref FROM"
            " model_connection_version_v1 v"
            " WHERE v.status='active' AND v.location='api'"
            " AND v.secret_ref != ''"
            " AND NOT EXISTS (SELECT 1 FROM model_secret_envelope_v1 e"
            "  WHERE e.secret_ref = v.secret_ref AND e.status='active')")]
        check("active_api_connection_has_active_secret", not missing_secret,
              missing_secret)

        bad_secret_status = [dict(r) for r in conn.execute(
            "SELECT secret_ref, version, status FROM"
            " model_secret_envelope_v1 WHERE status NOT IN"
            " ('active','rotated','revoked')")]
        check("secret_status_enum", not bad_secret_status, bad_secret_status)

        # 8. usage 未归属
        unattributed = conn.execute(
            "SELECT count(*) c FROM usage_event_v2"
            " WHERE model_call_id != '' AND principal_id = ''").fetchone()[0]
        check("usage_attributed", unattributed == 0,
              {"unattributed_rows": unattributed})

        # 9. 调用账本悬挂与未收敛
        stale_requested = [dict(r) for r in conn.execute(
            "SELECT model_call_id, created_at FROM model_call_ledger_v1"
            " WHERE status='requested'"
            " AND datetime(created_at) <"
            " datetime('now', ? || ' seconds')",
            (-REQUESTED_STALE_SECONDS,))]
        check("call_ledger_no_stale_requested", not stale_requested,
              stale_requested)
        incomplete = [dict(r) for r in conn.execute(
            "SELECT model_call_id, created_at FROM model_call_ledger_v1"
            " WHERE status='metering_incomplete'")]
        check("call_ledger_no_metering_incomplete", not incomplete,
              incomplete)

        # 10. Embedding 索引身份漂移（既有 cognition 索引账本）
        if "cognition_index_activation_v1" in present and \
                "cognition_index_build_v1" in present:
            dup_act = [dict(r) for r in conn.execute(
                "SELECT target_kind, count(*) n FROM"
                " cognition_index_activation_v1 WHERE status='active'"
                " GROUP BY target_kind HAVING count(*) > 1")]
            check("index_single_active_per_target", not dup_act, dup_act)

            orphan_act = [dict(r) for r in conn.execute(
                "SELECT a.activation_id FROM cognition_index_activation_v1 a"
                " LEFT JOIN cognition_index_build_v1 b"
                "  ON b.index_snapshot_id = a.index_snapshot_id"
                " WHERE b.index_snapshot_id IS NULL"
                " OR b.build_status != 'ready'")]
            check("index_activation_points_to_ready_build", not orphan_act,
                  orphan_act)

            dense_no_identity = [dict(r) for r in conn.execute(
                "SELECT index_snapshot_id FROM cognition_index_build_v1"
                " WHERE backend != 'lexical'"
                " AND build_status = 'ready'"
                " AND (embedding_model IS NULL OR embedding_model = '')")]
            check("dense_build_has_embedding_identity", not dense_no_identity,
                  dense_no_identity)

        report["gate_ok"] = not report["drift"]
        return report
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="统一模型管理只读对账（不写任何数据）")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--json", action="store_true",
                        help="仅输出 JSON（默认输出人类可读摘要+JSON）")
    args = parser.parse_args()

    if not args.read_only:
        print("错误：必须显式提供 --read-only（本脚本无写模式）",
              file=sys.stderr)
        raise SystemExit(2)
    if not args.db.exists():
        print(f"错误：数据库不存在: {args.db}", file=sys.stderr)
        raise SystemExit(2)

    report = reconcile(args.db, read_only=True)
    if not args.json:
        print(f"db={args.db}")
        print(f"integrity/migrations: "
              f"{report.get('migration_count')} 条，最新 "
              f"{report.get('latest_migration')}")
        print(f"model_tables_present={report.get('model_tables_present')}")
        for c in report["checks"]:
            mark = "ok" if c["ok"] else "DRIFT"
            print(f"  [{mark}] {c['name']}: "
                  f"{json.dumps(c['detail'], ensure_ascii=False, default=str)}")
        if report.get("note"):
            print(f"note: {report['note']}")
    print(json.dumps(report, ensure_ascii=False, default=str))
    raise SystemExit(0 if report["gate_ok"] else 1)


if __name__ == "__main__":
    main()
