"""GLTC Task 6：TrainingControlGraph —— 四 lane 共享的唯一训练控制图。

状态机来自 vocabulary.RUN_TRANSITIONS（01 §7）；非法跃迁拒绝并写审计。
通道差异只经 adapter/policy 注入，本图无 lane 专属分支。
"""
from __future__ import annotations

import uuid
from typing import Any

from . import vocabulary as V


class GraphError(RuntimeError):
    """控制图错误（非法跃迁/未注册 hook/越权命令）。"""


class TrainingControlGraph:
    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}
        self._audit: dict[str, list[dict[str, Any]]] = {}

    # ---- run 生命周期 ----

    def create_run(self, *, lane: str, plan_id: str) -> str:
        if lane not in V.TRAINING_LANES:
            raise GraphError(f"非法 lane: {lane}")
        rid = uuid.uuid4().hex
        self._runs[rid] = {"run_id": rid, "lane": lane, "plan_id": plan_id,
                           "status": "DRAFT", "waiting_for": None}
        self._audit[rid] = [{"kind": "created", "actor": "system",
                             "status": "DRAFT"}]
        return rid

    def status(self, run_id: str) -> str:
        return self._run(run_id)["status"]

    def _run(self, run_id: str) -> dict[str, Any]:
        if run_id not in self._runs:
            raise GraphError(f"未知 run: {run_id}")
        return self._runs[run_id]

    def advance(self, run_id: str, target: str, *, actor: str,
                evidence: dict[str, Any] | None = None,
                via_hook: str | None = None) -> None:
        """状态推进：非法跃迁拒绝 + 审计留痕。"""
        run = self._run(run_id)
        cur = run["status"]
        if target not in V.RUN_STATES:
            raise GraphError(f"非法状态: {target}")
        if not V.can_transition(cur, target):
            self._audit[run_id].append({
                "kind": "illegal_transition", "from": cur, "to": target,
                "actor": actor})
            raise GraphError(f"非法跃迁 {cur} -> {target}")
        run["status"] = target
        if target in ("APPROVED", "RUNNING", "STOPPED"):
            run["waiting_for"] = None
        self._audit[run_id].append({
            "kind": "transition", "from": cur, "to": target,
            "actor": actor, "via_hook": via_hook,
            "evidence": evidence or {}})

    def mark_waiting(self, run_id: str, what: str) -> None:
        """人工 gate checkpoint：记录等待事项（可恢复可回放）。"""
        run = self._run(run_id)
        run["waiting_for"] = what
        self._audit[run_id].append({"kind": "waiting", "for": what})

    def audit_trail(self, run_id: str) -> list[dict[str, Any]]:
        return list(self._audit.get(run_id, []))

    # ---- checkpoint / restore ----

    def checkpoint(self, run_id: str) -> dict[str, Any]:
        run = self._run(run_id)
        return {"run": dict(run),
                "waiting_for": run.get("waiting_for"),
                "audit": list(self._audit[run_id])}

    @classmethod
    def restore(cls, cp: dict[str, Any]) -> "TrainingControlGraph":
        g = cls()
        run = dict(cp["run"])
        g._runs[run["run_id"]] = run
        g._audit[run["run_id"]] = list(cp.get("audit", []))
        return g
