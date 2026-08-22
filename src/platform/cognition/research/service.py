"""ResearchService：可恢复研究工作流（Task 9 / G7）。

不变量：
- run/state/step 全部持久化；resume 从断点续跑，已完成节点不重复执行、
  查询不重复消费；
- 预算（queries/steps/deadline）在每步前检查，超限诚实停止
  （stop_reason=budget_exhausted:*，不伪装完整）；
- sufficiency 发现冲突 → waiting_human，需人类裁决（decide_conflict）
  才继续；
- 每个节点挂统一 BusinessRun / NodeAttempt / Usage / Evidence。
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from ...scope import ExecutionContext
from ..context import CognitiveContext
from ..contracts import CognitiveQueryRequest
from ..errors import (
    CognitionConflictError,
    CognitionIntegrityError,
    CognitionPermissionDeniedError,
    CognitionPolicyError,
    CognitionValidationError,
)
from .budgets import budget_for, check_budget
from .graph import PIPELINE

_MODE_KINDS = {
    "lookup": ("knowledge",),
    "case_analysis": ("memory_l2", "knowledge"),
    "methodology": ("memory_l3", "skill"),
    "deep_research": ("knowledge", "memory_l2", "memory_l3", "skill"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-" + uuid.uuid4().hex[:14]


class ResearchService:
    def __init__(self, store: Any, *, gateway: Any,
                 clock: Callable[[], float] | None = None,
                 verifier: Any = None, synthesizer: Any = None,
                 planner: Any = None) -> None:
        self.store = store
        self.gateway = gateway
        self._clock = clock or time.time
        # R2-04：终态 UoW 需要引证门与报告构造端口（默认懒构造，
        # 避免循环 import；composition 显式注入共享实例）。
        if verifier is None:
            from .citations import CitationVerifier
            verifier = CitationVerifier(store)
        if synthesizer is None:
            from .synthesizer import Synthesizer
            synthesizer = Synthesizer(store)
        if planner is None:
            from .planner import UnavailablePlannerProvider
            planner = UnavailablePlannerProvider()
        self.verifier = verifier
        self.synthesizer = synthesizer
        self.planner = planner

    # ---------- run 生命周期 ----------

    def start(self, ctx: CognitiveContext, *, question: str,
              mode: str = "lookup", budget: dict | None = None,
              corpus_snapshot_id: str = "",
              fault: Callable[[str], None] | None = None) -> dict:
        if ctx is None:
            raise CognitionValidationError("缺 CognitiveContext")
        if not question or not question.strip():
            raise CognitionValidationError("question 必填")
        if mode not in _MODE_KINDS:
            raise CognitionValidationError(f"非法 mode: {mode}")
        research_run_id = _new_id("rrun")
        business_run_id = _new_id("run")
        work_id = _new_id("work")
        b = budget_for(mode, budget)
        # 统一 BusinessRun / WorkItem / 事件（与 workflow/agent 同协议）
        self.store.insert_business_run({
            "run_id": business_run_id, "work_id": work_id,
            "tenant_id": ctx.tenant_id, "customer_id": ctx.customer_id,
            "project_id": ctx.project_id, "trigger_type": "research",
            "correlation_id": ctx.correlation_id,
            "initiator_type": "human", "initiator_id": ctx.principal_id,
            "status": "queued", "command_kind": "research.run",
            "params": {"research_run_id": research_run_id, "mode": mode},
            "data_scope": ctx.data_scope, "test_run_id": ctx.test_run_id})
        self.store.insert_work_item_v2({
            "work_id": work_id, "run_id": business_run_id,
            "status": "running", "owner_type": "system",
            "owner_id": "research_service",
            "title": f"研究：{question[:60]}",
            "business_summary": question[:120],
            "data_scope": ctx.data_scope})
        self.store.emit_event(
            event_id=_new_id("evt"), event_type="research.started",
            run_id=business_run_id, work_id=work_id,
            correlation_id=ctx.correlation_id, actor_type="human",
            actor_id=ctx.principal_id,
            payload={"research_run_id": research_run_id, "mode": mode})
        self.store.set_business_run_status(business_run_id, "running",
                                           current_node="classify")
        conn = self.store._conn
        conn.execute(
            "INSERT INTO research_run_v1 (research_run_id,"
            " business_run_id, question, mode, budget_json,"
            " consumed_json, state_json, status, tenant_id, customer_id,"
            " project_id, data_scope, test_run_id, permission_tags_json,"
            " created_by, created_at, updated_at, corpus_snapshot_id)"
            " VALUES (?,?,?,?,?, '{}', '{}', 'running',?,?,?,?,?,?,?,?,?,?)",
            (research_run_id, business_run_id, question, mode,
             json.dumps(b), ctx.tenant_id, ctx.customer_id,
             ctx.project_id, ctx.data_scope, ctx.test_run_id,
             json.dumps(list(ctx.permission_tags)), ctx.principal_id,
             _now(), _now(), corpus_snapshot_id))
        conn.commit()
        return self._advance(research_run_id, fault=fault)

    def _cas_acquire(self, research_run_id: str, expected_version: int,
                     from_statuses: tuple[str, ...], *,
                     new_status: str | None = None,
                     state_json: str | None = None,
                     stop_reason: str | None = None) -> bool:
        """乐观 CAS 获取：仅当 version 与 status 均匹配时才推进，
        version+1。并发 resume/cancel/decide 只有一个成功（R2-03）。"""
        sets = ["version=version+1", "updated_at=?"]
        vals: list = [_now()]
        if new_status is not None:
            sets.append("status=?"); vals.append(new_status)
        if state_json is not None:
            sets.append("state_json=?"); vals.append(state_json)
        if stop_reason is not None:
            sets.append("stop_reason=?"); vals.append(stop_reason)
        ph = ",".join("?" * len(from_statuses))
        rc = self.store._conn.execute(
            f"UPDATE research_run_v1 SET {','.join(sets)} WHERE"
            f" research_run_id=? AND version=? AND status IN ({ph})",
            (*vals, research_run_id, expected_version,
             *from_statuses)).rowcount
        self.store._conn.commit()
        return rc == 1

    def _require_run_scope(self, ctx: CognitiveContext | None,
                           run: dict) -> None:
        """服务端 scope 复核（R2-03）：run 持久化 scope 与 ctx 完全
        一致才允许操作。平台例外由 API 层以 run 派生 ctx 表达，服务层
        不做旁路。"""
        if ctx is None:
            raise CognitionValidationError("缺 CognitiveContext")
        if (run.get("tenant_id", "local") or "local") != ctx.tenant_id:
            raise CognitionPermissionDeniedError("tenant 不匹配")
        if (run.get("data_scope", "operational") or
                "operational") != ctx.data_scope:
            raise CognitionPermissionDeniedError("data_scope 不匹配")
        if (run.get("test_run_id", "") or "") != ctx.test_run_id:
            raise CognitionPermissionDeniedError("test_run 不匹配")
        if (run.get("customer_id", "") or "") != ctx.customer_id:
            raise CognitionPermissionDeniedError("customer 不匹配")
        if (run.get("project_id", "") or "") != ctx.project_id:
            raise CognitionPermissionDeniedError("project 不匹配")

    def _emit(self, run: dict, event_type: str, actor: str) -> None:
        """mutation 审计事件（best-effort；账本失败不阻断状态转换）。"""
        try:
            self.store.emit_event(
                event_id=_new_id("evt"), event_type=event_type,
                run_id=run["business_run_id"], work_id="",
                correlation_id="", actor_type="human", actor_id=actor,
                payload={"research_run_id": run["research_run_id"]})
        except Exception:
            pass

    def resume(self, research_run_id: str, *, ctx: CognitiveContext,
               fault: Callable[[str], None] | None = None) -> dict:
        run = self._load(research_run_id)
        self._require_run_scope(ctx, run)
        if run["status"] in ("succeeded", "cancelled"):
            return run
        if run["status"] == "waiting_human":
            raise CognitionConflictError(
                "run 等待人类裁决；请先 decide_conflict")
        if run["status"] == "running":
            # 推进中：no-op，不二次获取推进权（并发 resume 只有一个
            # 实际推进，R2-03）
            return run
        # CAS 获取推进权：仅 failed → running，version+1。并发双 resume
        # 只有一个成功；败者得到稳定 conflict。
        if not self._cas_acquire(research_run_id, run["version"],
                                 ("failed",), new_status="running"):
            raise CognitionConflictError(
                f"run {research_run_id} 并发 resume/cancel 竞争失败"
                "（CAS）")
        # 业务账本同步恢复（failed→running 合法 retry 跃迁）；失败则
        # 回滚 research 状态避免双账本漂移（R2-04 终态一致性）。
        try:
            self.store.set_business_run_status(run["business_run_id"],
                                               "running")
        except Exception as e:  # noqa: BLE001
            self.store._conn.execute(
                "UPDATE research_run_v1 SET status='failed',"
                " stop_reason='resume_business_sync_failed',"
                " version=version+1, updated_at=? WHERE"
                " research_run_id=? AND status='running'",
                (_now(), research_run_id))
            self.store._conn.commit()
            raise CognitionConflictError(
                f"run {research_run_id} resume 业务账本同步失败: {e}")
        self._emit(run, "research.resumed", ctx.principal_id)
        return self._advance(research_run_id, fault=fault)

    def cancel(self, research_run_id: str, *, actor: str,
               ctx: CognitiveContext) -> dict:
        run = self._load(research_run_id)
        self._require_run_scope(ctx, run)
        if run["status"] in ("succeeded", "cancelled"):
            return run
        # CAS：仅活动态可取消；并发只有一个成功
        if not self._cas_acquire(research_run_id, run["version"],
                                 ("running", "failed", "waiting_human"),
                                 new_status="cancelled",
                                 stop_reason="cancelled_by_user"):
            raise CognitionConflictError(
                f"run {research_run_id} 并发 cancel 竞争失败（CAS）")
        self.store.set_business_run_status(run["business_run_id"],
                                           "cancelled")
        self._emit(run, "research.cancelled", actor)
        return self._load(research_run_id)

    def decide_conflict(self, research_run_id: str, *, actor: str,
                        resolution: str, ctx: CognitiveContext,
                        fault: Callable[[str], None] | None = None
                        ) -> dict:
        """人类裁决冲突后恢复执行（03 §5 冲突需人类裁决）。"""
        run = self._load(research_run_id)
        self._require_run_scope(ctx, run)
        if run["status"] != "waiting_human":
            raise CognitionConflictError(
                f"run 不在 waiting_human（当前 {run['status']}）")
        if not resolution:
            raise CognitionValidationError("冲突裁决必须给出 resolution")
        state = json.loads(run["state_json"] or "{}")
        state["conflict_resolved"] = True
        state["conflict_resolution"] = resolution
        state["next"] = "claim"
        # CAS：仅 waiting_human 可裁决；并发双 decide 只有一个成功
        if not self._cas_acquire(research_run_id, run["version"],
                                 ("waiting_human",),
                                 new_status="running",
                                 state_json=json.dumps(
                                     state, ensure_ascii=False),
                                 stop_reason=None):
            raise CognitionConflictError(
                f"run {research_run_id} 并发 decide 竞争失败（CAS）")
        self._emit(run, "research.conflict_decided", actor)
        return self._advance(research_run_id, fault=fault)

    def _load(self, research_run_id: str) -> dict:
        """内部读取（不做 scope 复核；公共入口负责鉴权）。"""
        row = self.store._conn.execute(
            "SELECT * FROM research_run_v1 WHERE research_run_id=?",
            (research_run_id,)).fetchone()
        if row is None:
            raise CognitionValidationError(
                f"research run 不存在: {research_run_id}")
        d = dict(row)
        d["budget"] = json.loads(d["budget_json"] or "{}")
        d["consumed"] = json.loads(d["consumed_json"] or "{}")
        d["state"] = json.loads(d["state_json"] or "{}")
        return d

    def get_run(self, research_run_id: str, *,
                ctx: CognitiveContext | None = None) -> dict:
        run = self._load(research_run_id)
        if ctx is not None:
            self._require_run_scope(ctx, run)
        return run

    def list_claims(self, research_run_id: str, *,
                    ctx: CognitiveContext | None = None) -> list[dict]:
        if ctx is not None:
            self._require_run_scope(ctx, self._load(research_run_id))
        rows = self.store._conn.execute(
            "SELECT * FROM research_claim_v1 WHERE research_run_id=?"
            " ORDER BY created_at", (research_run_id,)).fetchall()
        return [dict(r) for r in rows]

    def list_queries(self, research_run_id: str, *,
                     ctx: CognitiveContext | None = None) -> list[dict]:
        if ctx is not None:
            self._require_run_scope(ctx, self._load(research_run_id))
        rows = self.store._conn.execute(
            "SELECT * FROM research_query_v1 WHERE research_run_id=?"
            " ORDER BY created_at", (research_run_id,)).fetchall()
        return [dict(r) for r in rows]

    # ---------- 推进引擎 ----------

    def _ctx_of(self, run: dict) -> CognitiveContext:
        return CognitiveContext(
            principal_id=run["created_by"], tenant_id=run["tenant_id"],
            customer_id=run["customer_id"], project_id=run["project_id"],
            test_run_id=run["test_run_id"], data_scope=run["data_scope"],
            action="cognition.research.start",
            permission_tags=tuple(json.loads(
                run["permission_tags_json"] or "[]")),
            purpose="research", correlation_id="", parent_run_id=None,
            as_of=datetime.now(timezone.utc))

    def _advance(self, research_run_id: str, *,
                 fault: Callable[[str], None] | None = None) -> dict:
        run = self._load(research_run_id)
        state = dict(run["state"])
        consumed = dict(run["consumed"])
        budget = run["budget"]
        state.setdefault("next", "classify")
        # deadline 以累计 elapsed（持久化在 state）计量：resume 不重置
        # （评审 #G7-3）。每步把本次 advance 的时钟增量累入 state.elapsed。
        last_tick = self._clock()

        while True:
            node = state.get("next")
            if node is None:
                break
            # 竞争复核（R2-03）：推进中若 cancel 已改写状态，立即停止，
            # 不得继续执行节点或覆盖终态。
            if self._load(research_run_id)["status"] != "running":
                break
            now = self._clock()
            state["elapsed"] = round(
                state.get("elapsed", 0.0) + max(0.0, now - last_tick), 6)
            last_tick = now
            # 步骤尝试计数（无论成功/失败，防无限重试，评审 #G7-9）
            consumed["steps"] = consumed.get("steps", 0) + 1
            self._persist_state(research_run_id, state, consumed)
            # 预算检查（每步前）
            violation = check_budget(consumed, budget)
            if violation:
                self._stop(research_run_id, "failed", violation,
                           state, consumed)
                return self._load(research_run_id)
            if state["elapsed"] > budget.get("deadline_seconds", 1800):
                self._stop(research_run_id, "failed",
                           "budget_exhausted:deadline", state, consumed)
                return self._load(research_run_id)
            # 故障注入钩子（resume 测试用）——在 try 内，使故障被记录
            # 为 failed step + run failed，从而可 resume。
            step_no = self._next_seq(research_run_id)
            step_id = _new_id("step")
            try:
                if fault is not None:
                    fault(node)
                handler = getattr(self, f"_node_{node}")
                out = handler(run, state, consumed)
            except Exception as e:  # noqa: BLE001
                # 错误分类（R2-04）：policy/integrity/node 稳定 stop reason
                if isinstance(e, CognitionConflictError):
                    reason = f"conflict:{node}"
                elif isinstance(e, CognitionPolicyError):
                    reason = f"policy_denied:{node}"
                elif isinstance(e, CognitionIntegrityError):
                    reason = f"integrity:{node}"
                else:
                    reason = f"node_error:{node}"
                self._record_step(research_run_id, step_id, step_no, node,
                                  "failed", {"error": str(e)[:300]})
                self._stop(research_run_id, "failed", reason, state,
                           consumed)
                return self._load(research_run_id)
            self._record_step(research_run_id, step_id, step_no, node,
                              "succeeded", out)
            self.store.upsert_node_execution(
                run["business_run_id"], f"research.{node}",
                node_type="research", status="succeeded",
                output_data=out)
            if node == "sufficiency" and out.get("waiting_human"):
                self._persist_state(research_run_id, state, consumed)
                rc = self.store._conn.execute(
                    "UPDATE research_run_v1 SET status='waiting_human',"
                    " stop_reason='conflict_requires_human',"
                    " version=version+1, updated_at=?"
                    " WHERE research_run_id=? AND status='running'",
                    (_now(), research_run_id)).rowcount
                self.store._conn.commit()
                if rc == 1:
                    self.store.set_business_run_status(
                        run["business_run_id"], "waiting_human",
                        current_node=node)
                return self._load(research_run_id)
            self._persist_state(research_run_id, state, consumed)
            if state.get("next") == "done":
                break
        return self._load(research_run_id)

    def _next_seq(self, research_run_id: str) -> int:
        row = self.store._conn.execute(
            "SELECT coalesce(max(seq),0)+1 n FROM research_step_v1 WHERE"
            " research_run_id=?", (research_run_id,)).fetchone()
        return row["n"]

    def _record_step(self, research_run_id: str, step_id: str, seq: int,
                     node: str, status: str, out: dict) -> None:
        conn = self.store._conn
        conn.execute(
            "INSERT INTO research_step_v1 (step_id, research_run_id,"
            " seq, node, status, output_json, error, started_at,"
            " ended_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (step_id, research_run_id, seq, node, status,
             json.dumps(out, ensure_ascii=False, default=str),
             out.get("error", "") if status == "failed" else "",
             _now(), _now() if status in ("succeeded", "failed")
             else None))
        conn.commit()

    def _persist_state(self, research_run_id: str, state: dict,
                       consumed: dict) -> None:
        self.store._conn.execute(
            "UPDATE research_run_v1 SET state_json=?, consumed_json=?,"
            " updated_at=? WHERE research_run_id=?",
            (json.dumps(state, ensure_ascii=False),
             json.dumps(consumed, ensure_ascii=False), _now(),
             research_run_id))
        self.store._conn.commit()

    def _stop(self, research_run_id: str, status: str, stop_reason: str,
              state: dict, consumed: dict) -> None:
        self._persist_state(research_run_id, state, consumed)
        run = self._load(research_run_id)
        # 条件终态转换（R2-03）：cancelled/succeeded 不被 failed 覆盖。
        rc = self.store._conn.execute(
            "UPDATE research_run_v1 SET status=?, stop_reason=?,"
            " version=version+1, updated_at=? WHERE research_run_id=?"
            " AND status IN ('running','failed')",
            (status, stop_reason, _now(), research_run_id)).rowcount
        self.store._conn.commit()
        if rc != 1:
            return  # 竞争终态（如 cancelled）获胜，保持现状
        biz_status = {"succeeded": "succeeded", "failed": "failed",
                      "cancelled": "cancelled"}.get(status, "failed")
        try:
            self.store.set_business_run_status(run["business_run_id"],
                                               biz_status,
                                               error=stop_reason)
        except Exception as e:  # noqa: BLE001
            # R2-04 错误诚实性：业务账本同步失败不得吞掉；发 critical
            # 告警并以分类错误上抛（保留 research failed 状态）。
            self._critical_alert(
                research_run_id,
                f"business_run 终态同步失败（{biz_status}）: {e}")
            raise CognitionIntegrityError(
                f"business_sync_failed:{type(e).__name__}:{str(e)[:160]}")

    # ---------- 节点实现 ----------

    def _node_classify(self, run: dict, state: dict,
                       consumed: dict) -> dict:
        state["iteration"] = 0
        state["subquestions"] = [{"sq_id": "sq-1",
                                  "text": run["question"]}]
        # R2-06：deep_research 必须经 typed planner；provider 不可用时
        # degraded/abstain，不得用单问题冒充规划。
        if run["mode"] == "deep_research" and not self.planner.available():
            state["planner_degraded"] = True
            state["abstain"] = True
            state["stop_reason_override"] = "degraded:planner_unavailable"
            state["next"] = "finalize"
            return {"answerability": "degraded_planner_unavailable",
                    "mode": run["mode"]}
        state["next"] = "plan"
        return {"answerability": "needs_research",
                "mode": run["mode"]}

    def _node_plan(self, run: dict, state: dict, consumed: dict) -> dict:
        from .planner import atomic_plan, validate_plan
        budget = run["budget"]
        if run["mode"] == "deep_research":
            plan = self.planner.plan(question=run["question"],
                                     mode=run["mode"], budget=budget)
            errors = validate_plan(plan, budget)
            if errors:
                raise CognitionValidationError(
                    f"研究计划非法: {'; '.join(errors[:4])}")
            state["plan"] = plan
            primary = [s for s in plan["subquestions"]
                       if s.get("kind") != "counterevidence"]
            if not primary:
                raise CognitionValidationError("计划缺少主问题子问题")
            state["subquestions"] = primary
            state["target_kinds"] = list(_MODE_KINDS[run["mode"]])
        else:
            state["target_kinds"] = list(_MODE_KINDS[run["mode"]])
            state["plan"] = atomic_plan(
                run["question"], target_kinds=state["target_kinds"])
        state["next"] = "retrieve"
        return {"subquestions": [s["sq_id"]
                                 for s in state["subquestions"]],
                "planner": state["plan"].get("planner",
                                             "provider")}

    def _retrieve_queries(self, run: dict, state: dict, iteration: int,
                          action: str) -> list[tuple[str, str, str]]:
        """生成本轮 (sq_id, qtext, strategy)。gap/counterevidence 是
        独立 typed 动作（R2-06）；反证查询保持中性，不预设结论。"""
        from .reader import counterevidence_query, gap_rewrite
        if action == "counterevidence":
            conflicts = state.get("conflicts") or []
            out = []
            for c in conflicts:
                out.append(("conflict",
                            counterevidence_query(c.get("proposition", "")),
                            "counterevidence"))
            if not out:  # 无结构化冲突命题时的中性兜底
                out.append(("conflict",
                            counterevidence_query(run["question"]),
                            "counterevidence"))
            return out
        if action == "gap_query":
            gaps = set(state.get("gaps") or [])
            out = []
            for sq in state["subquestions"]:
                if sq["sq_id"] in gaps or not gaps:
                    out.append((sq["sq_id"], gap_rewrite(sq["text"]),
                                "gap"))
            return out
        # primary：首轮主问题（不含计划内反证子问题）
        return [(sq["sq_id"], sq["text"], "hybrid")
                for sq in state["subquestions"]
                if sq.get("kind") != "counterevidence"]

    def _node_retrieve(self, run: dict, state: dict,
                       consumed: dict) -> dict:
        # iteration 只在成功发出查询后才写回 state（评审 #G7-8：
        # 异常时不双计数、不吃掉 gap 回跳配额）。
        iteration = state.get("iteration", 0) + 1
        action = state.pop("pending_action", None) or (
            "primary" if iteration == 1 else "gap_query")
        ctx = self._ctx_of(run)
        hits_by_sq: dict[str, list[dict]] = dict(state.get("hits", {}))
        n_queries = 0
        for sq_id, qtext, strategy in self._retrieve_queries(
                run, state, iteration, action):
            sq = next((s for s in state["subquestions"]
                       if s["sq_id"] == sq_id), None)
            kinds = tuple((sq or {}).get("target_kinds")
                          or state.get("target_kinds")
                          or list(_MODE_KINDS[run["mode"]]))
            req = CognitiveQueryRequest(
                query=qtext, target_kinds=kinds,
                mode="lookup", top_k=8)
            result = self.gateway.search(req, ctx)
            hits = [{"target_kind": c.target_kind,
                     "target_id": c.target_id,
                     "version": c.version, "summary": c.summary,
                     "spans": [s.to_dict() for s in c.spans]}
                    for c in result.candidates]
            hits_by_sq[sq_id] = hits
            n_queries += 1
            # 幂等 query/usage id（run+sq+action+iteration 派生，
            # R2-06 novelty key）：崩溃后 resume 重跑不重复落账。
            qkey = (f"{run['research_run_id']}:{sq_id}:{action}:"
                    f"{iteration}")
            query_id = "q-" + hashlib.sha256(
                qkey.encode("utf-8")).hexdigest()[:14]
            usage_id = "usage-" + hashlib.sha256(
                ("u:" + qkey).encode("utf-8")).hexdigest()[:14]
            cur = self.store._conn.execute(
                "INSERT OR IGNORE INTO research_query_v1 (query_id,"
                " research_run_id, subquestion_id, query_text,"
                " target_kinds_json, strategy, iteration, hits_json,"
                " created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (query_id, run["research_run_id"], sq_id, qtext,
                 json.dumps(list(kinds)), strategy, iteration,
                 json.dumps(hits, ensure_ascii=False), _now()))
            inserted = cur.rowcount > 0
            if self.store._conn.execute(
                    "SELECT 1 FROM usage_event_v2 WHERE usage_id=?",
                    (usage_id,)).fetchone() is None:
                self.store.insert_usage_event_v2(
                    usage_id=usage_id, unit="research_query",
                    quantity=1, run_id=run["business_run_id"],
                    node=f"research.retrieve.{action}.{iteration}",
                    capability="cognition.research.query",
                    customer_id=run["customer_id"],
                    project_id=run["project_id"],
                    data_scope=run["data_scope"],
                    test_run_id=run["test_run_id"])
            self.store._conn.commit()
            if inserted:
                # 逐查询持久化 consumed：中途崩溃后 resume 已计入消耗，
                # 不会超出 max_queries（评审 #G7-4）。
                consumed["queries"] = consumed.get("queries", 0) + 1
                state["hits"] = hits_by_sq
                self._persist_state(run["research_run_id"], state,
                                    consumed)
        state["iteration"] = iteration
        state["hits"] = hits_by_sq
        state["retrieve_action"] = action
        state["next"] = "read"
        return {"queries": n_queries, "iteration": iteration,
                "action": action}

    def _node_read(self, run: dict, state: dict, consumed: dict) -> dict:
        from .reader import extract_evidence
        evidence = extract_evidence(state.get("hits", {}))
        state["evidence"] = evidence
        # R2-06 novelty：跟踪新增高价值 span；连续两轮无新 span 时
        # sufficiency 停止 gap 回跳。
        seen = set(state.get("seen_spans") or [])
        new_spans = 0
        for spans in evidence.values():
            for sp in spans:
                sid = sp.get("span_id")
                if sid and sid not in seen:
                    seen.add(sid)
                    new_spans += 1
        state["seen_spans"] = sorted(seen)
        state["rounds_without_new"] = (
            0 if new_spans > 0
            else state.get("rounds_without_new", 0) + 1)
        state["next"] = "sufficiency"
        return {"evidence_spans": sum(len(v) for v in evidence.values()),
                "new_spans": new_spans}

    def _node_sufficiency(self, run: dict, state: dict,
                          consumed: dict) -> dict:
        """Critic 决策（R2-06）：多来源≠冲突；仅互斥规范化数值等构成
        conflict；gap/conflict 分别触发 typed 下一动作；连续两轮无新
        高价值 span 即停止。"""
        from .critic import sufficiency_assessment
        a = sufficiency_assessment(state, run["budget"])
        state["covered"] = a["covered"]
        state["gaps"] = a["gaps"]
        if a.get("stop_rule"):
            state["stop_rule"] = a["stop_rule"]
        action = a["action"]
        if action == "counterevidence":
            state["conflicts"] = a["conflicts"]
            state["counterevidence_done"] = True
            state["pending_action"] = "counterevidence"
            state["next"] = "retrieve"
            return {"covered": a["covered"], "gaps": a["gaps"],
                    "conflict": True, "action": "counterevidence"}
        if action == "ask_human":
            state["conflicts"] = a["conflicts"]
            state["next"] = "claim"  # 裁决后继续
            return {"covered": a["covered"], "gaps": a["gaps"],
                    "waiting_human": True, "conflict": True,
                    "conflicts": a["conflicts"],
                    "action": "ask_human"}
        if action == "gap_query":
            state["pending_action"] = "gap_query"
            state["next"] = "retrieve"
        else:
            state["next"] = "claim"
        return {"covered": a["covered"], "gaps": a["gaps"],
                "conflict": False, "action": action,
                "stop_rule": a.get("stop_rule")}

    def _node_claim(self, run: dict, state: dict, consumed: dict) -> dict:
        if state.get("planner_degraded"):
            # degraded run 不生成 Claim（abstain，R2-06）
            state["next"] = "finalize"
            return {"claims": 0, "degraded": True}
        evidence = state.get("evidence", {})
        conn = self.store._conn
        n_claims = 0
        resolved = bool(state.get("conflict_resolved"))
        if resolved:
            from .claims import DeterministicClaimSupportVerifier
            _sv = DeterministicClaimSupportVerifier()
        for sq in state["subquestions"]:
            sq_id = sq["sq_id"]
            spans = evidence.get(sq_id, [])
            if resolved and spans:
                # 冲突已人工裁决：以首个 span 为 Claim 基准，排除与基准
                # 互斥的证据（关系仍留待 CitationVerifier 核验，不在此
                # 预填 supports）。
                base_quote = spans[0].get("quote", "")
                draft = f"{sq['text']}：{base_quote[:120]}"
                keep = [sp for sp in spans
                        if _sv.verify(draft,
                                      sp.get("quote", "")).relation
                        != "contradicts"]
                spans = keep or spans[:1]
            claim_id = _new_id("clm")
            if spans:
                claim_type, support, conf = "fact", "supported", min(
                    1.0, 0.5 + 0.1 * len(spans))
                text = f"{sq['text']}：{spans[0].get('quote', '')[:120]}"
            else:
                claim_type, support, conf = "unknown", "unsupported", 0.0
                text = f"{sq['text']}：未找到证据（unknown）"
            conn.execute(
                "INSERT INTO research_claim_v1 (claim_id,"
                " research_run_id, subquestion_id, text, claim_type,"
                " importance, support_status, confidence, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (claim_id, run["research_run_id"], sq_id, text,
                 claim_type, "high" if spans else "medium", support,
                 conf, _now()))
            for sp in spans:
                # R2-07：初始关系必须 unverified；supports/分数只能由
                # ClaimSupportVerifier 验证后写入（不得预填 1.0）。
                conn.execute(
                    "INSERT OR IGNORE INTO claim_evidence_v1 (claim_id,"
                    " span_id, relation, verifier_score, verifier_version,"
                    " created_at) VALUES (?,?,?,?,?,?)",
                    (claim_id, sp["span_id"], "unverified", 0.0,
                     "", _now()))
            n_claims += 1
        conn.commit()
        state["next"] = "finalize"
        return {"claims": n_claims}

    def _node_finalize(self, run: dict, state: dict,
                       consumed: dict) -> dict:
        """终态节点（R2-04）：先过引证门，再在同一 UoW 收敛
        report/evidence/research/business/work/event。任一步失败整体
        回滚，不得写 succeeded。"""
        gaps = state.get("gaps", [])
        stop_reason = state.get("stop_reason_override") or (
            "completed_with_gaps" if gaps else "complete")
        # 1) Claim Gate（高重要性 unsupported/contradicted → 拒绝终态）
        vctx = self._ctx_of(run)
        verification = self.verifier.verify_run(run["research_run_id"],
                                                ctx=vctx)
        if not verification["gate_ok"]:
            raise CognitionPolicyError(
                "citation_gate_failed: blocking="
                f"{verification['blocking_claims']}")
        # 2) 终态 UoW（原子）
        out = self._finalize_uow(run, state, stop_reason, verification)
        state["next"] = "done"
        return out

    # ---------- 终态 UoW（R2-04） ----------

    def _finalize_uow(self, run: dict, state: dict, stop_reason: str,
                      verification: dict) -> dict:
        """同一显式事务写 report/evidence/research/business/work/
        event+outbox；任一失败 ROLLBACK 并抛分类错误（不得吞错）。"""
        conn = self.store._conn
        evidence_id = _new_id("evid")
        report_id = _new_id("rep")
        event_id = _new_id("evt")
        conn.execute("BEGIN")
        try:
            self._uow_report(conn, run, report_id, verification)
            self._uow_evidence(conn, run, evidence_id, report_id)
            rc = conn.execute(
                "UPDATE research_run_v1 SET status='succeeded',"
                " stop_reason=?, version=version+1, updated_at=?"
                " WHERE research_run_id=? AND status='running'",
                (stop_reason, _now(),
                 run["research_run_id"])).rowcount
            if rc != 1:
                raise CognitionConflictError(
                    "superseded_by_concurrent_transition")
            self._uow_business(conn, run)
            self._uow_work(conn, run)
            self._uow_event(conn, run, event_id, report_id, evidence_id)
            conn.execute("COMMIT")
        except CognitionConflictError:
            conn.execute("ROLLBACK")
            # cancel 等竞争终态获胜：保持现状，不产生假成功
            return {"stop_reason": "superseded_by_concurrent_transition",
                    "evidence_id": evidence_id}
        except Exception as e:  # noqa: BLE001
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise CognitionIntegrityError(
                f"terminal_uow_failed:{type(e).__name__}:{str(e)[:200]}")
        return {"stop_reason": stop_reason, "evidence_id": evidence_id,
                "report_id": report_id}

    def _uow_report(self, conn, run: dict, report_id: str,
                    verification: dict) -> None:
        """终态报告（构建期快照：corpus 取 run 固化值）。"""
        rep = self.synthesizer.build_report(
            run["research_run_id"], ctx=self._ctx_of(run),
            report_id=report_id,
            corpus_snapshot_id=run.get("corpus_snapshot_id", "") or "")
        self.synthesizer.insert_report(conn, rep)

    def _uow_evidence(self, conn, run: dict, evidence_id: str,
                      report_id: str) -> None:
        conn.execute(
            "INSERT INTO evidence_bundle_v1 (evidence_id, run_id,"
            " work_id, kind, source_uri, cas_hash, content_type,"
            " producer, data_scope, test_run_id, created_at) VALUES"
            " (?,?,?,?,?, '', 'application/json', 'research_service',"
            " ?,?,?)",
            (evidence_id, run["business_run_id"], "", "research_run",
             f"research_run:{run['research_run_id']}:{report_id}",
             run["data_scope"], run["test_run_id"], _now()))

    def _uow_business(self, conn, run: dict) -> None:
        rc = conn.execute(
            "UPDATE business_run_v1 SET status='succeeded',"
            " version=version+1, updated_at=?, ended_at=? WHERE run_id=?"
            " AND status IN ('queued','running','waiting_human')",
            (_now(), _now(), run["business_run_id"])).rowcount
        if rc != 1:
            raise RuntimeError(
                f"business_run {run['business_run_id']} 终态转换失败")

    def _uow_work(self, conn, run: dict) -> None:
        row = conn.execute(
            "SELECT work_id FROM business_run_v1 WHERE run_id=?",
            (run["business_run_id"],)).fetchone()
        if row is None or not row["work_id"]:
            raise RuntimeError("business_run 缺 work_id")
        rc = conn.execute(
            "UPDATE work_item_v2 SET status='completed', updated_at=?"
            " WHERE work_id=? AND status IN ('running','pending')",
            (_now(), row["work_id"])).rowcount
        if rc != 1:
            raise RuntimeError(f"work_item {row['work_id']} 终态转换失败")

    def _uow_event(self, conn, run: dict, event_id: str,
                   report_id: str, evidence_id: str) -> None:
        conn.execute(
            "INSERT INTO event_envelope_v1 (event_id, event_type,"
            " occurred_at, actor_type, actor_id, correlation_id,"
            " run_id, work_id, payload_json) VALUES"
            " (?, 'research.completed', ?, 'system', 'research_service',"
            " ?, ?, ?, ?)",
            (event_id, _now(), "", run["business_run_id"], "",
             json.dumps({"research_run_id": run["research_run_id"],
                         "report_id": report_id,
                         "evidence_id": evidence_id},
                        ensure_ascii=False)))
        conn.execute(
            "INSERT INTO outbox_v1 (event_id, status, attempts,"
            " created_at) VALUES (?, 'pending', 0, ?)",
            (event_id, _now()))

    def _critical_alert(self, run_id: str, content: str) -> None:
        """无法写失败状态时的 critical 治理告警（best-effort；之后必须
        抛出，不得吞错）。"""
        try:
            self.store._conn.execute(
                "INSERT INTO governance_alert_v1 (alert_id, severity,"
                " rule_id, source_agent, affected_run_ids_json,"
                " evidence_refs_json, content, recommended_action,"
                " pause_requested, status, created_by, created_at)"
                " VALUES (?, 'critical', 'research.terminal_uow',"
                " 'silent_agent', ?, '[]', ?, 'human_review_required',"
                " 1, 'open', 'research_service', ?)",
                (_new_id("alert"), json.dumps([run_id]), content[:500],
                 _now()))
            self.store._conn.commit()
        except Exception:
            pass
