"""R2-02（R2-P0-01）：迁移备份预检必须先于任何可写连接与 schema migration。

红测试（修复前应按预期失败）：
- 从 061 备份复制到 tmp 副本，记录 fingerprint（bytes/hash/size/
  migration count/journal 文件）；
- 把备份目录指向不存在位置执行 ``--apply --yes-i-have-backup``；
- 断言进程 exit 2 且数据库 fingerprint 完全不变。

修复前的错误顺序是：CLI 构造 PlatformStore → 自动 apply_migrations
（061→068）→ run_migration 才检查备份。因此备份守卫拒绝时 schema 已被
修改，migration_count 从 61 变 68，fingerprint 变化 → 本测试红。
"""
from __future__ import annotations

import hashlib
import importlib.util
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cognition_migrate_legacy.py"
BACKUP_GLOB = "platform_pre_cognition_*.sqlite"


def _backup_dir() -> Path:
    return REPO_ROOT / "runtime" / "platform" / "backups"


def _find_061_backup() -> Path | None:
    bd = _backup_dir()
    if not bd.exists():
        return None
    cands = sorted(bd.glob(BACKUP_GLOB))
    for c in cands:
        try:
            conn = sqlite3.connect(c.resolve().as_uri() + "?mode=ro",
                                     uri=True)
            n = conn.execute(
                "SELECT count(*) c FROM schema_migrations").fetchone()[0]
            conn.close()
            if n == 61:
                return c
        except sqlite3.Error:
            continue
    return None


def _declared_latest() -> tuple[int, str]:
    """返回当前 store 声明的迁移总数与最新名（不写死 068，
    后续纯追加迁移如 069 CAS 不应使本测试变红）。"""
    from src.platform.data.store import MIGRATIONS
    return len(MIGRATIONS), MIGRATIONS[-1][0]


def _load_module():
    name = "cognition_migrate_legacy_under_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclass 需要能从 sys.modules 解析模块
    spec.loader.exec_module(mod)
    return mod


def _fingerprint(db: Path) -> dict:
    """bytes/hash/size/migration count/journal 文件全量指纹。"""
    data = db.read_bytes()
    fp = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "wal_exists": Path(str(db) + "-wal").exists(),
        "shm_exists": Path(str(db) + "-shm").exists(),
    }
    try:
        conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro",
                                 uri=True)
        fp["migration_count"] = conn.execute(
            "SELECT count(*) c FROM schema_migrations").fetchone()[0]
        fp["latest_migration"] = conn.execute(
            "SELECT name FROM schema_migrations ORDER BY id DESC"
            " LIMIT 1").fetchone()[0]
        conn.close()
    except sqlite3.Error:
        fp["migration_count"] = None
        fp["latest_migration"] = None
    return fp


def _copy_pre_062(tmp_path: Path) -> Path:
    """复制 061 备份并归一化为 DELETE journal。

    061 备份是从 live WAL 库 backup 出来的，文件头仍是 WAL 模式；
    对 WAL 库做只读打开 SQLite 也会生成 -shm（WAL 读取簿记），这并非
    迁移脚本的行为。为让“dry-run 不生成 WAL/SHM”这一断言针对干净
    的非 WAL 副本成立，先把副本 checkpoint 并切到 DELETE journal
    （这是测试 fixture 归一化，副本归测试所有）。
    """
    src = _find_061_backup()
    if src is None:
        pytest.skip("无 061 平台备份可供迁移预检测试")
    db = tmp_path / "pre.sqlite"
    shutil.copy(src, db)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    # checkpoint 后清掉残留 journal 文件，得到干净非 WAL 副本
    for j in (str(db) + "-wal", str(db) + "-shm"):
        p = Path(j)
        if p.exists():
            p.unlink()
    return db


def test_apply_guard_rejects_before_store_and_schema_migrations(
        tmp_path, monkeypatch):
    """备份目录无效 → exit 2，且 DB 指纹（含 migration 数）完全不变。"""
    db = _copy_pre_062(tmp_path)
    before = _fingerprint(db)
    assert before["migration_count"] == 61, "前置：副本应为 061"

    mod = _load_module()
    # 把备份目录指向不存在位置：预检必须拒绝
    monkeypatch.setattr(mod, "BACKUP_DIR", tmp_path / "missing_backup")
    monkeypatch.setattr(
        sys, "argv",
        ["cognition_migrate_legacy", "--apply", "--yes-i-have-backup",
         "--db", str(db)])
    with pytest.raises(SystemExit) as ei:
        mod.main()
    assert ei.value.code == 2, "预检失败必须 exit 2"

    after = _fingerprint(db)
    assert after == before, (
        "备份守卫拒绝时数据库不得被修改（含 schema migration）："
        f"before={before} after={after}")


def test_apply_guard_rejects_without_confirm_flag(tmp_path, monkeypatch):
    """--apply 但未提供 --yes-i-have-backup → exit 2，DB 不变。"""
    db = _copy_pre_062(tmp_path)
    before = _fingerprint(db)
    mod = _load_module()
    monkeypatch.setattr(mod, "BACKUP_DIR", tmp_path / "missing_backup")
    monkeypatch.setattr(
        sys, "argv",
        ["cognition_migrate_legacy", "--apply", "--db", str(db)])
    with pytest.raises(SystemExit) as ei:
        mod.main()
    assert ei.value.code == 2
    assert _fingerprint(db) == before


