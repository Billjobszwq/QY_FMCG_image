#!/usr/bin/env python3
"""Task 13（G10）：旧记忆/知识表迁移脚本（dry-run 默认；--apply 需备份）。

对以下旧表输出逐行迁移决策 + 行级 hash：
- agent_memory_v1（L0-L4 → L1/L2/L3/quarantine）
- memory_entry_v1（→ L2 candidate）
- knowledge_document_v1（→ knowledge_item draft）
- agent_asset_v1（kind=skill → skill draft；kind=kb/prompt 记录但不迁）

安全：
- 默认 --dry-run：只输出决策，不写任何表；
- --apply：先校验 runtime/platform/backups/ 存在平台备份，否则拒绝；
  以读写模式打开 DB（应用待应用迁移），逐行写入新认知表（draft/candidate，
  不直接发布）；不 DELETE/UPDATE 任何旧表行；
- 不 drop 旧表（回滚=不应用新写；旧表只读保留）。

用法：
  python scripts/cognition_migrate_legacy.py --dry-run [--db PATH]
  python scripts/cognition_migrate_legacy.py --apply --yes-i-have-backup
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.platform.cognition.memory.legacy import map_agent_memory_level  # noqa: E402

DEFAULT_DB = REPO_ROOT / "runtime" / "platform" / "platform.sqlite"
BACKUP_DIR = REPO_ROOT / "runtime" / "platform" / "backups"


class MigrationNotAuthorized(Exception):
    """迁移未获授权（dry-run 缺省 / apply 缺备份 / 预检失败）。"""


@dataclass(frozen=True)
class MigrationPreflight:
    """只读迁移预检结果（R2-P0-01）。

    只允许 readonly sqlite3；禁止构造 PlatformStore（会设 WAL 并自动
    apply_migrations）。预检失败时数据库 bytes/size/migration/journal
    必须完全不变。
    """
    db_path: Path
    db_sha256: str
    db_size: int
    integrity: str
    migration_count: int
    latest_migration: str
    backup_path: str | None
    backup_sha256: str | None
    backup_integrity: str | None
    allowed: bool
    reasons: tuple[str, ...]


def _validate_backup(backup_dir: Path,
                     target_migrations: set[str]
                     ) -> tuple[bool, tuple[str, str, str] | None,
                                list[str]]:
    """校验备份：存在、非空、integrity ok、目标身份匹配。

    目标身份匹配 = 备份的 schema_migrations 是目标 DB 的子集（同一
    迁移谱系）；否则视为另一个数据库的备份，不能用于本目标。
    """
    reasons: list[str] = []
    backup_dir = Path(backup_dir)
    if not backup_dir.exists():
        return False, None, [f"备份目录不存在: {backup_dir}"]
    cands = sorted(backup_dir.glob("platform_pre_cognition_*.sqlite"))
    if not cands:
        return False, None, [
            f"未在 {backup_dir} 找到 platform_pre_cognition_* 备份"]
    for b in cands:
        if b.stat().st_size == 0:
            reasons.append(f"备份为空，跳过: {b}")
            continue
        try:
            conn = sqlite3.connect(b.resolve().as_uri() + "?mode=ro",
                                     uri=True)
            integrity = conn.execute(
                "PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                reasons.append(f"备份 integrity={integrity}: {b}")
                conn.close()
                continue
            bmigs = {r[0] for r in conn.execute(
                "SELECT name FROM schema_migrations")}
            conn.close()
            if not bmigs.issubset(target_migrations):
                reasons.append(
                    f"备份迁移谱系与目标不匹配（非同一 DB）: {b}")
                continue
            sha = hashlib.sha256(b.read_bytes()).hexdigest()
            return True, (str(b), sha, integrity), []
        except sqlite3.Error as e:
            reasons.append(f"备份读取失败: {b}: {e}")
            continue
    return False, None, reasons or ["无有效备份"]


def preflight_migration(db_path: Path, backup_dir: Path, *,
                        require_backup: bool) -> MigrationPreflight:
    """只读预检：读取目标 DB 的 hash/integrity/migration，并在
    require_backup 时校验备份。全程 mode=ro，不构造 PlatformStore。"""
    db_path = Path(db_path)
    reasons: list[str] = []
    if not db_path.exists():
        return MigrationPreflight(
            db_path=db_path, db_sha256="", db_size=0, integrity="",
            migration_count=0, latest_migration="", backup_path=None,
            backup_sha256=None, backup_integrity=None, allowed=False,
            reasons=("目标数据库不存在",))
    db_sha = hashlib.sha256(db_path.read_bytes()).hexdigest()
    db_size = db_path.stat().st_size
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro",
                           uri=True)
    conn.row_factory = sqlite3.Row
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    migs = [r["name"] for r in conn.execute(
        "SELECT name FROM schema_migrations ORDER BY id")]
    conn.close()
    if integrity != "ok":
        reasons.append(f"目标 DB integrity={integrity}")
    backup_path = backup_sha = backup_integrity = None
    if require_backup:
        bok, binfo, breasons = _validate_backup(backup_dir, set(migs))
        if bok and binfo is not None:
            backup_path, backup_sha, backup_integrity = binfo
        else:
            reasons.extend(breasons)
    allowed = (integrity == "ok") and (
        (not require_backup) or (backup_path is not None))
    return MigrationPreflight(
        db_path=db_path, db_sha256=db_sha, db_size=db_size,
        integrity=integrity, migration_count=len(migs),
        latest_migration=(migs[-1] if migs else ""),
        backup_path=backup_path, backup_sha256=backup_sha,
        backup_integrity=backup_integrity, allowed=allowed,
        reasons=tuple(reasons))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_hash(row: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        row, sort_keys=True, ensure_ascii=False, default=str
    ).encode("utf-8")).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}-" + uuid.uuid4().hex[:14]


def _det_id(prefix: str, key: str) -> str:
    """确定性 ID（由 legacy 行派生）：apply 重跑幂等（评审 #T13-2）。"""
    return f"{prefix}-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def collect_decisions(conn) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for r in conn.execute(
            "SELECT * FROM agent_memory_v1 ORDER BY created_at"):
        row = dict(r)
        target, reason = map_agent_memory_level(row.get("level", ""))
        decisions.append({
            "table": "agent_memory_v1", "row_id": row["memory_id"],
            "level": row.get("level", ""), "target": target,
            "reason": reason, "row_hash": _row_hash(row)})
    for r in conn.execute(
            "SELECT * FROM memory_entry_v1 ORDER BY valid_from"):
        row = dict(r)
        decisions.append({
            "table": "memory_entry_v1", "row_id": row["id"],
            "level": row.get("level", ""),
            "target": "memory_l2_candidate",
            "reason": "旧 MemoryService 条目 → L2 candidate（需人工发布）",
            "row_hash": _row_hash(row)})
    for r in conn.execute(
            "SELECT * FROM knowledge_document_v1 ORDER BY created_at"):
        row = dict(r)
        decisions.append({
            "table": "knowledge_document_v1", "row_id": row["doc_id"],
            "level": "", "target": "knowledge_item_draft",
            "reason": "旧知识文档元数据 → knowledge draft（需补 span+审批）",
            "row_hash": _row_hash(row)})
    for r in conn.execute(
            "SELECT * FROM agent_asset_v1 WHERE kind='skill'"
            " ORDER BY created_at"):
        row = dict(r)
        decisions.append({
            "table": "agent_asset_v1", "row_id": row["asset_id"],
            "level": "skill", "target": "skill_definition_draft",
            "reason": "旧 skill 资产 → skill draft（需补 schema+评测+审批）",
            "row_hash": _row_hash(row)})
    return decisions


