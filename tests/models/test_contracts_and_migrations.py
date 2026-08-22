"""M1（G0）：072–074 纯追加迁移、只读 preflight 与副本升级保护测试。

红测试（实现前应按预期失败）：
- 072/073/074 迁移尚不存在 → MIGRATIONS 断言失败；
- ``readonly_model_preflight`` / ``reconcile_model_management.py`` 尚未实现
  → collection/运行失败。

保护合同（合同 §四/§六、05 计划 M1）：
- live DB 全程只读，任何预检不得升级副本之外的东西；
- 新迁移只能纯追加（无 DROP/RENAME/DELETE/UPDATE 旧表）；
- live 068 副本按工作树序列升级到最新（074），apply 幂等、旧表行数不丢失；
- live hash 不变。
"""
from __future__ import annotations

import importlib.util
import os
import re
import sqlite3
import sys
from pathlib import Path

import pytest

from src.platform.data.store import MIGRATIONS, PlatformStore
from tests.models.helpers import (
    LIVE_DB,
    LIVE_DB_DOC_SHA256,
    PROVIDER_ENV_KEYS,
    copy_live_database,
    fingerprint,
    live_db_sha256,
    table_row_counts,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RECONCILE_SCRIPT = REPO_ROOT / "scripts" / "reconcile_model_management.py"

MODEL_MIGRATION_NAMES = [
    "072_model_management_core_v1",
    "073_model_secret_envelope_v1",
    "074_model_usage_metering_v1",
]

_MODEL_NAMES = set(MODEL_MIGRATION_NAMES)

# 纯追加纪律：新迁移 SQL 中禁止出现的破坏性 DDL/DML。
_FORBIDDEN_PATTERNS = (
    r"DROP\s+TABLE",
    r"DROP\s+INDEX",
    r"DROP\s+TRIGGER",
    r"ALTER\s+TABLE\s+\S+\s+RENAME",
    r"ALTER\s+TABLE\s+\S+\s+DROP\s+COLUMN",
    r"\bDELETE\s+FROM\b",
    r"\bUPDATE\s+\S+\s+SET\b",
)


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch):
    """模型测试不得继承宿主 provider/secret 环境（DEC-105 先例）。"""
    for key in PROVIDER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _load_reconcile_module():
    name = "reconcile_model_management_under_test"
    spec = importlib.util.spec_from_file_location(name, RECONCILE_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestMigrationAppendOnly:
    def test_model_migrations_are_append_only_and_start_at_072(self):
        names = [name for name, _ in MIGRATIONS]
        assert names[-3:] == MODEL_MIGRATION_NAMES, (
            "新迁移必须以 072/073/074 结尾且名称固定")
        assert len(names) == len(set(names)), "迁移名不得重复"

    def test_prefix_001_to_071_unchanged(self):
        names = [name for name, _ in MIGRATIONS]
        assert names[0] == "001_platform_init"
        assert names[70] == "071_research_idempotency_v1", (
            "001–071 序列不得被改写或重排")

    def test_new_migrations_contain_no_destructive_statements(self):
        for name, sql in MIGRATIONS:
            if name not in _MODEL_NAMES:
                continue
            for pat in _FORBIDDEN_PATTERNS:
                assert re.search(pat, sql, re.IGNORECASE) is None, (
                    f"{name} 含破坏性语句（{pat}）；072–074 只能纯追加")


class TestReadonlyPreflight:
    def test_readonly_preflight_does_not_upgrade_live_copy(self, tmp_path):
        db = copy_live_database(tmp_path)
        before = fingerprint(db)
        assert before["migration_count"] == 68, (
            "前置：live 副本应为 068（文档基线）；若 live 已升级需先登记事实")

        mod = _load_reconcile_module()
        result = mod.readonly_model_preflight(db)
        assert result["migration_count"] == 68
        assert result["integrity"] == "ok"

        after = fingerprint(db)
        assert after == before, "只读 preflight 不得修改数据库（含 journal）"
        assert not Path(str(db) + "-wal").exists()
        assert not Path(str(db) + "-shm").exists()

    def test_reconcile_cli_read_only_keeps_live_copy_untouched(
            self, tmp_path, monkeypatch):
        db = copy_live_database(tmp_path)
        before = fingerprint(db)
        mod = _load_reconcile_module()
        monkeypatch.setattr(
            sys, "argv",
            ["reconcile_model_management", "--db", str(db), "--read-only"])
        with pytest.raises(SystemExit) as ei:
            mod.main()
        assert ei.value.code == 0, "无漂移时 reconcile 必须 exit 0"
        assert fingerprint(db) == before


class TestCopyUpgrade:
    def test_upgrade_copy_from_068_to_latest_is_idempotent_and_lossless(
            self, tmp_path):
        live_before = live_db_sha256()
        db = copy_live_database(tmp_path)
        # 复制动作本身不得改变 live 文件
        assert live_db_sha256() == live_before

        before_counts = table_row_counts(db)
        fp = fingerprint(db)
        assert fp["migration_count"] == 68

        store = PlatformStore(db)
        store.apply_migrations()  # 第二次调用必须幂等
        store.close()

        conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
        n = conn.execute(
            "SELECT count(*) c FROM schema_migrations").fetchone()[0]
        latest = conn.execute(
            "SELECT name FROM schema_migrations ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        integrity = conn.execute(
            "PRAGMA integrity_check").fetchone()[0]
        conn.close()

        expected_count = len(MIGRATIONS)
        assert n == expected_count, f"副本应升级到最新（{expected_count}）"
        assert latest == MIGRATIONS[-1][0]
        assert integrity == "ok"

        # 旧表不丢失：升级前存在的每张表行数不变
        # （schema_migrations 例外：迁移 apply 本身向其追加行）
        after_counts = table_row_counts(db)
        for table, count in before_counts.items():
            assert table in after_counts, f"升级后旧表 {table} 消失"
            if table == "schema_migrations":
                assert after_counts[table] == expected_count, (
                    "schema_migrations 应恰好记录全部已声明迁移")
                continue
            assert after_counts[table] == count, (
                f"升级后旧表 {table} 行数变化 {count}→{after_counts[table]}")

    def test_live_db_hash_matches_documented_baseline(self):
        """G0：本轮 live DB hash 必须保持文档冻结值（只读纪律锁定）。"""
        if not LIVE_DB.exists():
            pytest.skip("live DB 不存在")
        assert live_db_sha256() == LIVE_DB_DOC_SHA256, (
            "live DB hash 与文档基线不一致：有主体在本轮之外修改了 live DB，"
            "必须先登记事实并评估影响，而不是继续执行")
