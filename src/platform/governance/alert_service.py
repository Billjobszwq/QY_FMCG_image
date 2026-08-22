"""Silent Agent 告警与不可变快照服务（Task 4 / G2）。

- 只有 role=silent_agent 可发告警/快照（服务层强制，非 Prompt）；
- 告警 append-only（禁 DELETE）；状态迁移走 CAS；
- 快照完全不可变（禁 UPDATE/DELETE），内容哈希入账。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from . import GovernanceConflictError, GovernanceError, GovernanceRoleError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_hash(state: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        state, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()


class AlertService:
    def __init__(self, store: Any) -> None:
        self.store = store

    def raise_alert(self, *, actor: str, role: str = "silent_agent",
                    severity: str, content: str, rule_id: str = "",
                    evidence_refs: list[str] | None = None,
                    affected_run_ids: list[str] | None = None,
                    recommended_action: str = "",
                    pause_requested: bool = False) -> dict[str, Any]:
        if role not in ("silent_agent", "system"):
            raise GovernanceRoleError(
                f"只有 Silent Agent/系统服务可发治理告警"
                f"（当前 role={role}）")
        if severity not in ("warning", "critical"):
            raise GovernanceError(f"非法 severity: {severity}")
        if not content:
            raise GovernanceError("告警 content 必填")
        alert_id = "alert-" + uuid.uuid4().hex[:12]
        self.store._conn.execute(
            "INSERT INTO governance_alert_v1 (alert_id, severity,"
            " rule_id, source_agent, affected_run_ids_json,"
            " evidence_refs_json, content, recommended_action,"
            " pause_requested, status, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?, 'open', ?,?)",
            (alert_id, severity, rule_id, actor,
             json.dumps(affected_run_ids or [], ensure_ascii=False),
             json.dumps(evidence_refs or [], ensure_ascii=False),
             content, recommended_action, 1 if pause_requested else 0,
             actor, _now()))
        self.store._conn.commit()
        return self.get_alert(alert_id)

    def list_alerts(self, *, limit: int = 200) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM governance_alert_v1 ORDER BY created_at DESC"
            f" LIMIT {int(limit)}").fetchall()
        return [dict(r) for r in rows]

    def get_alert(self, alert_id: str) -> dict[str, Any]:
        row = self.store._conn.execute(
            "SELECT * FROM governance_alert_v1 WHERE alert_id=?",
            (alert_id,)).fetchone()
        if row is None:
            raise GovernanceError(f"告警不存在: {alert_id}")
        return dict(row)

    def resolve_alert(self, alert_id: str, *, actor: str,
                      role: str = "human", note: str = "") -> dict:
        """告警闭环只能由 human/supervisor 响应（Silent 不自我闭环）。"""
        if role not in ("human", "supervisor"):
            raise GovernanceRoleError(
                f"role={role} 不得闭环告警（只有 human/supervisor）")
        rc = self.store._conn.execute(
            "UPDATE governance_alert_v1 SET status='resolved',"
            " resolved_at=? WHERE alert_id=? AND status IN"
            " ('open','acknowledged')", (_now(), alert_id)).rowcount
        self.store._conn.commit()
        if rc == 0:
            raise GovernanceConflictError(
                f"告警 {alert_id} 不存在或已闭环（CAS 拒绝）")
        return self.get_alert(alert_id)

    def snapshot(self, *, actor: str, role: str = "silent_agent",
                 subject_type: str, subject_id: str,
                 state: dict[str, Any], alert_id: str = "") -> dict:
        if role != "silent_agent":
            raise GovernanceRoleError(
                f"只有 Silent Agent 可创建治理快照（当前 role={role}）")
        snapshot_id = "snap-" + uuid.uuid4().hex[:12]
        state_json = json.dumps(state, sort_keys=True, ensure_ascii=False)
        self.store._conn.execute(
            "INSERT INTO governance_snapshot_v1 (snapshot_id, alert_id,"
            " subject_type, subject_id, state_hash, state_json,"
            " created_by, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (snapshot_id, alert_id, subject_type, subject_id,
             _state_hash(state), state_json, actor, _now()))
        self.store._conn.commit()
        row = self.store._conn.execute(
            "SELECT * FROM governance_snapshot_v1 WHERE snapshot_id=?",
            (snapshot_id,)).fetchone()
        return dict(row)
