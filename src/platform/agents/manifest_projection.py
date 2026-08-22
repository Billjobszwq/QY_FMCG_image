"""Manifest 只读投影（Task 3）。

Manifest = 已发布 AgentDefinitionVersion ⊕ Module Registry 元数据
（kernel._BUILTIN 的域/UI/计费/审批元数据）。禁止新的双写：
- 唯一写入路径是 rebuild_manifest_projection / guarded_manifest_insert；
- source != 'projection' 的直接写一律拒绝（ManifestDirectWriteError）；
- consistency_report 是 Gate：definition 与投影的 agent_id/version/
  tool scope 任一漂移即 fail-closed。
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from .kernel import GRANTABLE_SCOPES, AgentManifest, _BUILTIN

# Tool → 可授予 capability scope（投影派生；全部在 GRANTABLE_SCOPES 内）
TOOL_CAPABILITY: dict[str, str] = {
    "work.progress.query": "evidence.read",
    "master.skus.summary": "data.query.readonly",
    "master.data.summary": "data.query.readonly",
    "survey.list": "survey.read",
    "survey.responses.summary": "survey.read",
    "geo.addresses.missing_coords": "geo.read",
    "geo.tasks.summary": "geo.read",
    "usage.query": "finance.read",
    "modelops.artifacts.query": "training.run.read",
    "analytics.metrics.list": "analytics.read",
    "analytics.report.draft": "analytics.read",
    "kb.search": "registry.read",
    "workflow.draft.create": "workflow.draft.propose",
    "recognition.create.preview": "recognition.task.create",
}

# 写类工具（生成 command schema 的 allowlist 条目）
_WRITE_TOOLS = ("workflow.draft.create", "analytics.report.draft",
                "recognition.create.preview")

_META_BY_ID = {m.agent_id: m for m in _BUILTIN}


class ManifestDirectWriteError(Exception):
    """绕过投影直接写 agent_manifest_v1（fail-closed）。"""


def project_manifest(defn: dict[str, Any]) -> AgentManifest:
    """由已发布定义 + Module Registry 元数据确定性投影 Manifest。"""
    meta = _META_BY_ID[defn["agent_id"]]
    tools = json.loads(defn["tool_allowlist_json"] or "[]")
    scopes = sorted({TOOL_CAPABILITY[t] for t in tools
                     if t in TOOL_CAPABILITY} | set(
                         meta.capability_scopes))
    bad = set(scopes) - GRANTABLE_SCOPES
    if bad:
        raise ManifestDirectWriteError(
            f"投影产生不可授予 scope: {sorted(bad)}")
    return AgentManifest(
        agent_id=defn["agent_id"],
        version=str(defn["version"]),
        domain=meta.domain,
        capability_scopes=scopes,
        command_schemas=[t for t in tools if t in _WRITE_TOOLS],
        allowed_data_scopes=list(meta.allowed_data_scopes),
        memory_policy=meta.memory_policy,
        ui_slots=list(meta.ui_slots),
        graph_templates=list(meta.graph_templates),
        risk_level=meta.risk_level,
        approval_rules=list(meta.approval_rules),
        billing_unit=meta.billing_unit,
        health_endpoint=meta.health_endpoint,
        definition_status="published",
    )


def projection_payload(agent_id: str, store: Any) -> dict[str, Any]:
    """该 Agent 的期望 manifest_json（Gate 对账基准）。"""
    from .definition_service import AgentDefinitionService
    svc = AgentDefinitionService(store)
    defn = svc.published_definition(agent_id)
    if defn is not None:
        m = project_manifest(defn)
        payload = asdict(m)
        payload["tool_allowlist"] = sorted(
            json.loads(defn["tool_allowlist_json"] or "[]"))
        return payload
    meta = _META_BY_ID[agent_id]
    payload = asdict(meta)
    payload["definition_status"] = "declared"
    payload["tool_allowlist"] = []
    return payload


def guarded_manifest_insert(store: Any, m: AgentManifest, *,
                            source: str) -> None:
    """agent_manifest_v1 唯一合法写入点；仅投影来源允许。"""
    if source != "projection":
        raise ManifestDirectWriteError(
            f"agent_manifest_v1 禁止直接写入（source={source}）；"
            "Manifest 只能由 Definition 投影生成")
    store._conn.execute(
        "INSERT OR REPLACE INTO agent_manifest_v1 (agent_id, version,"
        " domain, manifest_json, created_at) VALUES (?,?,?,?,?)",
        (m.agent_id, m.version, m.domain,
         json.dumps(asdict(m), ensure_ascii=False),
         __import__("datetime").datetime.now(
             __import__("datetime").timezone.utc).isoformat()))
    store._conn.commit()


def rebuild_manifest_projection(store: Any) -> dict[str, Any]:
    """确定性重建全部内置 Agent 的 Manifest 投影（幂等）。"""
    from datetime import datetime, timezone
    conn = store._conn
    for agent_id in sorted(_META_BY_ID):
        payload = projection_payload(agent_id, store)
        conn.execute(
            "INSERT OR REPLACE INTO agent_manifest_v1 (agent_id,"
            " version, domain, manifest_json, created_at)"
            " VALUES (?,?,?,?,?)",
            (agent_id, payload["version"], payload["domain"],
             json.dumps(payload, ensure_ascii=False),
             datetime.now(timezone.utc).isoformat()))
    conn.commit()
    n = conn.execute(
        "SELECT count(*) c FROM agent_manifest_v1").fetchone()["c"]
    return {"projected": n, "source": "projection"}


def consistency_report(store: Any) -> dict[str, Any]:
    """Gate：Manifest 投影 vs Definition 一致性（fail-closed）。

    检查：12 个内置 Agent 的 manifest 行必须存在；published 定义的
    version/tool_allowlist/派生字段必须与存储投影逐字段一致；
    declared Agent 必须标 declared。
    """
    mismatches: list[dict[str, Any]] = []
    for agent_id in sorted(_META_BY_ID):
        row = store._conn.execute(
            "SELECT version, manifest_json FROM agent_manifest_v1"
            " WHERE agent_id=?", (agent_id,)).fetchone()
        if row is None:
            mismatches.append({"agent_id": agent_id, "field": "missing",
                               "detail": "manifest 行缺失"})
            continue
        try:
            stored = json.loads(row["manifest_json"])
        except (TypeError, ValueError):
            mismatches.append({"agent_id": agent_id,
                               "field": "manifest_json",
                               "detail": "manifest_json 不可解析"})
            continue
        expected = projection_payload(agent_id, store)
        for k, v in expected.items():
            if stored.get(k) != v:
                mismatches.append({
                    "agent_id": agent_id, "field": k,
                    "detail": f"stored={stored.get(k)!r}"
                              f" expected={v!r}"})
        if row["version"] != expected["version"]:
            mismatches.append({
                "agent_id": agent_id, "field": "version",
                "detail": f"列 version={row['version']!r}"
                          f" expected={expected['version']!r}"})
    return {"ok": not mismatches, "mismatches": mismatches}
