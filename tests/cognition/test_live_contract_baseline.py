"""Task 1（G0）：只读基线与禁止行为锁定测试（当前基线应为绿）。

锁定内容：
1. 六张旧事实表存在，且任何迁移不得 DROP/RENAME 它们（追加式迁移纪律）；
2. Blackboard/不可变账本触发器在位（append-only 不被后续迁移移除）；
3. `.superpowers/`、training-data/、recognition-models/、runtime/、模型与
   数据集符号链接目录永不进入 git stage；
4. 现场运行库（若存在）integrity=ok 且关键认知表计数可只读复核。

这些测试不写任何运行库；仅使用 tmp DB 与 `git` 只读命令。
"""
from __future__ import annotations

import re
import sqlite3
import subprocess
from pathlib import Path

import pytest

from src.platform.data.store import MIGRATIONS, PlatformStore

REPO_ROOT = Path(__file__).resolve().parents[2]

# 旧事实表：认知内核收敛期间只读兼容，禁止 drop/rename（任务书 Task 1）。
LEGACY_TABLES = (
    "agent_manifest_v1",
    "agent_definition_v1",
    "memory_entry_v1",
    "agent_memory_v1",
    "knowledge_document_v1",
    "agent_asset_v1",
)

# 永不进入版本控制的资产目录（实体或符号链接）。
PROTECTED_PREFIXES = (
    ".superpowers/",
    "training-data/",
    "recognition-models/",
    "runtime/",
    ".models/",
    ".kb/",
    ".platform/",
    ".datasets/",
    ".datasets_nextgen/",
    ".training_data/",
    ".eval/",
    ".sam_checkpoints/",
)


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


