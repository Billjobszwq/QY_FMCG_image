"""Task 3 红测试：单一 Agent Definition 事实源 + Manifest 只读投影。

要求（05 计划 Task 3）：
- Manifest 与 Definition 的 Agent ID/version/tool scope 不一致时 Gate 失败；
- Manifest 只能由“已发布 Definition + Module Registry 元数据”投影；
- 12 个内置 Agent 的迁移报告：缺 Runtime Definition 的状态为 declared，
  不得伪装 healthy/published；
- 禁止新代码直接写 agent_manifest_v1（投影守卫）；
- 旧 AgentRegistry 兼容契约保持（scope 白名单校验仍生效）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.platform.agents.definition_service import (
    AgentDefinitionService,
    canonical_agent_report,
)
from src.platform.agents.kernel import AgentManifest, AgentRegistry
from src.platform.agents.manifest_projection import (
    ManifestDirectWriteError,
    consistency_report,
    guarded_manifest_insert,
    rebuild_manifest_projection,
)
from src.platform.data.store import PlatformStore


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


class TestCanonicalReport:
    def test_twelve_canonical_agents_with_declared_status(self, store):
        AgentDefinitionService(store).ensure_seed_definitions()
        rebuild_manifest_projection(store)
        report = canonical_agent_report(store)
        assert len(report) == 12, "12 个内置 Agent 必须全部在报告中"
        by_id = {r["agent_id"]: r for r in report}
        # 7 个有 Runtime Definition（published）
        for aid in ("supervisor", "modelops", "data_steward",
                    "survey_agent", "analytics_agent", "fieldops_agent",
                    "finance_agent"):
            assert by_id[aid]["definition_status"] == "published", aid
        # 5 个只有 Manifest 声明：declared，不得伪装 published/healthy
        for aid in ("workbench", "recognition_agent", "system_agent",
                    "workflow_agent", "iam_agent"):
            assert by_id[aid]["definition_status"] == "declared", aid
            assert by_id[aid]["healthy"] is False

    def test_seed_is_idempotent(self, store):
        svc = AgentDefinitionService(store)
        svc.ensure_seed_definitions()
        n1 = store._conn.execute(
            "SELECT count(*) c FROM agent_definition_v1").fetchone()["c"]
        svc.ensure_seed_definitions()
        n2 = store._conn.execute(
            "SELECT count(*) c FROM agent_definition_v1").fetchone()["c"]
        assert n1 == n2 == 7


class TestProjectionGate:
    def test_gate_passes_after_projection(self, store):
        AgentDefinitionService(store).ensure_seed_definitions()
        rebuild_manifest_projection(store)
        rep = consistency_report(store)
        assert rep["ok"] is True, rep["mismatches"]

    def test_gate_fails_on_version_drift(self, store):
        AgentDefinitionService(store).ensure_seed_definitions()
        rebuild_manifest_projection(store)
        # 模拟漂移：有人绕过投影直接改了 manifest 版本
        row = store._conn.execute(
            "SELECT manifest_json FROM agent_manifest_v1"
            " WHERE agent_id='supervisor'").fetchone()
        mj = json.loads(row["manifest_json"])
        mj["version"] = "99"
        store._conn.execute(
            "UPDATE agent_manifest_v1 SET version='99', manifest_json=?"
            " WHERE agent_id='supervisor'",
            (json.dumps(mj, ensure_ascii=False),))
        store._conn.commit()
        rep = consistency_report(store)
        assert rep["ok"] is False
        assert any(m["agent_id"] == "supervisor" and "version" in
                   m["field"] for m in rep["mismatches"])

    def test_gate_fails_on_tool_scope_drift(self, store):
        AgentDefinitionService(store).ensure_seed_definitions()
        rebuild_manifest_projection(store)
        # 模拟漂移：definition 的 tool allowlist 被改动但未重投影
        row = store._conn.execute(
            "SELECT tool_allowlist_json FROM agent_definition_v1"
            " WHERE agent_id='supervisor' AND status='published'"
        ).fetchone()
        tools = json.loads(row["tool_allowlist_json"]) + ["rogue.tool"]
        store._conn.execute(
            "UPDATE agent_definition_v1 SET tool_allowlist_json=?"
            " WHERE agent_id='supervisor' AND status='published'",
            (json.dumps(tools),))
        store._conn.commit()
        rep = consistency_report(store)
        assert rep["ok"] is False
        assert any(m["agent_id"] == "supervisor"
                   for m in rep["mismatches"])

    def test_gate_fails_on_missing_manifest(self, store):
        AgentDefinitionService(store).ensure_seed_definitions()
        rebuild_manifest_projection(store)
        store._conn.execute(
            "DELETE FROM agent_manifest_v1 WHERE agent_id='modelops'")
        store._conn.commit()
        rep = consistency_report(store)
        assert rep["ok"] is False
        assert any(m["agent_id"] == "modelops" and m["field"] == "missing"
                   for m in rep["mismatches"])

    def test_rebuild_is_idempotent(self, store):
        AgentDefinitionService(store).ensure_seed_definitions()
        rebuild_manifest_projection(store)
        h1 = store._conn.execute(
            "SELECT group_concat(manifest_json) x FROM agent_manifest_v1"
            " ORDER BY agent_id").fetchone()["x"]
        rebuild_manifest_projection(store)
        n = store._conn.execute(
            "SELECT count(*) c FROM agent_manifest_v1").fetchone()["c"]
        h2 = store._conn.execute(
            "SELECT group_concat(manifest_json) x FROM agent_manifest_v1"
            " ORDER BY agent_id").fetchone()["x"]
        assert n == 12
        assert h1 == h2


class TestDirectWriteGuard:
    def test_guarded_insert_rejects_non_projection_source(self, store):
        m = AgentManifest(agent_id="x", version="1", domain="x",
                          capability_scopes=[], command_schemas=[],
                          allowed_data_scopes=[], memory_policy="none",
                          ui_slots=[], graph_templates=[], risk_level="low",
                          approval_rules=[], billing_unit="call",
                          health_endpoint="/health")
        with pytest.raises(ManifestDirectWriteError):
            guarded_manifest_insert(store, m, source="runtime_hotfix")

    def test_guarded_insert_allows_projection_source(self, store):
        m = AgentManifest(agent_id="y", version="1", domain="x",
                          capability_scopes=[], command_schemas=[],
                          allowed_data_scopes=[], memory_policy="none",
                          ui_slots=[], graph_templates=[], risk_level="low",
                          approval_rules=[], billing_unit="call",
                          health_endpoint="/health")
        guarded_manifest_insert(store, m, source="projection")
        assert store._conn.execute(
            "SELECT 1 FROM agent_manifest_v1 WHERE agent_id='y'"
        ).fetchone() is not None


class TestLegacyCompatibility:
    def test_registry_still_seeds_and_validates_scopes(self, store):
        AgentDefinitionService(store).ensure_seed_definitions()
        reg = AgentRegistry(store)
        ids = {a["agent_id"] for a in reg.list_agents()}
        assert {"supervisor", "modelops", "data_steward",
                "workbench"} <= ids
        m = AgentManifest(agent_id="rogue", version="1", domain="x",
                          capability_scopes=["production.switch"],
                          command_schemas=[], allowed_data_scopes=[],
                          memory_policy="none", ui_slots=[],
                          graph_templates=[], risk_level="high",
                          approval_rules=[], billing_unit="call",
                          health_endpoint="/health")
        with pytest.raises(ValueError):
            reg.register(m)