def apply_decisions(conn, decisions: list[dict[str, Any]]) -> dict[str, int]:
    """把决策写入新认知表（均为 draft/candidate，不直接发布）。

    幂等（评审 #T13-2）：新表行用 legacy 行派生的确定性 ID + INSERT
    OR IGNORE，重跑不产生重复（append-only 表重复无法清理）。
    L3/quarantine 候选也落账（评审 #T13-4），不静默丢弃。
    """
    migrated = 0
    skipped = 0
    for d in decisions:
        target = d["target"]
        if target == "memory_l1_event":
            src = dict(conn.execute(
                "SELECT * FROM agent_memory_v1 WHERE memory_id=?",
                (d["row_id"],)).fetchone())
            event_id = _det_id("l1mig", src["memory_id"])
            cur = conn.execute(
                "INSERT OR IGNORE INTO memory_l1_event (event_id,"
                " task_id, actor_id, actor_kind, event_type, payload_json,"
                " occurred_at, ingested_at, permission_tags_json,"
                " retention_class) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (event_id, "", src.get("agent_id", ""), "agent",
                 "legacy_migration", json.dumps(
                     {"legacy_memory_id": src["memory_id"],
                      "content": src.get("content", "")},
                     ensure_ascii=False),
                 src.get("created_at", _now()), _now(),
                 json.dumps(["legacy"]), "permanent"))
            migrated += cur.rowcount
            skipped += (1 - cur.rowcount)
        elif target == "memory_l2_candidate":
            if d["table"] == "agent_memory_v1":
                src = dict(conn.execute(
                    "SELECT * FROM agent_memory_v1 WHERE memory_id=?",
                    (d["row_id"],)).fetchone())
                text = src.get("content", "")
                created = src.get("created_at", _now())
            else:
                src = dict(conn.execute(
                    "SELECT * FROM memory_entry_v1 WHERE id=?",
                    (d["row_id"],)).fetchone())
                text = src.get("text", "")
                created = src.get("valid_from", _now())
            episode_id = _det_id("l2mig", d["row_hash"])
            cur = conn.execute(
                "INSERT OR IGNORE INTO memory_l2_episode (episode_id,"
                " task_id, period_start, period_end, solution, result,"
                " source_hash, consolidator_version, confidence, status,"
                " permission_tags_json, created_by, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?, 'candidate',?,?,?)",
                (episode_id, "", created, created, text, "",
                 d["row_hash"], "legacy_migration@1", 0.5,
                 json.dumps(["legacy"]), "legacy_migration", created))
            migrated += cur.rowcount
            skipped += (1 - cur.rowcount)
        elif target == "memory_l3_candidate":
            src = dict(conn.execute(
                "SELECT * FROM agent_memory_v1 WHERE memory_id=?",
                (d["row_id"],)).fetchone())
            methodology_id = _det_id("l3mig", src["memory_id"])
            cur = conn.execute(
                "INSERT OR IGNORE INTO memory_l3_methodology_version"
                " (methodology_id, version, statement, confidence,"
                " source_l2_ids_json, supporting_event_count, status,"
                " created_by, created_at, tenant_id, data_scope)"
                " VALUES (?,1,?,0.5,'[]',0,'candidate',?,?,'local',"
                " 'operational')",
                (methodology_id, src.get("content", "")[:500],
                 "legacy_migration", src.get("created_at", _now())))
            migrated += cur.rowcount
            skipped += (1 - cur.rowcount)
        elif target == "quarantine_candidate":
            # 无法确定含义的层级 → 以 conflict 状态落 L2 隔离，留待裁决
            src = dict(conn.execute(
                "SELECT * FROM agent_memory_v1 WHERE memory_id=?",
                (d["row_id"],)).fetchone())
            episode_id = _det_id("l2quar", src["memory_id"])
            cur = conn.execute(
                "INSERT OR IGNORE INTO memory_l2_episode (episode_id,"
                " task_id, period_start, period_end, solution, result,"
                " source_hash, consolidator_version, confidence, status,"
                " permission_tags_json, created_by, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,0.0,'conflict',?,?,?)",
                (episode_id, "", src.get("created_at", _now()),
                 src.get("created_at", _now()),
                 f"[quarantine] {src.get('content', '')[:300]}",
                 f"无法确定层级 {src.get('level', '')}，隔离待裁决",
                 d["row_hash"], "legacy_migration@1",
                 json.dumps(["legacy", "quarantine"]),
                 "legacy_migration", src.get("created_at", _now())))
            migrated += cur.rowcount
            skipped += (1 - cur.rowcount)
        elif target == "knowledge_item_draft":
            src = dict(conn.execute(
                "SELECT * FROM knowledge_document_v1 WHERE doc_id=?",
                (d["row_id"],)).fetchone())
            knowledge_id = _det_id("kbmig", src["doc_id"])
            # effective_from 取 created_at（expires_at 是失效期，不得
            # 写入生效期，评审 #T13-1）；expires_at 为 NULL 时不崩。
            effective_from = src.get("created_at") or _now()
            cur = conn.execute(
                "INSERT OR IGNORE INTO knowledge_item_version"
                " (knowledge_id, version, type, title, body, summary,"
                " owner, effective_from, status, permission_tags_json,"
                " source_span_ids_json, created_by, created_at,"
                " tenant_id, customer_id, data_scope)"
                " VALUES (?,1,'policy',?,?,?,?,?, 'draft','[]','[]',?,?,"
                " 'local',?, 'operational')",
                (knowledge_id, src.get("title", ""), "",
                 src.get("title", ""), src.get("kb_name", ""),
                 effective_from, "legacy_migration",
                 src.get("created_at", _now()),
                 src.get("customer_id", "")))
            migrated += cur.rowcount
            skipped += (1 - cur.rowcount)
        elif target == "skill_definition_draft":
            src = dict(conn.execute(
                "SELECT * FROM agent_asset_v1 WHERE asset_id=? AND"
                " kind='skill'", (d["row_id"],)).fetchone())
            skill_id = _det_id("skmig", src["asset_id"])
            cur = conn.execute(
                "INSERT OR IGNORE INTO skill_definition_version"
                " (skill_id, version, name, description, skill_type,"
                " input_schema_json, output_schema_json, execution_ref,"
                " risk_level, status, permission_tags_json,"
                " source_refs_json, created_by, created_at, tenant_id,"
                " data_scope) VALUES (?,1,?,?,'curated','{}','{}','', "
                "'medium','draft','[]',?,?,?,'local','operational')",
                (skill_id, src.get("name", ""),
                 src.get("content", "")[:200],
                 json.dumps([f"legacy:{src['asset_id']}"]),
                 "legacy_migration", src.get("created_at", _now())))
            migrated += cur.rowcount
            skipped += (1 - cur.rowcount)
    conn.commit()
    return {"migrated": migrated, "skipped_duplicate": skipped}


