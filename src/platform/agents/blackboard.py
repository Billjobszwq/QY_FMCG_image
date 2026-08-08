"""SLTF §12：Shared Blackboard（typed append-only）+ 分级记忆（ACL/supersedes）。

黑板事件类型固定；Agent 只追加，不得覆盖他人/人工结论（supersede 需同
agent 或 human）。记忆条目带 scope/ACL/confidence/valid_from/valid_to/
supersedes；向量索引仅为可重建派生物（本实现不建向量，留接口）。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

EVENT_TYPES = frozenset({
    "Question", "Finding", "Decision", "Task", "Blocker", "EvidenceRef",
    "DataQueryResultRef", "ModelRunRef", "PendingCommand", "Approval",
    "Resolution", "Note",
})


class BlackboardTypeError(ValueError):
    """黑板事件类型非法。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BlackboardService:
    def __init__(self, store: Any) -> None:
        self.store = store

    def append(self, by: str, event_type: str, payload: dict[str, Any],
               *, evidence_refs: list[str] | None = None,
               supersedes: str | None = None,
               by_kind: str = "agent") -> str:
        if event_type not in EVENT_TYPES:
            raise BlackboardTypeError(f"非法黑板事件类型: {event_type}")
        if supersedes is not None:
            old = self.store._conn.execute(
                "SELECT by, by_kind FROM blackboard_event_v1 WHERE id=?",
                (supersedes,)).fetchone()
            if old is None:
                raise BlackboardTypeError("supersedes 目标不存在")
            if old["by"] != by and old["by_kind"] != "human" and \
                    by_kind != "human":
                raise PermissionError(
                    "跨 Agent 覆盖需人工批准（不得静默覆盖他人结论）")
        eid = uuid.uuid4().hex
        self.store._conn.execute(
            "INSERT INTO blackboard_event_v1 (id, by, by_kind, event_type,"
            " payload_json, evidence_json, supersedes, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (eid, by, by_kind, event_type,
             json.dumps(payload, ensure_ascii=False),
             json.dumps(evidence_refs or [], ensure_ascii=False),
             supersedes, _now()))
        self.store._conn.commit()
        return eid

    def cards(self, *, status: str | None = None) -> list[dict[str, Any]]:
        rows = self.store._conn.execute(
            "SELECT * FROM blackboard_event_v1 ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]


class MemoryService:
    def __init__(self, store: Any) -> None:
        self.store = store

    def put(self, level: str, text: str, *, scope: str, acl: list[str],
            confidence: float, evidence: list[str],
            supersedes: str | None = None,
            retention: str = "project_lifetime") -> str:
        mid = uuid.uuid4().hex
        if supersedes:
            self.store._conn.execute(
                "UPDATE memory_entry_v1 SET valid_to=? WHERE id=?",
                (_now(), supersedes))
        self.store._conn.execute(
            "INSERT INTO memory_entry_v1 (id, level, text, scope, acl_json,"
            " confidence, evidence_json, valid_from, valid_to, retention,"
            " supersedes, version) VALUES (?,?,?,?,?,?,?,?,NULL,?,?,1)",
            (mid, level, text, scope, json.dumps(acl), confidence,
             json.dumps(evidence, ensure_ascii=False), _now(), retention,
             supersedes))
        self.store._conn.commit()
        return mid

    def get(self, mid: str, *, requester_acl: list[str]
            ) -> dict[str, Any] | None:
        row = self.store._conn.execute(
            "SELECT * FROM memory_entry_v1 WHERE id=?", (mid,)).fetchone()
        if row is None:
            return None
        acl = set(json.loads(row["acl_json"]))
        if not (acl & set(requester_acl)):
            return None
        d = dict(row)
        d["acl"] = sorted(acl)
        return d
