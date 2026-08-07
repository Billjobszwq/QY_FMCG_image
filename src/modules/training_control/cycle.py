"""N2 Task 1：持久化 TrainingCycle（03 计划 §1/§2）。

Graph 状态、checkpoint、等待原因、事件序列与幂等键全部持久化在平台
事实库；内存对象只是执行投影，服务重启后从 DB 恢复。乐观版本号
防止并发/重复按钮造成的重复推进。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

# Cycle 状态机（03 §2.1 冻结顺序 + FAILED/STOPPED 任意可达）
CYCLE_STATES: tuple[str, ...] = (
    "DRAFT", "BASELINE_VERIFIED", "ASSET_SCOPE_FROZEN",
    "QUALITY_POLICY_CALIBRATED", "SAM_DATASET_VERIFIED", "SNAPSHOTS_READY",
    "RESOURCE_PLAN_READY", "TRAINING_AUTHORIZED", "TRAINING_RUNNING",
    "FOUR_EXPERIMENTAL_CANDIDATES_READY", "HUMAN_EVALUATION_READY",
    "SHADOW_READY", "AWAITING_PROMOTION_DECISION",
    "COMPLETED_NO_PROMOTION", "FAILED", "STOPPED",
)

_LINEAR = {s: CYCLE_STATES[i + 1]
           for i, s in enumerate(CYCLE_STATES[:14]) if i + 1 < 14}


def _can_cycle_transition(cur: str, target: str) -> bool:
    if target in ("FAILED", "STOPPED"):
        return cur not in ("FAILED", "STOPPED")
    return _LINEAR.get(cur) == target


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class CycleError(RuntimeError):
    """Cycle 状态/版本错误（fail-closed）。"""


class TrainingCycleService:
    """唯一写事实源：DB 乐观版本推进 + append-only 事件。"""

    def __init__(self, store: Any) -> None:
        self.store = store
        self._conn = store._conn  # 复用平台事实库连接（同库事务）

    # ---- cycle ----

    def create_cycle(self, *, name: str, actor: str) -> str:
        cid = uuid.uuid4().hex
        self._conn.execute(
            "INSERT INTO training_cycle_v1 (cycle_id, name, status,"
            " version, created_by, created_at, updated_at)"
            " VALUES (?,?,?,1,?,?,?)",
            (cid, name, "DRAFT", actor, _utcnow(), _utcnow()))
        self._conn.commit()
        self._append_event(cid, "cycle_created",
                           {"name": name, "actor": actor})
        return cid

    def get_cycle(self, cycle_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM training_cycle_v1 WHERE cycle_id=?",
            (cycle_id,)).fetchone()
        if row is None:
            raise CycleError(f"未知 cycle: {cycle_id}")
        return dict(row)

    def advance(self, cycle_id: str, target: str, *, actor: str,
                expected_version: int, waiting_for: str = "") -> None:
        cur = self.get_cycle(cycle_id)
        if cur["version"] != expected_version:
            raise CycleError(
                f"版本冲突：期望 {expected_version}，实际 {cur['version']}"
                "（并发/重复操作被拒绝）")
        if not _can_cycle_transition(cur["status"], target):
            self._append_event(cycle_id, "illegal_cycle_transition",
                               {"from": cur["status"], "to": target,
                                "actor": actor})
            raise CycleError(
                f"非法跃迁 {cur['status']} -> {target}")
        n = self._conn.execute(
            "UPDATE training_cycle_v1 SET status=?, version=?,"
            " waiting_for=?, updated_at=?"
            " WHERE cycle_id=? AND version=?",
            (target, expected_version + 1, waiting_for, _utcnow(),
             cycle_id, expected_version)).rowcount
        self._conn.commit()
        if n != 1:
            raise CycleError("乐观锁冲突：推进失败")
        self._append_event(cycle_id, "cycle_advanced",
                           {"from": cur["status"], "to": target,
                            "actor": actor, "version": expected_version + 1})

    # ---- 节点 checkpoint（幂等键防重复执行） ----

    def record_node(self, cycle_id: str, *, node: str, status: str,
                    idempotency_key: str,
                    evidence: dict[str, Any] | None = None) -> dict:
        row = self._conn.execute(
            "SELECT * FROM training_cycle_node_v1"
            " WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if row is not None:
            return {"duplicate": True, "node": dict(row)}
        self._conn.execute(
            "INSERT INTO training_cycle_node_v1 (cycle_id, node, status,"
            " idempotency_key, evidence_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (cycle_id, node, status, idempotency_key,
             json.dumps(evidence or {}, ensure_ascii=False),
             _utcnow(), _utcnow()))
        self._conn.commit()
        self._append_event(cycle_id, "node_checkpoint",
                           {"node": node, "status": status,
                            "key": idempotency_key})
        return {"duplicate": False}

    def node_checkpoint(self, cycle_id: str, node: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM training_cycle_node_v1"
            " WHERE cycle_id=? AND node=? ORDER BY id DESC LIMIT 1",
            (cycle_id, node)).fetchone()
        if row is None:
            raise CycleError(f"无 checkpoint: {node}")
        d = dict(row)
        d["evidence"] = json.loads(d.pop("evidence_json"))
        return d

    # ---- 事件（append-only） ----

    def _append_event(self, cycle_id: str, kind: str,
                      payload: dict[str, Any]) -> None:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM"
            " training_cycle_event_v1 WHERE cycle_id=?",
            (cycle_id,)).fetchone()
        self._conn.execute(
            "INSERT INTO training_cycle_event_v1"
            " (cycle_id, seq, kind, payload_json, created_at)"
            " VALUES (?,?,?,?,?)",
            (cycle_id, row["n"], kind,
             json.dumps(payload, ensure_ascii=False), _utcnow()))
        self._conn.commit()

    def events(self, cycle_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM training_cycle_event_v1 WHERE cycle_id=?"
            " ORDER BY seq", (cycle_id,)).fetchall()
        return [dict(r) for r in rows]

    # ---- plan / approval ----

    def register_plan(self, cycle_id: str, *, lane: str, hypothesis: str,
                      base_revision: str, dataset_hash: str,
                      budget: dict[str, Any], stop_lines: list[str],
                      eval_set_hash: str, actor: str) -> str:
        pid = uuid.uuid4().hex
        self._conn.execute(
            "INSERT INTO nextgen_plan_v1 (plan_id, cycle_id, lane,"
            " hypothesis, base_revision, dataset_hash, budget_json,"
            " stop_lines_json, eval_set_hash, status, created_by,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,"
            "'DRAFT',?,?,?)",
            (pid, cycle_id, lane, hypothesis, base_revision, dataset_hash,
             json.dumps(budget, ensure_ascii=False),
             json.dumps(stop_lines, ensure_ascii=False), eval_set_hash,
             actor, _utcnow(), _utcnow()))
        self._conn.commit()
        self._append_event(cycle_id, "plan_registered",
                           {"plan_id": pid, "lane": lane, "actor": actor})
        return pid

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM nextgen_plan_v1 WHERE plan_id=?",
            (plan_id,)).fetchone()
        if row is None:
            raise CycleError(f"未知 plan: {plan_id}")
        return dict(row)

    def approve_plan(self, plan_id: str, *, actor: str,
                     approval_key: str) -> None:
        row = self._conn.execute(
            "SELECT 1 FROM nextgen_plan_approval_v1 WHERE approval_key=?",
            (approval_key,)).fetchone()
        if row is not None:
            return  # 幂等：重复审批键不重复记录
        self._conn.execute(
            "INSERT INTO nextgen_plan_approval_v1"
            " (plan_id, approval_key, actor, created_at)"
            " VALUES (?,?,?,?)",
            (plan_id, approval_key, actor, _utcnow()))
        self._conn.execute(
            "UPDATE nextgen_plan_v1 SET status='APPROVED',"
            " approved_by=?, approved_count=approved_count+1,"
            " updated_at=? WHERE plan_id=?",
            (actor, _utcnow(), plan_id))
        self._conn.commit()

    # ---- run attempt / artifact ----

    def register_run_attempt(self, plan_id: str, *, attempt: int,
                             command_hash: str, env_hash: str,
                             output_dir: str = "") -> str:
        rid = uuid.uuid4().hex
        self._conn.execute(
            "INSERT INTO nextgen_run_attempt_v1 (run_id, plan_id, attempt,"
            " command_hash, env_hash, status, output_dir, created_at,"
            " updated_at) VALUES (?,?,?,?,?,'REGISTERED',?,?,?)",
            (rid, plan_id, attempt, command_hash, env_hash, output_dir,
             _utcnow(), _utcnow()))
        self._conn.commit()
        return rid

    def get_run_attempt(self, run_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM nextgen_run_attempt_v1 WHERE run_id=?",
            (run_id,)).fetchone()
        if row is None:
            raise CycleError(f"未知 run: {run_id}")
        return dict(row)

    def update_run_attempt(self, run_id: str, **fields: Any) -> None:
        allowed = {"status", "pid", "heartbeat_at", "lease_json",
                   "output_dir"}
        cols = [k for k in fields if k in allowed]
        if not cols:
            return
        sets = ", ".join(f"{c}=?" for c in cols)
        self._conn.execute(
            f"UPDATE nextgen_run_attempt_v1 SET {sets}, updated_at=?"
            " WHERE run_id=?",
            (*[fields[c] for c in cols], _utcnow(), run_id))
        self._conn.commit()

    def register_artifact(self, run_id: str, *, artifact_type: str,
                          path: str, sha256: str,
                          lineage: dict[str, Any] | None = None) -> None:
        self._conn.execute(
            "INSERT INTO training_artifact_v2 (run_id, artifact_type,"
            " path, sha256, lineage_json, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (run_id, artifact_type, path, sha256,
             json.dumps(lineage or {}, ensure_ascii=False), _utcnow()))
        self._conn.commit()

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM training_artifact_v2 WHERE run_id=?"
            " ORDER BY id", (run_id,)).fetchall()
        return [dict(r) for r in rows]