def run_migration(store: Any, *, dry_run: bool,
                  confirm_backup: bool = False,
                  backup_info: str | None = None) -> dict[str, Any]:
    """搬运 legacy rows。备份校验由调用方（main 的 preflight）完成；
    此处仅在 apply 时要求 confirm_backup 与已验证的 backup_info。"""
    conn = store._conn
    if not dry_run:
        if not confirm_backup:
            raise MigrationNotAuthorized(
                "--apply 需要 --yes-i-have-backup（先备份平台 DB）")
        if not backup_info:
            raise MigrationNotAuthorized(
                "备份未经只读预检（preflight）验证，拒绝迁移")
    decisions = collect_decisions(conn)
    counts: dict[str, int] = {}
    for d in decisions:
        counts[d["target"]] = counts.get(d["target"], 0) + 1
    report: dict[str, Any] = {"dry_run": dry_run, "decisions": decisions,
                              "counts": counts}
    if not dry_run:
        report["backup"] = backup_info
        report.update(apply_decisions(conn, decisions))
    return report


def main() -> None:
    ap = argparse.ArgumentParser(
        description="cognition legacy migration (dry-run default)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--yes-i-have-backup", action="store_true")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--backup-dir", default=str(BACKUP_DIR))
    args = ap.parse_args()

    db_path = Path(args.db)
    backup_dir = Path(args.backup_dir)
    dry_run = not args.apply  # 默认 dry-run

    # R2-P0-01：先做只读预检（不构造 PlatformStore，不设 WAL，不迁移）。
    preflight = preflight_migration(db_path, backup_dir,
                                    require_backup=(not dry_run))
    if not preflight.allowed:
        print(json.dumps({"error": "迁移预检失败",
                          "reasons": list(preflight.reasons),
                          "db_sha256": preflight.db_sha256,
                          "migration_count": preflight.migration_count,
                          "latest_migration": preflight.latest_migration,
                          "backup_path": preflight.backup_path},
                         ensure_ascii=False))
        raise SystemExit(2)

    if dry_run:
        # 保持只读：mode=ro 连接，不应用 schema、不写任何表
        class _RO:
            def __init__(self, path: Path) -> None:
                self._conn = sqlite3.connect(
                    path.resolve().as_uri() + "?mode=ro", uri=True)
                self._conn.row_factory = sqlite3.Row
        report = run_migration(_RO(db_path), dry_run=True)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    # apply：预检已确认备份有效，才构造可写 Store 并显式应用迁移
    from src.platform.data.store import PlatformStore
    store = PlatformStore(db_path)
    try:
        report = run_migration(store, dry_run=False,
                               confirm_backup=True,
                               backup_info=preflight.backup_path)
    except MigrationNotAuthorized as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        raise SystemExit(2)
    # 迁移后 reconcile / integrity
    post = preflight_migration(db_path, backup_dir, require_backup=False)
    report["post_integrity"] = post.integrity
    report["post_migration_count"] = post.migration_count
    report["post_db_sha256"] = post.db_sha256
    print(json.dumps(report, ensure_ascii=False, indent=2))
    store.close()


if __name__ == "__main__":
    main()
