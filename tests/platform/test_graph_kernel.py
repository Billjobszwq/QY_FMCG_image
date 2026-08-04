"""W7 Graph Kernel TDD：版本化、Run 状态机、Checkpoint、预算/超时、幂等重试、人工门。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.platform.data.store import PlatformStore
from src.platform.kernel.definition import (
    GraphDefinition,
    GraphRegistry,
    GraphVersionError,
    NodeSpec,
)
from src.platform.kernel.engine import (
    BudgetExceeded,
    GraphEngine,
    NodeContext,
)


@pytest.fixture()
def store(tmp_path: Path) -> PlatformStore:
    s = PlatformStore(tmp_path / "platform.sqlite")
    yield s
    s.close()


def _graph(name="g", version="1", nodes=("a", "b")) -> GraphDefinition:
    return GraphDefinition(name=name, version=version, nodes=[NodeSpec(node_name=n) for n in nodes])


def _handlers(calls: dict[str, int], outputs=None):
    def make(node: str):
        def h(ctx: NodeContext) -> dict:
            calls[node] = calls.get(node, 0) + 1
            return (outputs or {}).get(node, {"done": node})
        return h
    return {n: make(n) for n in ("a", "b", "c", "d")}


# ---------- 版本化 ----------

def test_graph_version_immutable() -> None:
    reg = GraphRegistry()
    reg.register(_graph(nodes=("a",)))
    with pytest.raises(GraphVersionError):
        reg.register(_graph(nodes=("a", "b")))  # 同名同版本不同内容 → 拒绝
    reg.register(_graph(version="2", nodes=("a", "b")))  # 新版本允许
    assert reg.get("g", "1").nodes[0].node_name == "a"
    assert len(reg.get("g", "2").nodes) == 2


def test_unknown_graph_raises() -> None:
    reg = GraphRegistry()
    with pytest.raises(GraphVersionError):
        reg.get("nope", "1")


# ---------- 基本执行 + 持久化 ----------

def test_run_completes_and_persists(store: PlatformStore) -> None:
    reg = GraphRegistry()
    reg.register(_graph())
    engine = GraphEngine(store, reg)
    run = engine.start_run("g", "1", {"x": 1})
    calls: dict[str, int] = {}
    out = engine.execute(run["run_id"], _handlers(calls))
    assert out["status"] == "completed"
    assert calls == {"a": 1, "b": 1}
    nodes = store.list_nodes(run["run_id"])
    assert [n["node_name"] for n in nodes] == ["a", "b"]
    assert all(n["status"] == "completed" for n in nodes)
    assert store.get_run(run["run_id"])["status"] == "completed"


def test_idempotent_start_run(store: PlatformStore) -> None:
    reg = GraphRegistry()
    reg.register(_graph())
    engine = GraphEngine(store, reg)
    r1 = engine.start_run("g", "1", {}, idempotency_key="k1")
    r2 = engine.start_run("g", "1", {}, idempotency_key="k1")
    assert r1["run_id"] == r2["run_id"]
    assert len(store.list_runs()) == 1


def test_retry_does_not_repeat_completed_nodes(store: PlatformStore) -> None:
    reg = GraphRegistry()
    reg.register(_graph())
    engine = GraphEngine(store, reg)

    calls: dict[str, int] = {}
    failing = {
        "a": lambda ctx: {"ok": True},
        "b": lambda ctx: (_ for _ in ()).throw(RuntimeError("boom")),
    }
    calls["a"] = 0
    run = engine.start_run("g", "1", {})
    out = engine.execute(run["run_id"], failing)
    assert out["status"] == "failed"
    # 重试：a 已完成不得重复执行（幂等），b 再试
    calls.clear()

    def rec(node: str):
        def h(ctx: NodeContext) -> dict:
            calls[node] = calls.get(node, 0) + 1
            return {"ok": True}
        return h

    ok = {"a": rec("a"), "b": rec("b")}
    out2 = engine.execute(run["run_id"], ok)
    assert out2["status"] == "completed"
    assert calls.get("a", 0) == 0, "已完成节点不得重复执行（副作用不重复）"
    assert calls.get("b", 0) == 1


# ---------- 人工门 ----------

def test_human_gate_pause_and_resume(store: PlatformStore) -> None:
    reg = GraphRegistry()
    reg.register(_graph(nodes=("a", "gate", "b")))
    engine = GraphEngine(store, reg)
    run = engine.start_run("g", "1", {})

    def gate(ctx: NodeContext) -> dict:
        if not ctx.checkpoint_get("human_approved"):
            ctx.request_human("需要人工确认")
        return {"approved": True}

    handlers = {
        "a": lambda ctx: {"ok": True},
        "gate": gate,
        "b": lambda ctx: {"ok": True},
    }
    out = engine.execute(run["run_id"], handlers)
    assert out["status"] == "waiting_human"
    # 未批准前 execute 仍 waiting_human（不前进）
    out2 = engine.execute(run["run_id"], handlers)
    assert out2["status"] == "waiting_human"
    engine.approve_human_gate(run["run_id"], approved=True, actor="tester")
    out3 = engine.execute(run["run_id"], handlers)
    assert out3["status"] == "completed"
    assert store.get_run(run["run_id"])["status"] == "completed"


def test_human_gate_reject_fails_run(store: PlatformStore) -> None:
    reg = GraphRegistry()
    reg.register(_graph(nodes=("gate",)))
    engine = GraphEngine(store, reg)
    run = engine.start_run("g", "1", {})
    engine.execute(run["run_id"], {"gate": lambda ctx: ctx.request_human("审")})
    engine.approve_human_gate(run["run_id"], approved=False, actor="tester")
    out = engine.execute(run["run_id"], {"gate": lambda ctx: ctx.request_human("审")})
    assert out["status"] == "failed"


# ---------- 预算/超时/循环 ----------

def test_max_nodes_budget(store: PlatformStore) -> None:
    reg = GraphRegistry()
    reg.register(_graph(nodes=("a", "b", "c")))
    engine = GraphEngine(store, reg, max_nodes=2)
    run = engine.start_run("g", "1", {})
    with pytest.raises(BudgetExceeded):
        engine.execute(run["run_id"], _handlers({}))
    assert store.get_run(run["run_id"])["status"] == "failed"


def test_timeout_budget(store: PlatformStore) -> None:
    reg = GraphRegistry()
    reg.register(_graph(nodes=("a", "b")))
    engine = GraphEngine(store, reg, timeout_s=0.0)
    run = engine.start_run("g", "1", {})
    out = engine.execute(run["run_id"], _handlers({}))
    assert out["status"] == "failed"
    assert "timeout" in (store.get_run(run["run_id"])["error"] or "")


def test_max_loops_budget(store: PlatformStore) -> None:
    reg = GraphRegistry()
    reg.register(_graph(nodes=("a",)))
    engine = GraphEngine(store, reg, max_loops=2)
    run = engine.start_run("g", "1", {})
    # 模拟同一节点反复重执行（attempt 递增）
    handler = {"a": lambda ctx: (_ for _ in ()).throw(RuntimeError("retry"))}
    for _ in range(2):
        engine.execute(run["run_id"], handler)  # attempt 1, 2 → failed
    with pytest.raises(BudgetExceeded):
        engine.execute(run["run_id"], handler)  # attempt 3 超 max_loops


# ---------- checkpoint ----------

def test_checkpoint_persists_across_engine_restart(store: PlatformStore) -> None:
    reg = GraphRegistry()
    reg.register(_graph(nodes=("a", "b")))
    engine = GraphEngine(store, reg)
    run = engine.start_run("g", "1", {})

    def a(ctx: NodeContext) -> dict:
        ctx.checkpoint_set("progress", 7)
        return {"ok": True}

    engine.execute(run["run_id"], {"a": a, "b": lambda ctx: (_ for _ in ()).throw(RuntimeError("x"))})
    # 新 engine 实例（模拟进程重启）读 checkpoint
    engine2 = GraphEngine(store, reg)
    cp = store.load_checkpoint(run["run_id"], "a")
    assert cp and cp.get("progress") == 7
    assert engine2 is not engine
