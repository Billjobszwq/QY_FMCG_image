"""Cognition API（Task 11 / 02 §9；R2-03 授权收口）。

端点（均鉴权；写端点 CSRF）：
- POST /api/v1/cognition/sources/ingest   摄取 source（返回 draft/隔离态）
- POST /api/v1/cognition/sources/publish-document  发布 document 版本
- GET  /api/v1/cognition/knowledge/search  知识检索（ACL 前置过滤）
- GET  /api/v1/cognition/memory/search     记忆检索（L2/L3，ACL）
- GET  /api/v1/cognition/skills/search     Skill 发现（命中≠可执行）
- GET  /api/v1/cognition/skills/{id}/can-execute  执行面独立判定
- POST /api/v1/cognition/index/build       构建索引
- POST /api/v1/cognition/index/activate    激活索引（hash CAS）

授权（R2-03）：session principal → IAM action permission
（cognition.read/cognition.manage）→ ScopeResolver → CognitiveContext。
禁止 API 内手写上下文；客户端 customer/project 只是请求值，必须经
IAM membership 验证（build_context fail-closed）。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..auth import AuthService, require_principal
from ..cognition.composition import CognitionStack
from ..cognition.contracts import CognitiveQueryRequest
from ..cognition.errors import (
    CognitionConflictError,
    CognitionIntegrityError,
    CognitionPermissionDeniedError,
    CognitionPolicyError,
    CognitionProviderError,
    CognitionValidationError,
)
from ..iam import IAMService
from .cognition_auth import build_context

P_READ = "cognition.read"
P_MANAGE = "cognition.manage"


class IngestBody(BaseModel):
    source_type: str = "file"
    original_uri: str
    media_type: str = "text/markdown"
    content_b64: str = ""
    content_text: str = ""
    permission_tags: list[str] = ["public"]
    trust_tier: str = "internal"


class PublishDocumentBody(BaseModel):
    document_id: str
    version: int
    owner: str
    approval_id: str


class SearchQuery(BaseModel):
    query: str
    target_kinds: list[str] = ["knowledge"]
    mode: str = "lookup"
    top_k: int = 8


class IndexBuildBody(BaseModel):
    target_kind: str = "knowledge"
    corpus_snapshot_id: str


class IndexActivateBody(BaseModel):
    target_kind: str = "knowledge"
    index_snapshot_id: str
    expected_hash: str | None = None


class KnowledgeDraftBody(BaseModel):
    knowledge_id: str
    knowledge_type: str = "policy"
    title: str
    body: str
    summary: str = ""
    owner: str
    effective_from: str
    effective_to: str | None = None
    permission_tags: list[str] = ["public"]
    source_span_ids: list[str] = []


class KnowledgePublishBody(BaseModel):
    knowledge_id: str
    version: int
    approval_id: str


def _search_result_dto(r) -> dict:
    return {"query": r.query,
            "degraded": r.degraded,
            "index_snapshot_ids": list(r.index_snapshot_ids),
            "policy_decision": r.policy_decision,
            "candidates": [
                {"target_kind": c.target_kind, "target_id": c.target_id,
                 "version": c.version, "summary": c.summary,
                 "score_breakdown": c.score_breakdown,
                 "spans": [s.to_dict() for s in c.spans]}
                for c in r.candidates]}


def create_cognition_router(stack: CognitionStack,
                            auth: AuthService | None,
                            iam: IAMService | None = None) -> APIRouter:
    router = APIRouter(tags=["cognition"])
    if iam is None:
        iam = IAMService(stack.store)

    def _ctx(p: dict, permission: str, action: str,
             customer_id: str = "", project_id: str = ""):
        try:
            return build_context(store=stack.store, iam=iam, principal=p,
                                 permission=permission, action=action,
                                 customer_id=customer_id,
                                 project_id=project_id)
        except CognitionPermissionDeniedError as e:
            raise HTTPException(403, str(e))

    @router.post("/api/v1/cognition/sources/ingest")
    def ingest(body: IngestBody, request: Request,
               customer_id: str = "", project_id: str = "") -> dict:
        p = require_principal(auth, request, csrf=True)
        import base64
        if body.content_b64:
            content = base64.b64decode(body.content_b64)
        else:
            content = body.content_text.encode("utf-8")
        try:
            res = stack.sources.ingest(
                _ctx(p, P_MANAGE, "cognition.sources.ingest",
                     customer_id, project_id),
                source_type=body.source_type,
                original_uri=body.original_uri,
                media_type=body.media_type, content=content,
                permission_tags=tuple(body.permission_tags),
                trust_tier=body.trust_tier)
        except (CognitionValidationError, CognitionProviderError) as e:
            raise HTTPException(422, str(e))
        return {"source": res["source"],
                "document": res["document"],
                "chunk_count": len(res["chunks"]),
                "quarantine_reason": res["quarantine_reason"]}

    @router.post("/api/v1/cognition/sources/publish-document")
    def publish_document(body: PublishDocumentBody, request: Request,
                         customer_id: str = "",
                         project_id: str = "") -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            doc = stack.sources.publish(
                body.document_id, body.version,
                ctx=_ctx(p, P_MANAGE, "cognition.document.publish",
                         customer_id, project_id),
                approver=p["actor"], owner=body.owner,
                approval_id=body.approval_id)
        except CognitionValidationError as e:
            raise HTTPException(422, str(e))
        except CognitionPolicyError as e:
            raise HTTPException(403, str(e))
        except CognitionConflictError as e:
            raise HTTPException(409, str(e))
        return {"document_id": doc["document_id"],
                "version": doc["version"], "status": doc["status"]}

    @router.post("/api/v1/cognition/knowledge/draft")
    def knowledge_draft(body: KnowledgeDraftBody, request: Request,
                        customer_id: str = "",
                        project_id: str = "") -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            item = stack.knowledge.draft(
                _ctx(p, P_MANAGE, "cognition.knowledge.draft",
                     customer_id, project_id),
                knowledge_id=body.knowledge_id,
                knowledge_type=body.knowledge_type, title=body.title,
                body=body.body, summary=body.summary or body.title,
                owner=body.owner, effective_from=body.effective_from,
                effective_to=body.effective_to,
                permission_tags=tuple(body.permission_tags),
                source_span_ids=list(body.source_span_ids))
        except CognitionValidationError as e:
            raise HTTPException(422, str(e))
        return {"knowledge_id": item["knowledge_id"],
                "version": item["version"], "status": item["status"]}

    @router.post("/api/v1/cognition/knowledge/publish")
    def knowledge_publish(body: KnowledgePublishBody, request: Request,
                          customer_id: str = "",
                          project_id: str = "") -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            item = stack.knowledge.publish(
                _ctx(p, P_MANAGE, "cognition.knowledge.publish",
                     customer_id, project_id),
                body.knowledge_id, body.version, approver=p["actor"],
                approval_id=body.approval_id)
        except CognitionValidationError as e:
            raise HTTPException(422, str(e))
        except CognitionPolicyError as e:
            raise HTTPException(403, str(e))
        except CognitionConflictError as e:
            raise HTTPException(409, str(e))
        return {"knowledge_id": item["knowledge_id"],
                "version": item["version"], "status": item["status"]}

    @router.get("/api/v1/cognition/knowledge/search")
    def knowledge_search(request: Request, q: str,
                         customer_id: str = "", project_id: str = "",
                         top_k: int = 8) -> dict:
        p = require_principal(auth, request, csrf=False)
        req = CognitiveQueryRequest(query=q, target_kinds=("knowledge",),
                                    mode="lookup", top_k=top_k)
        try:
            r = stack.gateway.search(req, _ctx(
                p, P_READ, "cognition.knowledge.search", customer_id,
                project_id))
        except CognitionValidationError as e:
            raise HTTPException(422, str(e))
        return _search_result_dto(r)

    @router.get("/api/v1/cognition/memory/search")
    def memory_search(request: Request, q: str, layer: str = "memory_l2",
                      customer_id: str = "", project_id: str = "",
                      top_k: int = 8) -> dict:
        p = require_principal(auth, request, csrf=False)
        if layer not in ("memory_l2", "memory_l3"):
            raise HTTPException(422, "layer 必须为 memory_l2/memory_l3")
        req = CognitiveQueryRequest(query=q, target_kinds=(layer,),
                                    mode="case_analysis", top_k=top_k)
        try:
            r = stack.gateway.search(req, _ctx(
                p, P_READ, "cognition.memory.search", customer_id,
                project_id))
        except CognitionValidationError as e:
            raise HTTPException(422, str(e))
        return _search_result_dto(r)

    @router.get("/api/v1/cognition/skills/search")
    def skills_search(request: Request, q: str, customer_id: str = "",
                      project_id: str = "", top_k: int = 8) -> dict:
        p = require_principal(auth, request, csrf=False)
        req = CognitiveQueryRequest(query=q, target_kinds=("skill",),
                                    mode="lookup", top_k=top_k)
        try:
            r = stack.gateway.search(req, _ctx(
                p, P_READ, "cognition.skills.search", customer_id,
                project_id))
        except CognitionValidationError as e:
            raise HTTPException(422, str(e))
        return _search_result_dto(r)

    @router.get("/api/v1/cognition/skills/{skill_id}/can-execute")
    def can_execute(skill_id: str, request: Request,
                    customer_id: str = "", project_id: str = "") -> dict:
        p = require_principal(auth, request, csrf=False)
        return stack.skills.can_execute(_ctx(
            p, P_READ, "cognition.skills.can_execute", customer_id,
            project_id), skill_id)

    @router.post("/api/v1/cognition/index/build")
    def build_index(body: IndexBuildBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            b = stack.catalog.build(
                _ctx(p, P_MANAGE, "cognition.index.build"),
                target_kind=body.target_kind,
                corpus_snapshot_id=body.corpus_snapshot_id)
        except CognitionValidationError as e:
            raise HTTPException(422, str(e))
        return {"index_snapshot_id": b["index_snapshot_id"],
                "build_status": b["build_status"],
                "item_count": b["item_count"],
                "source_manifest_hash": b["source_manifest_hash"]}

    @router.post("/api/v1/cognition/index/activate")
    def activate_index(body: IndexActivateBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            b = stack.catalog.activate(
                _ctx(p, P_MANAGE, "cognition.index.activate"),
                target_kind=body.target_kind,
                index_snapshot_id=body.index_snapshot_id,
                expected_hash=body.expected_hash)
        except CognitionIntegrityError as e:
            raise HTTPException(409, str(e))
        except CognitionValidationError as e:
            raise HTTPException(422, str(e))
        return {"activated": b["index_snapshot_id"]}

    return router