def test_dry_run_is_readonly_and_creates_no_journal(tmp_path, monkeypatch):
    """--dry-run 不创建 WAL/SHM，不应用 schema，DB 指纹不变。"""
    db = _copy_pre_062(tmp_path)
    before = _fingerprint(db)
    mod = _load_module()
    monkeypatch.setattr(
        sys, "argv",
        ["cognition_migrate_legacy", "--dry-run", "--db", str(db)])
    mod.main()  # dry-run 正常退出（exit 0）
    after = _fingerprint(db)
    assert after == before, "dry-run 必须保持 DB 完全只读"
    assert not Path(str(db) + "-wal").exists()
    assert not Path(str(db) + "-shm").exists()


def _seed_legacy_rows(db: Path) -> None:
    """向 061 副本灌入 legacy 行（L0-L4 + memory_entry），供 apply 搬运。"""
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    for i, lvl in enumerate(("L0", "L1", "L2", "L3", "L4")):
        conn.execute(
            "INSERT INTO agent_memory_v1 (memory_id, agent_id, level,"
            " content, acl_json, supersedes, status, created_by,"
            " created_at) VALUES (?,?,?,?,?,?, 'active','tester',"
            " '2026-08-01T00:00:00Z')",
            (f"mem-{i}", "supervisor", lvl, f"旧记忆 {lvl}", "{}", None))
    conn.execute(
        "INSERT INTO memory_entry_v1 (id, level, text, scope, acl_json,"
        " confidence, evidence_json, valid_from, valid_to, retention,"
        " supersedes, version) VALUES ('me-1','project','经验条目',"
        " 'project','[\"project:p1\"]',0.8,'[]',"
        " '2026-08-01T00:00:00Z',NULL,'project_lifetime',NULL,1)")
    conn.commit()
    conn.close()


def _setup_valid_backup(tmp_path: Path) -> Path:
    """在 tmp 备份目录放一个与目标同谱系的有效备份。"""
    src = _find_061_backup()
    bdir = tmp_path / "backup_dir"
    bdir.mkdir()
    shutil.copy(src, bdir / "platform_pre_cognition_test.sqlite")
    return bdir


def test_apply_with_valid_backup_migrates_to_068_and_is_idempotent(
        tmp_path, monkeypatch):
    """有效备份 → apply 迁移到 068 并搬运 legacy 行；二次 apply 幂等
    （migrated=0），旧表行数/hash 不变，L3/L4 映射不丢失。"""
    db = _copy_pre_062(tmp_path)
    _seed_legacy_rows(db)
    bdir = _setup_valid_backup(tmp_path)
    before_legacy_hashes = _legacy_row_hashes(db)

    mod = _load_module()
    monkeypatch.setattr(mod, "BACKUP_DIR", bdir)
    monkeypatch.setattr(
        sys, "argv",
        ["cognition_migrate_legacy", "--apply", "--yes-i-have-backup",
         "--db", str(db)])
    mod.main()  # 正常退出

    after = _fingerprint(db)
    expected_count, expected_latest = _declared_latest()
    assert after["migration_count"] == expected_count, (
        f"apply 后应迁移到最新 {expected_latest}")
    assert after["latest_migration"] == expected_latest
    # legacy 行未被修改（行数/hash 不变）
    assert _legacy_row_hashes(db) == before_legacy_hashes
    # 新表已搬运：L0/L1→l1，L2→l2 candidate，L3→l3 candidate，
    # L4→quarantine（conflict），memory_entry→l2 candidate
    conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    l1 = conn.execute("SELECT count(*) c FROM memory_l1_event").fetchone()["c"]
    l2 = conn.execute("SELECT count(*) c FROM memory_l2_episode").fetchone()["c"]
    l3 = conn.execute(
        "SELECT count(*) c FROM memory_l3_methodology_version").fetchone()["c"]
    assert l1 == 2, "L0+L1 → 2 条 memory_l1_event"
    # L2(candidate) + L4(quarantine conflict) + memory_entry(candidate) = 3
    assert l2 == 3, "L2 + L4(quarantine) + memory_entry → 3 条 memory_l2"
    assert l3 == 1, "L3 → 1 条 memory_l3 candidate"
    # L4 必须落 quarantine（conflict），不得映射为 L3
    quar = conn.execute(
        "SELECT count(*) c FROM memory_l2_episode WHERE status='conflict'"
    ).fetchone()["c"]
    assert quar == 1, "L4 未知层级 → quarantine/conflict"
    conn.close()

    # 二次 apply 幂等：migrated=0，指纹中新表行数不再增长
    monkeypatch.setattr(
        sys, "argv",
        ["cognition_migrate_legacy", "--apply", "--yes-i-have-backup",
         "--db", str(db)])
    mod.main()
    conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    assert conn.execute(
        "SELECT count(*) c FROM memory_l1_event").fetchone()["c"] == l1
    assert conn.execute(
        "SELECT count(*) c FROM memory_l2_episode").fetchone()["c"] == l2
    assert conn.execute(
        "SELECT count(*) c FROM memory_l3_methodology_version"
    ).fetchone()["c"] == l3
    conn.close()
    # legacy 行仍不变
    assert _legacy_row_hashes(db) == before_legacy_hashes


def _legacy_row_hashes(db: Path) -> dict:
    conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    am = [tuple(r) for r in conn.execute(
        "SELECT * FROM agent_memory_v1 ORDER BY memory_id")]
    me = [tuple(r) for r in conn.execute(
        "SELECT * FROM memory_entry_v1 ORDER BY id")]
    conn.close()
    import hashlib as _h
    return {
        "agent_memory_count": len(am),
        "memory_entry_count": len(me),
        "agent_memory_hash": _h.sha256(repr(am).encode()).hexdigest(),
        "memory_entry_hash": _h.sha256(repr(me).encode()).hexdigest(),
    }
