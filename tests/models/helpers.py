"""统一模型管理测试共享助手。

原则（M1/G0）：
- live DB 全程只读：复制一律经 ``mode=ro`` 源连接 + SQLite Online Backup API，
  不直接 shutil.copy（避免未 checkpoint 的 WAL 帧造成副本不一致）。
- 副本归测试所有：复制后 checkpoint + 切 DELETE journal，得到干净非 WAL 副本，
  使“只读操作不产生 WAL/SHM”断言可靠。
- 任何 helper 不得向 live DB 写入，也不得在 live 路径上构造 PlatformStore。
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_DB = REPO_ROOT / "runtime" / "platform" / "platform.sqlite"

# 文档冻结时（2026-08-21）live SHA-256；合同要求本轮 live hash 不变。
LIVE_DB_DOC_SHA256 = (
    "2306a030cf1128a36d2432e9fe78ca623ac0925f73710dc428630d05a806f109"
)

# 模型测试必须隔离的 provider/secret 环境（先例：DEC-105、ISS-011）。
PROVIDER_ENV_KEYS = (
    "TAAS_MODEL_SECRET_KEK",
    "TAAS_EMBEDDING_ENDPOINT",
    "TAAS_EMBEDDING_MODEL",
    "TAAS_EMBEDDING_API_KEY",
    "TAAS_OMLX_API_KEY",
    "OMLX_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def live_db_sha256() -> str | None:
    if not LIVE_DB.exists():
        return None
    return sha256_file(LIVE_DB)


def fingerprint(db: Path) -> dict:
    """bytes/hash/size/migration count/latest/journal 文件全量指纹。"""
    data = db.read_bytes()
    fp = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "wal_exists": Path(str(db) + "-wal").exists(),
        "shm_exists": Path(str(db) + "-shm").exists(),
    }
    try:
        conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
        fp["migration_count"] = conn.execute(
            "SELECT count(*) c FROM schema_migrations").fetchone()[0]
        fp["latest_migration"] = conn.execute(
            "SELECT name FROM schema_migrations ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        conn.close()
    except sqlite3.Error:
        fp["migration_count"] = None
        fp["latest_migration"] = None
    return fp


def table_row_counts(db: Path) -> dict[str, int]:
    """只读统计所有用户表行数（迁移无损性验证用）。"""
    conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
        " AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    counts = {}
    for name in names:
        counts[name] = conn.execute(
            f"SELECT count(*) FROM [{name}]").fetchone()[0]
    conn.close()
    return counts


def copy_live_database(tmp_path: Path, *, name: str = "copy.sqlite") -> Path:
    """把 live DB 只读复制到 tmp（sqlite backup API），并归一化为
    DELETE journal 的干净副本。live 文件零写入。"""
    import pytest

    if not LIVE_DB.exists():
        pytest.skip("live DB 不存在，无法制作副本")
    dst = tmp_path / name
    src = sqlite3.connect(
        LIVE_DB.resolve().as_uri() + "?mode=ro", uri=True)
    target = sqlite3.connect(str(dst))
    try:
        src.backup(target)
    finally:
        target.close()
        src.close()
    conn = sqlite3.connect(str(dst))
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    for suffix in ("-wal", "-shm"):
        p = Path(str(dst) + suffix)
        if p.exists():
            p.unlink()
    return dst


def copy_database_at_068(tmp_path: Path) -> Path:
    """复制当前 live（文档基线为 068）副本；若 live 已升级仍如实复制。"""
    return copy_live_database(tmp_path)
