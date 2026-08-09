"""状态收口 T1/T2：Cycle 节点与任务板唯一状态投影。

历史表保留；投影表 UNIQUE；乐观版本；done 禁回退（除非 reopen）。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

PRIORITY = {"done": 3, "running": 2, "waiting": 1, "failed": 1,
            "stopped": 1, "pending": 0}
LEGAL = {"pending": {"running", "done", "waiting", "failed", "stopped"},
         "running": {"done", "waiting", "failed", "stopped"},
         "waiting": {"running", "done", "failed"},
         "failed": {"running"},
         "stopped": {"running"},
         "done": set()}  # done 终态，仅 reopen 可回 pending


class IllegalTransition(RuntimeError):
    """非法状态跃迁（done 回退等）。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CycleProjectionService:
    def __init__(self, store: Any) -> None:
        self.store = store

    # ---- 投影 ----

    def set_state(self, cycle_id: str, node: str, status: str, *,
                  evidence: dict | None = None,
                  via_reopen: bool = False) -> None:
        row = self.store._conn.execute(
            "SELECT current_status, version FROM"
            " training_cycle_node_state_v2 WHERE cycle_id=? AND"
            " logical_node=?", (cycle_id, node)).fetchone()
        if row is None:
            self.store._conn.execute(
                "INSERT INTO training_cycle_node_state_v2 (cycle_id,"
                " logical_node, current_status, evidence_json, version,"
                " updated_at) VALUES (?,?,?,?,1,?)",
                (cycle_id, node, status,
                 json.dumps(evidence or {}, ensure_ascii=False), _now()))
            self.store._conn.commit()
            return
        cur = row["current_status"]
        if cur == "done" and status != "done":
            if not via_reopen:
                raise IllegalTransition(
                    f"{node}: done 禁回退 {status}（需显式 reopen）")
        elif status not in LEGAL.get(cur, set()) and cur != status:
            raise IllegalTransition(f"{node}: {cur}→{status} 非法")
        n = self.store._conn.execute(
            "UPDATE training_cycle_node_state_v2 SET current_status=?,"
            " evidence_json=?, version=version+1, updated_at=?"
            " WHERE cycle_id=? AND logical_node=? AND version=?",
            (status, json.dumps(evidence or {}, ensure_ascii=False),
             _now(), cycle_id, node, row["version"]))
        if n.rowcount != 1:
            raise IllegalTransition(f"{node}: 乐观版本冲突")
        self.store._conn.commit()

    # ---- 回填 ----

    def backfill(self, cycle_id: str) -> dict[str, str]:
        """按优先级+时间从历史表重建投影；幂等；历史行不删。"""
        rows = self.store._conn.execute(
            "SELECT node, status, id FROM training_cycle_node_v1"
            " WHERE cycle_id=? ORDER BY id", (cycle_id,)).fetchall()
        best: dict[str, tuple] = {}
        for r in rows:
            cur = best.get(r["node"])
            if cur is None or PRIORITY.get(r["status"], 0) >= cur[0]:
                best[r["node"]] = (PRIORITY.get(r["status"], 0),
                                   r["status"], r["id"])
        audit = {}
        for node, (pr, status, eid) in best.items():
            ex = self.store._conn.execute(
                "SELECT 1 FROM training_cycle_node_state_v2 WHERE"
                " cycle_id=? AND logical_node=?", (cycle_id, node)).fetchone()
            if ex is None:
                self.store._conn.execute(
                    "INSERT INTO training_cycle_node_state_v2 (cycle_id,"
                    " logical_node, current_status, latest_event_id,"
                    " evidence_json, version, updated_at)"
                    " VALUES (?,?,?,?,?,1,?)",
                    (cycle_id, node, status, str(eid),
                     json.dumps({"backfill": True}), _now()))
            audit[node] = status
        self.store._conn.commit()
        return audit

    # ---- 汇总 ----

    def cycle_summary(self, cycle_id: str) -> dict[str, Any]:
        rows = self.store._conn.execute(
            "SELECT current_status FROM training_cycle_node_state_v2"
            " WHERE cycle_id=?", (cycle_id,)).fetchall()
        cnt: dict[str, int] = {}
        for r in rows:
            cnt[r["current_status"]] = cnt.get(r["current_status"], 0) + 1
        return {"distinct_nodes": len(rows), "done": cnt.get("done", 0),
                "pending": cnt.get("pending", 0),
                "running": cnt.get("running", 0),
                "waiting": cnt.get("waiting", 0), "by_status": cnt}


class TaskProjectionService:
    def __init__(self, store: Any) -> None:
        self.store = store

    def set_task(self, key: str, *, title: str, status: str,
                 owner: str = "", blocker: str = "",
                 evidence: list | None = None,
                 cycle_id: str = "") -> None:
        row = self.store._conn.execute(
            "SELECT version FROM task_state_projection_v1 WHERE"
            " project='llm-image' AND cycle_id=? AND logical_task_key=?",
            (cycle_id, key)).fetchone()
        if row is None:
            self.store._conn.execute(
                "INSERT INTO task_state_projection_v1 (project, cycle_id,"
                " logical_task_key, title, current_status, owner, blocker,"
                " evidence_json, acceptance, version, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,1,?)",
                ("llm-image", cycle_id, key, title, status, owner, blocker,
                 json.dumps(evidence or [], ensure_ascii=False),
                 "accepted" if status == "done" else "pending", _now()))
        else:
            self.store._conn.execute(
                "UPDATE task_state_projection_v1 SET title=?, current_status=?,"
                " owner=?, blocker=?, evidence_json=?, acceptance=?,"
                " version=version+1, updated_at=? WHERE project='llm-image'"
                " AND cycle_id=? AND logical_task_key=? AND version=?",
                (title, status, owner, blocker,
                 json.dumps(evidence or [], ensure_ascii=False),
                 "accepted" if status == "done" else "pending", _now(),
                 cycle_id, key, row["version"]))
        self.store._conn.commit()

    def board(self, cycle_id: str = "") -> dict[str, list]:
        rows = self.store._conn.execute(
            "SELECT * FROM task_state_projection_v1 WHERE project="
            "'llm-image' AND cycle_id=?", (cycle_id,)).fetchall()
        out: dict[str, list] = {s: [] for s in (
            "todo", "running", "waiting", "review", "done")}
        for r in rows:
            out.setdefault(r["current_status"], []).append(dict(r))
        return out
