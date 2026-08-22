"""Research API（Task 11 / 02 §9；R2-03 授权收口）。

端点（均鉴权；写端点 CSRF）：
- POST /api/v1/research/runs           启动研究（lookup/case/...）
- GET  /api/v1/research/runs/{id}      状态/预算/停止原因
- POST /api/v1/research/runs/{id}/resume   断点恢复
- POST /api/v1/research/runs/{id}/cancel   取消
- POST /api/v1/research/runs/{id}/decide-conflict  人类裁决冲突
- GET  /api/v1/research/runs/{id}/claims     Claim 列表
- GET  /api/v1/research/runs/{id}/citations  引证核验
- POST /api/v1/research/runs/{id}/synthesize 综合报告（过引证门）

授权契约（R2-03 / round-2-hardening/01 §4）：
- run ID 不是授权凭证。每个端点执行：session principal → IAM action
  permission（research.read/run/decide）→ ScopeResolver →
  CognitiveContext → run 持久化 scope 对比；
- start 接收 requested customer/project/test_run，但必须经 IAM
  membership 与 ScopeResolver 验证后才持久化；
- citations/synthesize 的有效 scope 来自 run 持久化 scope（context_from_run），
  query 参数只用于访问检查，不得改写核验 scope；
- 无权与不存在统一 404（safe_404），不泄露 question/state/counts。
"""
from __future__ import annotations

import json as _json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..auth import AuthService, require_principal
from ..cognition.composition import CognitionStack
from ..cognition.errors import (
    CognitionConflictError,
    CognitionPermissionDeniedError,
    CognitionPolicyError,
    CognitionValidationError,
)
from ..iam import IAMService
from ..rate_limit import enforce as _rl_enforce
from .cognition_auth import (
    ResearchRunAccessPolicy,
    build_context,
    context_from_run,
    safe_404,
)

P_READ = "research.read"
P_RUN = "research.run"
P_DECIDE = "research.decide"


def _idem_get(store, principal: str, key: str, endpoint: str):
    row = store._conn.execute(
        "SELECT response_json FROM research_idempotency_v1 WHERE"
        " principal_id=? AND idempotency_key=? AND endpoint=?",
        (principal, key, endpoint)).fetchone()
    if row is None:
        return None
    return _json.loads(row["response_json"])


def _idem_put(store, principal: str, key: str, endpoint: str,
              response: dict) -> None:
    store._conn.execute(
        "INSERT OR IGNORE INTO research_idempotency_v1 (principal_id,"
        " idempotency_key, endpoint, response_json, created_at) VALUES"
        " (?,?,?,?,datetime('now'))",
        (principal, key, endpoint,
         _json.dumps(response, ensure_ascii=False, default=str)))
    store._conn.commit()


class ResearchStartBody(BaseModel):
    question: str
    mode: str = "lookup"
    budget: dict | None = None
    customer_id: str = ""
    project_id: str = ""
    test_run_id: str = ""


class DecideConflictBody(BaseModel):
    resolution: str
    customer_id: str = ""
    project_id: str = ""
    test_run_id: str = ""


