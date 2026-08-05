"""U5-1：Graph+Loop v2 内核 —— typed edges、条件路由、feedback loop。

与 sequential v1（GraphEngine，fixed for-loop）并存、互不影响：
- EdgeSpec(edge_type: next/on_fail/feedback) + when 标签；路由由 routers
  决定（router(output, state) -> when 标签）；未匹配 edge 一律 fail-closed；
- feedback edge 回跳并使轮次 +1；轮次超 max_rounds → failed +
  stop_reason="budget_rounds"（每轮预算/收敛条件）；
- 人工门复用 v1 的 HumanGateRequested：暂停 waiting_human，approve 后
  全新引擎实例可从 store 恢复续跑；reject 为终态；
- decision trail（轮次/节点/决策/原因/下一节点）与续跑位置全部经
  checkpoint 持久化，可恢复、可回放。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping

from ..data.store import PlatformStore
from .engine import HumanGateRequested, NodeContext

_STATE = "__loop_state__"
_GRAPH = "__loop_graph__"
_GATE = "__gate__"
_SHARED = "__loop_shared__"

EDGE_TYPES = ("next", "on_fail", "feedback")


class LoopNodeContext(NodeContext):
    """v2 节点上下文：在 v1 基础上增加轮次、跨节点共享状态与门状态查询。"""

    def __init__(self, store: PlatformStore, run_id: str, node_name: str,
                 run_input: dict, round_no: int) -> None:
        super().__init__(store, run_id, node_name, run_input)
        self.round = round_no

    def shared_get(self, key: str, default: Any = None) -> Any:
        cp = self._store.load_checkpoint(self.run_id, _SHARED) or {}
        return cp.get(key, default)

    def shared_set(self, key: str, value: Any) -> None:
        cp = self._store.load_checkpoint(self.run_id, _SHARED) or {}
        cp[key] = value
        self._store.save_checkpoint(self.run_id, node_name=_SHARED, payload=cp)

    def gate_approved(self) -> bool:
        m = self._store.load_checkpoint(self.run_id, _GATE) or {}
        return bool(m.get("approved")) and not m.get("rejected")


@dataclass(frozen=True)
class EdgeSpec:
    src: str
    dst: str
    edge_type: str = "next"
    when: str | None = None

    def __post_init__(self) -> None:
        if self.edge_type not in EDGE_TYPES:
            raise ValueError(f"非法 edge_type: {self.edge_type}")


@dataclass(frozen=True)
class GraphV2:
    name: str
    version: str
    entry: str
    nodes: tuple[str, ...] = field(default_factory=tuple)
    edges: tuple[EdgeSpec, ...] = field(default_factory=tuple)
    max_rounds: int = 5

    def __post_init__(self) -> None:
        if self.entry not in self.nodes:
            raise ValueError(f"entry 不在 nodes 中: {self.entry}")
        for e in self.edges:
            if e.src not in self.nodes or e.dst not in self.nodes:
                raise ValueError(f"edge 引用了未定义节点: {e.src}->{e.dst}")
        if self.max_rounds < 1:
            raise ValueError("max_rounds 必须 >= 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "entry": self.entry,
            "nodes": list(self.nodes),
            "edges": [asdict(e) for e in self.edges],
            "max_rounds": self.max_rounds,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "GraphV2":
        return cls(
            name=d["name"],
            version=d["version"],
            entry=d["entry"],
            nodes=tuple(d["nodes"]),
            edges=tuple(EdgeSpec(**e) for e in d["edges"]),
            max_rounds=d["max_rounds"],
        )


class LoopEngine:
    """Graph+Loop v2 执行引擎（状态全部经 PlatformStore 持久化）。"""

    def __init__(self, store: PlatformStore) -> None:
        self._store = store

    # ---------- run 生命周期 ----------

    def start_run(
        self,
        graph: GraphV2,
        input_payload: Mapping[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if idempotency_key is not None:
            existing = self._store.find_run_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing
        run_id = uuid.uuid4().hex
        run = self._store.create_run(
            run_id=run_id,
            graph_name=graph.name,
            graph_version=graph.version,
            input_payload=dict(input_payload),
            idempotency_key=idempotency_key,
        )
        # 图结构随 run 持久化：新引擎实例无需注册表即可恢复
        self._store.save_checkpoint(run_id, node_name=_GRAPH, payload=graph.to_dict())
        return run

    def execute(
        self,
        run_id: str,
        handlers: Mapping[str, Callable[[NodeContext], Mapping[str, Any]]],
        routers: Mapping[str, Callable[[Mapping[str, Any], dict], Any]] | None = None,
    ) -> dict[str, Any]:
        routers = routers or {}
        run = self._store.get_run(run_id)
        if run["status"] in ("completed", "cancelled", "failed"):
            return self._view(run)
        if run["status"] == "waiting_human":
            marker = self._store.load_checkpoint(run_id, _GATE)
            if not marker or not marker.get("approved"):
                return self._view(run)  # 未批准：保持等待，不得绕过人工门

        graph = self._graph(run_id)
        state = self._state(run_id) or {
            "round": 1, "node": graph.entry, "seq": 0, "trail": [], "outputs": {},
        }
        run_input = json.loads(run["input_json"] or "{}")
        self._store.set_run_status(run_id, "running")

        node = state["node"]
        rnd = state["round"]
        while True:
            state["seq"] += 1
            seq = state["seq"]
            handler = handlers.get(node)
            if handler is None:
                self._store.start_node(run_id, node_name=node, seq=seq, attempt=rnd)
                self._store.finish_node(
                    run_id, node_name=node, seq=seq, attempt=rnd,
                    status="failed", error="handler_missing",
                )
                return self._fail(run_id, state, f"handler_missing: {node}")

            self._store.start_node(run_id, node_name=node, seq=seq, attempt=rnd)
            ctx = LoopNodeContext(self._store, run_id, f"{node}#r{rnd}",
                                  run_input, rnd)
            try:
                output = dict(handler(ctx))
            except HumanGateRequested as e:
                self._store.finish_node(
                    run_id, node_name=node, seq=seq, attempt=rnd,
                    status="pending", error=f"waiting_human: {e.reason}",
                )
                state["trail"].append({
                    "round": rnd, "node": node, "decision": "human_gate",
                    "reason": e.reason, "next": None,
                })
                state["node"] = node
                state["round"] = rnd
                self._save_state(run_id, state)
                self._store.save_checkpoint(
                    run_id, node_name=_GATE,
                    payload={"node": node, "round": rnd, "reason": e.reason},
                )
                self._store.set_run_status(run_id, "waiting_human")
                return self._view(self._store.get_run(run_id))
            except Exception as e:  # noqa: BLE001 — 节点失败 fail-closed
                self._store.finish_node(
                    run_id, node_name=node, seq=seq, attempt=rnd,
                    status="failed", error=f"{type(e).__name__}: {e}",
                )
                return self._fail(run_id, state, f"{type(e).__name__}: {e}")

            self._store.finish_node(
                run_id, node_name=node, seq=seq, attempt=rnd,
                status="completed", output_payload=output,
            )
            state["outputs"][node] = output

            edges = [e for e in graph.edges if e.src == node]
            if not edges:
                # 无出边 = 终点节点，run 完成
                state["trail"].append({
                    "round": rnd, "node": node, "decision": "terminal",
                    "reason": "无出边，到达终点", "next": None,
                })
                state["node"] = None
                self._save_state(run_id, state)
                self._store.set_run_status(
                    run_id, "completed", output_payload=state["outputs"]
                )
                return self._view(self._store.get_run(run_id))

            edge = self._route(node, edges, output, state, routers)
            if edge is None:
                return self._fail(
                    run_id, state,
                    f"no_edge: {node} label={state.get('_label')!r}",
                    stop_reason="no_edge",
                )
            state["trail"].append({
                "round": rnd, "node": node, "decision": edge.edge_type,
                "reason": f"route label={state.get('_label')!r} via "
                          f"{edge.edge_type} -> {edge.dst}",
                "next": edge.dst,
            })
            if edge.edge_type == "feedback":
                rnd += 1
                if rnd > graph.max_rounds:
                    state["node"] = edge.dst
                    state["round"] = rnd
                    return self._fail(
                        run_id, state,
                        f"budget: max_rounds={graph.max_rounds} 超限"
                        f"（feedback {node}->{edge.dst}）",
                        stop_reason="budget_rounds",
                    )
            node = edge.dst
            state["node"] = node
            state["round"] = rnd
            self._save_state(run_id, state)

    # ---------- 人工门 ----------

    def approve_human_gate(
        self, run_id: str, *, approved: bool, actor: str = "human"
    ) -> dict[str, Any]:
        marker = self._store.load_checkpoint(run_id, _GATE)
        if not marker or marker.get("approved") or marker.get("rejected"):
            raise ValueError(f"run {run_id} 无待审批人工门")
        if approved:
            self._store.save_checkpoint(
                run_id, node_name=_GATE,
                payload={**marker, "approved": True, "actor": actor},
            )
            self._store.set_run_status(run_id, "running")
            action = "gate.approved"
        else:
            self._store.save_checkpoint(
                run_id, node_name=_GATE,
                payload={**marker, "rejected": True, "actor": actor},
            )
            self._store.set_run_status(run_id, "failed", error="human_rejected")
            action = "gate.rejected"
        self._store.append_audit(
            actor=actor, action=action, subject_type="run", subject_id=run_id,
            detail={"node": marker["node"], "round": marker.get("round")},
        )
        return self._view(self._store.get_run(run_id))

    # ---------- 决策轨迹（回放证据） ----------

    def decision_trail(self, run_id: str) -> list[dict[str, Any]]:
        state = self._state(run_id)
        return list((state or {}).get("trail", []))

    # ---------- 内部 ----------

    def _route(
        self,
        node: str,
        edges: list[EdgeSpec],
        output: Mapping[str, Any],
        state: dict[str, Any],
        routers: Mapping[str, Callable[[Mapping[str, Any], dict], Any]],
    ) -> EdgeSpec | None:
        if len(edges) == 1 and edges[0].when is None:
            state["_label"] = None
            return edges[0]
        router = routers.get(node)
        if router is None:
            state["_label"] = None
            return None  # 多条件边但无 router：fail-closed
        label = router(output, state)
        state["_label"] = label
        return next((e for e in edges if e.when == label), None)

    def _graph(self, run_id: str) -> GraphV2:
        payload = self._store.load_checkpoint(run_id, _GRAPH)
        if payload is None:
            raise ValueError(f"run {run_id} 缺少 GraphV2 定义（必须经 start_run 启动）")
        return GraphV2.from_dict(payload)

    def _state(self, run_id: str) -> dict[str, Any] | None:
        return self._store.load_checkpoint(run_id, _STATE)

    def _save_state(self, run_id: str, state: dict[str, Any]) -> None:
        self._store.save_checkpoint(run_id, node_name=_STATE, payload=state)

    def _fail(
        self,
        run_id: str,
        state: dict[str, Any],
        error: str,
        stop_reason: str | None = None,
    ) -> dict[str, Any]:
        state.pop("_label", None)
        self._save_state(run_id, state)
        payload = {"stop_reason": stop_reason} if stop_reason else None
        self._store.set_run_status(run_id, "failed", error=error, output_payload=payload)
        return self._view(self._store.get_run(run_id))

    def _view(self, run: dict[str, Any]) -> dict[str, Any]:
        view = dict(run)
        if run.get("output_json"):
            try:
                out = json.loads(run["output_json"])
            except (TypeError, ValueError):
                out = None
            if isinstance(out, dict) and out.get("stop_reason"):
                view["stop_reason"] = out["stop_reason"]
        return view
