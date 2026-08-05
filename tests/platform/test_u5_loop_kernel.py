"""U5-1 红测试：Graph+Loop v2 内核。

手册 §七/U5：typed edges、条件路由、feedback loop、收敛条件、
每轮预算、人工门、恢复和回放；fixed for-loop 保留为 sequential v1
（既有 GraphEngine 测试不动）。

口径：
- 每轮决策必须记录 轮次/节点/决策原因/下一节点/证据（decision trail）；
- 人工门暂停后可恢复；预算（max_rounds/budget_per_round）超限即停
  且 stop_reason 明确；
- 状态全部经 PlatformStore 持久化，新引擎实例可续跑（恢复/回放）。
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def store(tmp_path: Path):
    from src.platform.data.store import PlatformStore

    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _branch_graph():
    from src.platform.kernel.loop import EdgeSpec, GraphV2

    return GraphV2(
        name="branch_demo", version="v1", entry="quality",
        nodes=("quality", "accept", "reject"),
        edges=(
            EdgeSpec(src="quality", dst="accept",
                     edge_type="next", when="pass"),
            EdgeSpec(src="quality", dst="reject",
                     edge_type="on_fail", when="fail"),
        ))


class TestTypedEdgesAndRouting:
    def test_conditional_routing_both_branches(self, store):
        from src.platform.kernel.loop import LoopEngine

        g = _branch_graph()

        def make_handlers(verdict):
            return {
                "quality": lambda ctx: {"verdict": verdict},
                "accept": lambda ctx: {"ok": True},
                "reject": lambda ctx: {"rejected": True},
            }

        def router(output, state):
            return output["verdict"]  # pass→accept / fail→reject

        for verdict, last in (("pass", "accept"), ("fail", "reject")):
            eng = LoopEngine(store)
            run = eng.start_run(g, {"case": verdict})
            out = eng.execute(run["run_id"], make_handlers(verdict),
                              routers={"quality": router})
            assert out["status"] == "completed"
            trail = eng.decision_trail(run["run_id"])
            routed = trail[0]
            assert routed["node"] == "quality"
            assert routed["next"] == last
            assert routed["round"] == 1
            assert routed["reason"], "决策原因不得为空"
            assert trail[-1]["node"] == last

    def test_unknown_route_fails_closed(self, store):
        from src.platform.kernel.loop import LoopEngine

        eng = LoopEngine(store)
        run = eng.start_run(_branch_graph(), {})
        out = eng.execute(
            run["run_id"],
            {"quality": lambda ctx: {"verdict": "maybe"},
             "accept": lambda ctx: {}, "reject": lambda ctx: {}},
            routers={"quality": lambda o, s: o["verdict"]})
        assert out["status"] == "failed", \
            "路由到未定义 edge 必须 fail-closed"
        assert "no_edge" in (out.get("error") or "")


class TestFeedbackLoop:
    def _loop_graph(self, max_rounds=5):
        from src.platform.kernel.loop import EdgeSpec, GraphV2

        return GraphV2(
            name="feedback_demo", version="v1", entry="prep",
            nodes=("prep", "quality", "exit"),
            edges=(
                EdgeSpec(src="prep", dst="quality", edge_type="next"),
                EdgeSpec(src="quality", dst="prep",
                         edge_type="feedback", when="has_fails"),
                EdgeSpec(src="quality", dst="exit",
                         edge_type="next", when="converged"),
            ),
            max_rounds=max_rounds)

    def test_feedback_converges_and_counts_rounds(self, store):
        from src.platform.kernel.loop import LoopEngine

        fails = {"n": 2}  # 每轮修复一个，第 3 轮收敛

        def quality(ctx):
            return {"fails_left": fails["n"]}

        def router(output, state):
            if output["fails_left"] > 0:
                fails["n"] -= 1
                return "has_fails"
            return "converged"

        eng = LoopEngine(store)
        run = eng.start_run(self._loop_graph(), {})
        out = eng.execute(run["run_id"],
                          {"prep": lambda ctx: {"round_prep": True},
                           "quality": quality, "exit": lambda ctx: {}},
                          routers={"quality": router})
        assert out["status"] == "completed"
        trail = eng.decision_trail(run["run_id"])
        rounds = {d["round"] for d in trail}
        assert max(rounds) == 3, "2 次 feedback + 收敛轮 = 3 轮"
        fb = [d for d in trail if d["decision"] == "feedback"]
        assert len(fb) == 2 and fb[0]["next"] == "prep"

    def test_budget_stop_with_reason(self, store):
        from src.platform.kernel.loop import LoopEngine

        eng = LoopEngine(store)
        run = eng.start_run(self._loop_graph(max_rounds=2), {})
        out = eng.execute(
            run["run_id"],
            {"prep": lambda ctx: {},
             "quality": lambda ctx: {"fails_left": 99},
             "exit": lambda ctx: {}},
            routers={"quality": lambda o, s: "has_fails"})
        assert out["status"] == "failed"
        assert out["stop_reason"] == "budget_rounds"
        assert "max_rounds=2" in (out.get("error") or "")


class TestHumanGateAndRecovery:
    def test_human_gate_pause_resume(self, store):
        from src.platform.kernel.loop import LoopEngine

        g = _branch_graph()
        gate_done = {"asked": False}

        def quality(ctx):
            if not gate_done["asked"]:
                gate_done["asked"] = True
                ctx.request_human("质量结论需人工确认")
            return {"verdict": "pass"}

        eng = LoopEngine(store)
        run = eng.start_run(g, {})
        out = eng.execute(run["run_id"],
                          {"quality": quality,
                           "accept": lambda ctx: {},
                           "reject": lambda ctx: {}},
                          routers={"quality": lambda o, s: o["verdict"]})
        assert out["status"] == "waiting_human"

        # 模拟进程重启：全新引擎实例从 store 恢复续跑
        eng2 = LoopEngine(store)
        eng2.approve_human_gate(run["run_id"], approved=True,
                                actor="admin")
        out2 = eng2.execute(run["run_id"],
                            {"quality": quality,
                             "accept": lambda ctx: {"ok": True},
                             "reject": lambda ctx: {}},
                            routers={"quality":
                                     lambda o, s: o["verdict"]})
        assert out2["status"] == "completed"
        trail = eng2.decision_trail(run["run_id"])
        gates = [d for d in trail if d["decision"] == "human_gate"]
        assert gates and gates[0]["reason"] == "质量结论需人工确认"

    def test_reject_is_terminal(self, store):
        from src.platform.kernel.loop import LoopEngine

        eng = LoopEngine(store)
        run = eng.start_run(_branch_graph(), {})
        eng.execute(run["run_id"],
                    {"quality": lambda ctx: ctx.request_human("stop"),
                     "accept": lambda ctx: {}, "reject": lambda ctx: {}},
                    routers={"quality": lambda o, s: "pass"})
        eng.approve_human_gate(run["run_id"], approved=False,
                               actor="admin")
        out = eng.execute(run["run_id"],
                          {"quality": lambda ctx: {"verdict": "pass"},
                           "accept": lambda ctx: {},
                           "reject": lambda ctx: {}},
                          routers={"quality": lambda o, s: "pass"})
        assert out["status"] == "failed", "人工拒绝为终态"
