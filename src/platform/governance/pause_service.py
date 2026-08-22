"""熔断暂停与人类恢复（Task 4 / G2）。

- Silent Agent 的 pause request 一经创建即生效（status=paused）；
- 恢复必须人类批准（human_approved=True），且 CAS 条件 UPDATE：
  终态（resumed/rejected）不可再次迁移，迟到写被拒。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from . import GovernanceConflictError, GovernanceError, GovernanceRoleError


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PauseService:
    def __init__(self, store: Any) -> None:
        self.store = store

    def request_pause(self, *, actor: str, subject_type: str,
                      subject_id: str, reason: str,
                      alert_id: str = "") -> dict[str, Any]:
        if not reason:
            raise GovernanceError("暂停必须给出 reason")
        pause_id = "pause-" + uuid.uuid4().hex[:12]
        self.store._conn.execute(
            "INSERT INTO pause_request_v1 (pause_id, subject_type,"
            " subject_id, reason, alert_id, requested_by, status,"
            " version, requested_at) VALUES (?,?,?,?,?,?,'paused',1,?)",
            (pause_id, subject_type, subject_id, reason, alert_id,
             actor, _now()))
        self.store._conn.commit()
        return self.get_pause(pause_id)

    def get_pause(self, pause_id: str) -> dict[str, Any]:
        row = self.store._conn.execute(
            "SELECT * FROM pause_request_v1 WHERE pause_id=?",
            (pause_id,)).fetchone()
        if row is None:
            raise GovernanceError(f"pause 不存在: {pause_id}")
        return dict(row)

    def resume(self, pause_id: str, *, actor: str,
               human_approved: bool) -> dict[str, Any]:
        """只有人类批准可恢复被熔断对象（Silent/自动化不得自复）。"""
        if not human_approved:
            raise GovernanceRoleError(
                "恢复熔断必须人类批准（human_approved=True）")
        rc = self.store._conn.execute(
            "UPDATE pause_request_v1 SET status='resumed',"
            " resume_decided_by=?, decided_at=?, version=version+1"
            " WHERE pause_id=? AND status='paused'",
            (actor, _now(), pause_id)).rowcount
        self.store._conn.commit()
        if rc == 0:
            raise GovernanceConflictError(
                f"pause {pause_id} 不在 paused 状态（终态 CAS 拒绝）")
        return self.get_pause(pause_id)

    def reject(self, pause_id: str, *, actor: str) -> dict[str, Any]:
        rc = self.store._conn.execute(
            "UPDATE pause_request_v1 SET status='rejected',"
            " resume_decided_by=?, decided_at=?, version=version+1"
            " WHERE pause_id=? AND status='paused'",
            (actor, _now(), pause_id)).rowcount
        self.store._conn.commit()
        if rc == 0:
            raise GovernanceConflictError(
                f"pause {pause_id} 不在 paused 状态（终态 CAS 拒绝）")
        return self.get_pause(pause_id)