class TestLegacyTablesFrozen:
    def test_legacy_tables_exist_on_fresh_store(self, store):
        names = {r["name"] for r in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for t in LEGACY_TABLES:
            assert t in names, f"旧表 {t} 必须存在（只读兼容，不得删除）"

    def test_no_migration_drops_or_renames_legacy_tables(self):
        """追加式迁移纪律：对任一旧表的 DROP/RENAME 都使基线失败。

        正则必须覆盖引号/括号/反引号标识符与 schema 限定名
        （SQLAlchemy/Alembic 生成的 DDL 默认带引号）。
        """
        q = r'(?:"|`|\[)?'  # 可选开引号
        qe = r'(?:"|`|\])?'  # 可选闭引号
        for t in LEGACY_TABLES:
            pats = (
                rf"DROP\s+TABLE\s+(IF\s+EXISTS\s+)?"
                rf"(main\s*\.\s*)?{q}{t}{qe}\b",
                rf"ALTER\s+TABLE\s+(main\s*\.\s*)?{q}{t}{qe}\s+RENAME",
            )
            for name, sql in MIGRATIONS:
                for pat in pats:
                    assert re.search(pat, sql, re.IGNORECASE) is None, (
                        f"迁移 {name} 不得 DROP/RENAME 旧表 {t}")

    def test_no_migration_drops_immutability_triggers(self):
        """不可变账本的守护触发器不得被后续迁移移除/替换。"""
        guarded = ("blackboard_event_v1", "event_envelope_v1",
                   "usage_event_v2", "evidence_bundle_v1")
        for t in guarded:
            pat = rf"DROP\s+TRIGGER\s+(IF\s+EXISTS\s+)?{t}_no_"
            for name, sql in MIGRATIONS:
                assert re.search(pat, sql, re.IGNORECASE) is None, (
                    f"迁移 {name} 不得 DROP 表 {t} 的不可变触发器")

    def test_blackboard_append_only_triggers_survive(self, store):
        """blackboard_event_v1 的禁 DELETE/UPDATE 触发器必须在位。"""
        store._conn.execute(
            "INSERT INTO blackboard_event_v1 (id, by, by_kind, event_type,"
            " payload_json, evidence_json, supersedes, created_at)"
            " VALUES ('e1','t','agent','Note','{}','[]',NULL,"
            " '2026-01-01T00:00:00+00:00')")
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute("DELETE FROM blackboard_event_v1")
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute(
                "UPDATE blackboard_event_v1 SET payload_json='{}'")

    def test_event_usage_evidence_ledgers_append_only(self, store):
        """统一控制平面三账本必须做行为级验证（触发器真的拦住
        DELETE/UPDATE），不能只检查触发器名字存在。"""
        conn = store._conn
        conn.execute(
            "INSERT INTO event_envelope_v1 (event_id, event_type,"
            " occurred_at) VALUES ('ev-1','t.test','2026-01-01T00:00:00Z')")
        conn.execute(
            "INSERT INTO usage_event_v2 (usage_id, unit, quantity,"
            " occurred_at) VALUES ('u-1','call',1,'2026-01-01T00:00:00Z')")
        conn.execute(
            "INSERT INTO evidence_bundle_v1 (evidence_id, kind, created_at)"
            " VALUES ('e-1','test','2026-01-01T00:00:00Z')")
        for sql in ("DELETE FROM event_envelope_v1",
                    "UPDATE event_envelope_v1 SET event_type='x'",
                    "DELETE FROM usage_event_v2",
                    "UPDATE usage_event_v2 SET quantity=9",
                    "DELETE FROM evidence_bundle_v1",
                    "UPDATE evidence_bundle_v1 SET kind='x'"):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(sql)


def _git(*args: str) -> str:
    out = subprocess.run(
        ("git", "-c", "core.quotePath=false", *args), cwd=REPO_ROOT,
        capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        pytest.skip(f"git 不可用或非 git 检出: {out.stderr[:120]}")
    return out.stdout


def _in_protected(path: str) -> bool:
    """大小写折叠匹配：Linux 大小写敏感文件系统上变体目录同样锁定。"""
    p = path.lower()
    return any(p.startswith(pre.lower()) for pre in PROTECTED_PREFIXES)


class TestAssetBoundariesNeverStaged:
    def test_tracked_files_never_inside_protected_dirs(self):
        """受保护目录内只允许 README 占位；数据/模型/SQLite 零跟踪。"""
        tracked = _git("ls-files").splitlines()
        bad = [p for p in tracked if _in_protected(p)
               and not p.endswith("README.md")]
        assert bad == [], f"受保护资产被纳入版本控制: {bad[:5]}"

    def test_untracked_worktree_does_not_expose_protected_dirs(self):
        """git status 的 untracked 列表不得把受保护目录整体带出。"""
        lines = _git("status", "--porcelain").splitlines()
        untracked = [l[3:].strip() for l in lines if l.startswith("??")]
        bad = [p for p in untracked
               if any(p.rstrip("/").lower() == pre.lower().rstrip("/")
                      for pre in PROTECTED_PREFIXES)]
        assert bad == [], f"受保护目录出现在 untracked: {bad[:5]}"

    def test_gitignore_covers_protected_symlink_aliases(self):
        gi = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        entries = {l.strip().lower() for l in gi.splitlines()
                   if l.strip() and not l.strip().startswith("#")}
        for entry in (".kb/", ".platform/", ".models/", ".eval/"):
            assert entry in entries, f".gitignore 缺少 {entry}"

    def test_superpowers_dir_absent_or_ignored(self):
        """迁移仓库当前无 .superpowers/；若未来出现必须被 ignore。"""
        sp = REPO_ROOT / ".superpowers"
        if sp.exists():
            out = subprocess.run(
                ("git", "check-ignore", "-q", ".superpowers/"),
                cwd=REPO_ROOT, capture_output=True)
            assert out.returncode == 0, ".superpowers/ 存在但未被 ignore"


class TestLiveBaselineReadOnly:
    """现场运行库只读复核（文件缺失时 skip，保持 hermetic 可移植）。"""

    @pytest.fixture()
    def live_conn(self):
        db = REPO_ROOT / "runtime" / "platform" / "platform.sqlite"
        if not db.exists():
            pytest.skip("现场库不存在（非迁移项目环境）")
        conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        yield conn
        conn.close()

    def test_integrity_ok(self, live_conn):
        assert live_conn.execute(
            "PRAGMA integrity_check").fetchone()[0] == "ok"

    def test_cognition_baseline_counts_readable(self, live_conn):
        for t in LEGACY_TABLES + ("blackboard_event_v1",):
            n = live_conn.execute(
                f"SELECT count(*) c FROM {t}").fetchone()["c"]
            assert isinstance(n, int) and n >= 0, f"{t} 计数不可读"
