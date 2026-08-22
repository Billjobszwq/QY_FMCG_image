"""Governance API（Task 11 / 02 §9）。

端点（均鉴权；写端点 CSRF）：
- POST /api/v1/governance/approvals/request   申请批准（policy/知识/skill/L2/L3）
- POST /api/v1/governance/approvals/{id}/decide  人类决策（maker≠checker）
- GET  /api/v1/governance/approvals/{id}      查询批准状态
- POST /api/v1/governance/policies/draft      Rules Agent 起草规则（仅 draft）
- GET  /api/v1/governance/alerts              告警列表
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..auth import AuthService, require_principal
from ..governance import GovernanceError, GovernanceRoleError
from ..governance.alert_service import AlertService
from ..governance.policy_service import PolicyService


class ApprovalRequestBody(BaseModel):
    kind: str
    subject_ref: str
    requested_by: str | None = None  # 缺省=当前登录者；系统代发时显式指定


class ApprovalDecideBody(BaseModel):
    decision: str  # approved | rejected
    reason: str = ""


class PolicyDraftBody(BaseModel):
    rule_id: str
    allow: list[str] = []
    deny: list[str] = []
    risk_level: str = "medium"
    summary: str = ""


def create_governance_router(store, auth: AuthService | None
                             ) -> APIRouter:
    router = APIRouter(tags=["governance"])
    policy = PolicyService(store)

    @router.post("/api/v1/governance/approvals/request")
    def request_approval(body: ApprovalRequestBody,
                         request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            ap = policy.request_generic_approval(
                kind=body.kind, subject_ref=body.subject_ref,
                requested_by=body.requested_by or p["actor"])
        except GovernanceError as e:
            raise HTTPException(422, str(e))
        return {"approval_id": ap["approval_id"],
                "kind": ap["kind"], "subject_ref": ap["subject_ref"],
                "decision": ap["decision"],
                "requested_by": ap["requested_by"]}

    @router.post("/api/v1/governance/approvals/{approval_id}/decide")
    def decide(approval_id: str, body: ApprovalDecideBody,
               request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            ap = policy.decide_approval(approval_id, actor=p["actor"],
                                        decision=body.decision,
                                        reason=body.reason)
        except GovernanceRoleError as e:
            raise HTTPException(403, str(e))
        except GovernanceError as e:
            raise HTTPException(409, str(e))
        return {"approval_id": ap["approval_id"],
                "decision": ap["decision"], "decided_by": ap["decided_by"]}

    @router.get("/api/v1/governance/approvals/{approval_id}")
    def get_approval(approval_id: str, request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        try:
            ap = policy.get_approval(approval_id)
        except GovernanceError as e:
            raise HTTPException(404, str(e))
        return ap

    @router.post("/api/v1/governance/policies/draft")
    def draft_policy(body: PolicyDraftBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            rule = policy.draft_rule(actor=p["actor"],
                                     rule_id=body.rule_id,
                                     allow=body.allow, deny=body.deny,
                                     risk_level=body.risk_level,
                                     summary=body.summary)
        except GovernanceError as e:
            raise HTTPException(422, str(e))
        return {"rule_id": rule["rule_id"], "version": rule["version"],
                "status": rule["status"]}

    @router.get("/api/v1/governance/alerts")
    def alerts(request: Request) -> dict:
        require_principal(auth, request, csrf=False)
        rows = AlertService(store).list_alerts()
        return {"count": len(rows), "alerts": rows}

    return router
