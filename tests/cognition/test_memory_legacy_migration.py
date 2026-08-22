"""Task 6（G4）红测试：旧记忆表只读迁移适配（dry-run）。

要求（05 计划 Task 6）：
- 映射旧 L0-L4：无法确定含义的 L4 进入 quarantine/candidate，
  不强制映射为 L3；
- 迁移脚本先 --dry-run，输出逐行决策与 hash；
- 无 delete/update 旧表（行数与内容不变）。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from src.platform.data.store import PlatformStore

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cognition_migrate_legacy.py"


def _load_script():
    import sys as _sys
    name = "cognition_migrate_legacy"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    _sys.modules[name] = mod  # dataclass 需要能从 sys.modules 解析模块
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    # 造旧表数据：agent_memory_v1（L0-L4）+ memory_entry_v1
    conn = s._conn
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
    yield s
    s.close()


class TestDryRunMigration:
    def test_dry_run_decisions_and_no_writes(self, store):
        mod = _load_script()
        before_am = store._conn.execute(
            "SELECT count(*) c FROM agent_memory_v1").fetchone()["c"]
        before_me = store._conn.execute(
            "SELECT count(*) c FROM memory_entry_v1").fetchone()["c"]
        report = mod.run_migration(store, dry_run=True)
        assert report["dry_run"] is True
        # 逐行决策：L0/L1→l1_event，L2→l2_candidate，L3→l3_candidate，
        # L4→quarantine（不得强制映射为 L3）
        by_level = {d["level"]: d["target"] for d in report["decisions"]
                    if d["table"] == "agent_memory_v1"}
        assert by_level["L0"] == "memory_l1_event"
        assert by_level["L1"] == "memory_l1_event"
        assert by_level["L2"] == "memory_l2_candidate"
        assert by_level["L3"] == "memory_l3_candidate"
        assert by_level["L4"] == "quarantine_candidate"
        me = [d for d in report["decisions"]
              if d["table"] == "memory_entry_v1"][0]
        assert me["target"] == "memory_l2_candidate"
        # 每行带稳定 hash
        assert all(len(d["row_hash"]) == 64 for d in report["decisions"])
        # dry-run 零写入：旧表行数不变，新记忆表为空
        assert store._conn.execute(
            "SELECT count(*) c FROM agent_memory_v1").fetchone()["c"] \
            == before_am
        assert store._conn.execute(
            "SELECT count(*) c FROM memory_entry_v1").fetchone()["c"] \
            == before_me
        assert store._conn.execute(
            "SELECT count(*) c FROM memory_l1_event").fetchone()["c"] == 0
        assert store._conn.execute(
            "SELECT count(*) c FROM memory_l2_episode").fetchone()["c"] \
            == 0
        assert store._conn.execute(
            "SELECT count(*) c FROM memory_l3_methodology_version"
        ).fetchone()["c"] == 0

    def test_live_mode_refused_without_approval(self, store):
        mod = _load_script()
        with pytest.raises(mod.MigrationNotAuthorized):
            mod.run_migration(store, dry_run=False)

    def test_report_is_json_serializable(self, store):
        mod = _load_script()
        report = mod.run_migration(store, dry_run=True)
        assert json.loads(json.dumps(report, ensure_ascii=False))
