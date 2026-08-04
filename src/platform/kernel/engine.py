"""W7 Graph Kernel：执行引擎。

语义：
- Run 状态机：pending/running/waiting_human/completed/failed/cancelled（store 层 CHECK）；
- 已完成节点重试时不重复执行（副作用幂等）；
- 人工门：request_human → waiting_human 暂停；approve 后恢复；reject → failed；
- 预算：max_nodes（单次 execute 节点执行数）、max_loops（同节点 attempt 上限）、timeout_s；
- 所有状态经 PlatformStore 持久化，进程重启后可恢复查询/续跑。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Callable, Mapping

from ..data.store import PlatformStore
from .definition import GraphRegistry

_GATE_MARKER = "__gate__"


class BudgetExceeded(Exception):
    """max_nodes / max_loops 超限。"""


class HumanGateRequested(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class NodeContext:
    def __init__(self, store: PlatformStore, run_id: str, node_name: str, run_input: dict):
        self._store = store
        self.run_id = run_id
        self.node_name = node_name
        self.run_input = run_input

    def checkpoint_get(self, key: str) -> Any:
        cp = self._store.load_checkpoint(self.run_id, self.node_name)
        return (cp or {}).get(key)

    def checkpoint_set(self, key: str, value: Any) -> None:
        cp = self._store.load_checkpoint(self.run_id, self.node_name) or {}
        cp[key] = value
        self._store.save_checkpoint(self.run_id, node_name=self.node_name, payload=cp)

    def request_human(self, reason: str) -> None:
        raise HumanGateRequested(reason)


NodeHandler = Callable[[NodeContext], Mapping[str, Any]]


class GraphEngine:
    def __init__(
        self,
        store: PlatformStore,
        registry: GraphRegistry,
        *,
        max_nodes: int = 50,
        max_loops: int = 10,
        timeout_s: float = 300.0,
    ) -> None:
        self._store = store
        self._registry = registry
        self._max_nodes = max_nodes
        self._max_loops = max_loops
        self._timeout_s = timeout_s

    # ---------- run 生命周期 ----------

    def start_run(
        self,
        graph_name: str,
        graph_version: str,
        input_payload: Mapping[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> dict:
        if idempotency_key is not None:
            existing = self._store.find_run_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing
        self._registry.get(graph_name, graph_version)  # fail fast：未注册 Graph 拒绝启动
        run_id = uuid.uuid4().hex
        return self._store.create_run(
            run_id=run_id,
            graph_name=graph_name,
            graph_version=graph_version,
            input_payload=dict(input_payload),
            idempotency_key=idempotency_key,
        )

    def execute(self, run_id: str, handlers: Mapping[str, NodeHandler]) -> dict:
        run = self._store.get_run(run_id)
        if run["status"] in ("completed", "cancelled", "waiting_human"):
            return run
        marker = self._store.load_checkpoint(run_id, _GATE_MARKER)
        if marker and marker.get("rejected"):
            return run  # 人工拒绝为终态，不再重试
        defn = self._registry.get(run["graph_name"], run["graph_version"])
        run_input = json.loads(run["input_json"] or "{}")
        self._store.set_run_status(run_id, "running")
        t0 = time.monotonic()
        executed = 0

        for seq, spec in enumerate(defn.nodes, start=1):
            attempts = [
                n for n in self._store.list_nodes(run_id) if n["node_name"] == spec.node_name
            ]
            if any(a["status"] == "completed" for a in attempts):
                continue  # 幂等：已完成节点不重复执行

            attempt_no = len(attempts) + 1
            if attempt_no > self._max_loops:
                self._store.set_run_status(
                    run_id, "failed", error=f"budget: max_loops={self._max_loops} ({spec.node_name})"
                )
                raise BudgetExceeded(f"节点 {spec.node_name} attempt {attempt_no} 超 max_loops")
            if executed >= self._max_nodes:
                self._store.set_run_status(
                    run_id, "failed", error=f"budget: max_nodes={self._max_nodes}"
                )
                raise BudgetExceeded(f"单次执行节点数超 max_nodes={self._max_nodes}")
            if (time.monotonic() - t0) > self._timeout_s:
                self._store.set_run_status(
                    run_id, "failed", error=f"timeout: >{self._timeout_s}s"
                )
                return self._store.get_run(run_id)

            handler = handlers.get(spec.node_name)
            if handler is None:
                self._store.start_node(run_id, node_name=spec.node_name, seq=seq, attempt=attempt_no)
                self._store.finish_node(
                    run_id, node_name=spec.node_name, seq=seq, attempt=attempt_no,
                    status="failed", error="handler_missing",
                )
                self._store.set_run_status(run_id, "failed", error=f"handler_missing: {spec.node_name}")
                return self._store.get_run(run_id)

            self._store.start_node(run_id, node_name=spec.node_name, seq=seq, attempt=attempt_no)
            ctx = NodeContext(self._store, run_id, spec.node_name, run_input)
            try:
                output = dict(handler(ctx))
            except HumanGateRequested as e:
                self._store.finish_node(
                    run_id, node_name=spec.node_name, seq=seq, attempt=attempt_no,
                    status="pending", error=f"waiting_human: {e.reason}",
                )
                self._store.save_checkpoint(
                    run_id, node_name=_GATE_MARKER,
                    payload={"node": spec.node_name, "reason": e.reason},
                )
                self._store.set_run_status(run_id, "waiting_human")
                return self._store.get_run(run_id)
            except Exception as e:  # noqa: BLE001 — 节点失败 → run failed（attempt 已记录）
                self._store.finish_node(
                    run_id, node_name=spec.node_name, seq=seq, attempt=attempt_no,
                    status="failed", error=f"{type(e).__name__}: {e}",
                )
                self._store.set_run_status(run_id, "failed", error=f"{type(e).__name__}: {e}")
                return self._store.get_run(run_id)

            self._store.finish_node(
                run_id, node_name=spec.node_name, seq=seq, attempt=attempt_no,
                status="completed", output_payload=output,
            )
            executed += 1

        self._store.set_run_status(run_id, "completed")
        return self._store.get_run(run_id)

    # ---------- 人工门 ----------

    def approve_human_gate(self, run_id: str, *, approved: bool, actor: str = "human") -> dict:
        marker = self._store.load_checkpoint(run_id, _GATE_MARKER)
        if marker is None:
            raise BudgetExceeded(f"run {run_id} 无待审批人工门")
        node_name = marker["node"]
        if approved:
            self._store.save_checkpoint(run_id, node_name=node_name, payload={"human_approved": True})
            self._store.set_run_status(run_id, "running")
            self._store.append_audit(
                actor=actor, action="gate.approved", subject_type="run", subject_id=run_id,
                detail={"node": node_name},
            )
        else:
            self._store.save_checkpoint(
                run_id, node_name=_GATE_MARKER, payload={**marker, "rejected": True}
            )
            self._store.set_run_status(run_id, "failed", error="human_rejected")
            self._store.append_audit(
                actor=actor, action="gate.rejected", subject_type="run", subject_id=run_id,
                detail={"node": node_name},
            )
        return self._store.get_run(run_id)