def create_research_router(stack: CognitionStack,
                           auth: AuthService | None,
                           iam: IAMService | None = None) -> APIRouter:
    router = APIRouter(tags=["research"])
    if iam is None:
        iam = IAMService(stack.store)
    policy = ResearchRunAccessPolicy(iam)

    def _ctx_or_403(p: dict, permission: str, customer_id: str = "",
                    project_id: str = "", test_run_id: str = "",
                    action: str = ""):
        try:
            return build_context(store=stack.store, iam=iam, principal=p,
                                 permission=permission, action=action,
                                 customer_id=customer_id,
                                 project_id=project_id,
                                 test_run_id=test_run_id)
        except CognitionPermissionDeniedError as e:
            iam.audit(p.get("actor", ""), "research.access.denied",
                      permission, {"reason": str(e),
                                   "customer_id": customer_id})
            raise HTTPException(403, str(e))

    def _authorized_run(p: dict, run_id: str, permission: str,
                        customer_id: str = "", project_id: str = "",
                        test_run_id: str = "") -> dict:
        """读取 run 并做 IAM + 持久化 scope 对账；无权与不存在统一
        404，不泄露存在性（IAM 层拒绝同样并入统一响应）。"""
        try:
            ctx = build_context(store=stack.store, iam=iam, principal=p,
                                permission=permission,
                                customer_id=customer_id,
                                project_id=project_id,
                                test_run_id=test_run_id)
        except CognitionPermissionDeniedError as e:
            iam.audit(p.get("actor", ""), "research.access.denied",
                      f"run:{run_id}", {"reason": str(e),
                                        "permission": permission})
            raise HTTPException(404, safe_404())
        try:
            run = stack.research.get_run(run_id)
        except CognitionValidationError:
            raise HTTPException(404, safe_404())
        try:
            policy.require(ctx, run, permission=permission, principal=p)
        except CognitionPermissionDeniedError as e:
            iam.audit(p.get("actor", ""), "research.access.denied",
                      f"run:{run_id}", {"reason": str(e),
                                        "permission": permission})
            raise HTTPException(404, safe_404())
        return run

    @router.post("/api/v1/research/runs")
    def start(body: ResearchStartBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _rl_enforce(request, "research.run.start", p["actor"])
        idem_key = request.headers.get("Idempotency-Key")
        if idem_key:
            cached = _idem_get(stack.store, p["actor"], idem_key,
                               "research.start")
            if cached is not None:
                return cached
        ctx = _ctx_or_403(p, P_RUN, body.customer_id, body.project_id,
                          body.test_run_id, action="research.run.start")
        try:
            run = stack.research.start(
                ctx, question=body.question, mode=body.mode,
                budget=body.budget)
        except CognitionValidationError as e:
            raise HTTPException(422, str(e))
        iam.audit(p["actor"], "research.run.started",
                  f"run:{run['research_run_id']}",
                  {"customer_id": body.customer_id,
                   "project_id": body.project_id, "mode": body.mode})
        dto = _run_dto(run)
        if idem_key:
            _idem_put(stack.store, p["actor"], idem_key, "research.start",
                      dto)
        return dto

    @router.get("/api/v1/research/runs/{run_id}")
    def status(run_id: str, request: Request, customer_id: str = "",
               project_id: str = "", test_run_id: str = "") -> dict:
        p = require_principal(auth, request, csrf=False)
        run = _authorized_run(run_id=run_id, p=p, permission=P_READ,
                              customer_id=customer_id,
                              project_id=project_id,
                              test_run_id=test_run_id)
        return _run_dto(run)

    @router.post("/api/v1/research/runs/{run_id}/resume")
    def resume(run_id: str, request: Request, customer_id: str = "",
               project_id: str = "", test_run_id: str = "") -> dict:
        p = require_principal(auth, request, csrf=True)
        _rl_enforce(request, "research.run.resume", p["actor"])
        run = _authorized_run(run_id=run_id, p=p, permission=P_RUN,
                              customer_id=customer_id,
                              project_id=project_id,
                              test_run_id=test_run_id)
        rctx = context_from_run(run, principal_id=p["actor"],
                                action="research.run.resume")
        try:
            return _run_dto(stack.research.resume(run_id, ctx=rctx))
        except CognitionConflictError as e:
            raise HTTPException(409, str(e))
        except CognitionValidationError:
            raise HTTPException(404, safe_404())

    @router.post("/api/v1/research/runs/{run_id}/cancel")
    def cancel(run_id: str, request: Request, customer_id: str = "",
               project_id: str = "", test_run_id: str = "") -> dict:
        p = require_principal(auth, request, csrf=True)
        _rl_enforce(request, "research.run.cancel", p["actor"])
        run = _authorized_run(run_id=run_id, p=p, permission=P_RUN,
                              customer_id=customer_id,
                              project_id=project_id,
                              test_run_id=test_run_id)
        rctx = context_from_run(run, principal_id=p["actor"],
                                action="research.run.cancel")
        try:
            return _run_dto(stack.research.cancel(run_id, actor=p["actor"],
                                                  ctx=rctx))
        except CognitionConflictError as e:
            raise HTTPException(409, str(e))
        except CognitionValidationError:
            raise HTTPException(404, safe_404())

    @router.post("/api/v1/research/runs/{run_id}/decide-conflict")
    def decide_conflict(run_id: str, body: DecideConflictBody,
                        request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _rl_enforce(request, "research.run.decide", p["actor"])
        run = _authorized_run(run_id=run_id, p=p, permission=P_DECIDE,
                              customer_id=body.customer_id,
                              project_id=body.project_id,
                              test_run_id=body.test_run_id)
        rctx = context_from_run(run, principal_id=p["actor"],
                                action="research.run.decide")
        try:
            return _run_dto(stack.research.decide_conflict(
                run_id, actor=p["actor"], resolution=body.resolution,
                ctx=rctx))
        except CognitionConflictError as e:
            raise HTTPException(409, str(e))
        except CognitionValidationError as e:
            raise HTTPException(422, str(e))

    @router.get("/api/v1/research/runs/{run_id}/claims")
    def claims(run_id: str, request: Request, customer_id: str = "",
               project_id: str = "", test_run_id: str = "") -> dict:
        p = require_principal(auth, request, csrf=False)
        run = _authorized_run(run_id=run_id, p=p, permission=P_READ,
                              customer_id=customer_id,
                              project_id=project_id,
                              test_run_id=test_run_id)
        rctx = context_from_run(run, principal_id=p["actor"],
                                action="research.claims.read")
        rows = stack.research.list_claims(run_id, ctx=rctx)
        return {"count": len(rows), "claims": rows}

    @router.get("/api/v1/research/runs/{run_id}/citations")
    def citations(run_id: str, request: Request, customer_id: str = "",
                  project_id: str = "", test_run_id: str = "") -> dict:
        p = require_principal(auth, request, csrf=False)
        run = _authorized_run(run_id=run_id, p=p, permission=P_READ,
                              customer_id=customer_id,
                              project_id=project_id,
                              test_run_id=test_run_id)
        # 核验 scope 只来自 run 持久化 scope（不接受 query 参数改写）
        vctx = context_from_run(run, principal_id=p["actor"],
                                action="research.citations.verify")
        ver = stack.verifier.verify_run(run_id, ctx=vctx)
        return {"gate_ok": ver["gate_ok"],
                "blocking_claims": ver["blocking_claims"],
                "verdicts": ver["verdicts"]}

    @router.post("/api/v1/research/runs/{run_id}/synthesize")
    def synthesize(run_id: str, request: Request, customer_id: str = "",
                   project_id: str = "", test_run_id: str = "") -> dict:
        p = require_principal(auth, request, csrf=True)
        _rl_enforce(request, "research.synthesize", p["actor"])
        run = _authorized_run(run_id=run_id, p=p, permission=P_RUN,
                              customer_id=customer_id,
                              project_id=project_id,
                              test_run_id=test_run_id)
        sctx = context_from_run(run, principal_id=p["actor"],
                                action="research.synthesize")
        try:
            rep = stack.synthesizer.synthesize(run_id, ctx=sctx)
        except CognitionPolicyError as e:
            raise HTTPException(409, str(e))
        except CognitionValidationError:
            raise HTTPException(404, safe_404())
        return {"report_id": rep["report_id"], "abstain": rep["abstain"],
                "claims": rep["claims"], "citations": rep["citations"],
                "snapshots": rep["snapshots"],
                "body": rep["body"]}

    return router


def _run_dto(run: dict) -> dict:
    return {"research_run_id": run["research_run_id"],
            "business_run_id": run["business_run_id"],
            "question": run["question"], "mode": run["mode"],
            "status": run["status"], "stop_reason": run["stop_reason"],
            "budget": run["budget"], "consumed": run["consumed"],
            "state": run["state"],
            # 服务端固化的 scope（R2-03/UI 展示用）
            "tenant_id": run.get("tenant_id", "local"),
            "customer_id": run.get("customer_id", ""),
            "project_id": run.get("project_id", ""),
            "test_run_id": run.get("test_run_id", ""),
            "data_scope": run.get("data_scope", "operational")}
