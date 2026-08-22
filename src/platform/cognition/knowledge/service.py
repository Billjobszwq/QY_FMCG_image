"""Knowledge 生命周期服务（Task 7 / G5；评审修复后版本）。

发布门（02 §3 + 评审 #4/#12/#16/#17）：published 条目必须有 owner、
effective_from、≥1 **真实存在** 的 source span、以及 governance
approval 账本中已批准的 approval（kind/subject 匹配、批准人==approver、
maker≠checker）。检索面默认只返回“当前生效且已发布”的版本。
冲突策略：同主题（type+title）多个生效版本 → conflict report，
不自动“最新者胜”。所有持久化经 CognitionRepository/UoW。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ...governance.policy_service import PolicyService
from ..context import CognitiveContext
from ..errors import (
    CognitionConflictError,
    CognitionValidationError,
)
from ..repository import CognitionRepository, UnitOfWork

KNOWLEDGE_TYPES = ("organization", "policy", "process", "contract",
                   "finance", "technical", "conduct", "law")

APPROVAL_KIND_PUBLISH = "cognition.knowledge.publish"
APPROVAL_KIND_REVOKE = "cognition.knowledge.revoke"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_ctx(ctx: CognitiveContext | None) -> None:
    if ctx is None:
        raise CognitionValidationError("缺 CognitiveContext（fail-closed）")


def _parse_ts(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


class KnowledgeService:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.repo = CognitionRepository(store)
        self.policy = PolicyService(store)

    # ---------- draft ----------

    def draft(self, ctx: CognitiveContext, *, knowledge_id: str,
              knowledge_type: str, title: str, body: str, summary: str,
              owner: str, effective_from: str,
              effective_to: str | None,
              permission_tags: tuple[str, ...] | list[str],
              source_span_ids: list[str],
              related_knowledge: list[str] | None = None,
              extracted_entities: dict | None = None) -> dict[str, Any]:
        _require_ctx(ctx)
        if knowledge_type not in KNOWLEDGE_TYPES:
            raise CognitionValidationError(
                f"非法 knowledge_type: {knowledge_type}")
        if not knowledge_id or not title:
            raise CognitionValidationError("knowledge_id/title 必填")
        tags = list(permission_tags or [])
        if not tags:
            raise CognitionValidationError(
                "permission_tags 必填（fail-closed）")
        version = self.repo.max_knowledge_version(knowledge_id) + 1
        with UnitOfWork(self.store) as tx:
            self.repo.insert_knowledge_version(
                tx, knowledge_id=knowledge_id, version=version,
                type_=knowledge_type, title=title, body=body,
                summary=summary, owner=owner,
                effective_from=effective_from,
                effective_to=effective_to,
                permission_tags=tuple(tags),
                source_span_ids=list(source_span_ids or []),
                related_knowledge=list(related_knowledge or []),
                extracted_entities=dict(extracted_entities or {}),
                created_by=ctx.principal_id, created_at=_now(),
                tenant_id=ctx.tenant_id, customer_id=ctx.customer_id,
                project_id=ctx.project_id, data_scope=ctx.data_scope,
                test_run_id=ctx.test_run_id)
        return self.get(knowledge_id, version)

    def get(self, knowledge_id: str, version: int) -> dict[str, Any]:
        row = self.repo.get_knowledge_version(knowledge_id, version)
        if row is None:
            raise CognitionValidationError(
                f"knowledge 不存在: {knowledge_id}@v{version}")
        return self._dict(row)

    @staticmethod
    def _dict(row: Any) -> dict[str, Any]:
        d = dict(row)
        d["permission_tags"] = json.loads(
            d["permission_tags_json"] or "[]")
        d["source_span_ids"] = json.loads(
            d["source_span_ids_json"] or "[]")
        return d

    # ---------- 发布门 ----------

    def publish(self, ctx: CognitiveContext, knowledge_id: str,
                version: int, *, approver: str, approval_id: str,
                ) -> dict[str, Any]:
        _require_ctx(ctx)
        item = self.get(knowledge_id, version)
        if not item["owner"]:
            raise CognitionValidationError("发布必须有 owner")
        if not item["effective_from"]:
            raise CognitionValidationError("发布必须有 effective_from")
        spans = list(dict.fromkeys(item["source_span_ids"]))
        if not spans:
            raise CognitionValidationError(
                "发布必须有 ≥1 source span（可回查证据）")
        # span 必须真实存在（防伪 span id，评审 #16）
        if self.repo.count_existing_spans(spans) != len(spans):
            raise CognitionValidationError(
                "source_span_ids 含不存在的 span（发布门拒绝）")
        if not approver:
            raise CognitionValidationError("发布必须人类 approver")
        # 人类批准账本校验（maker≠checker，评审 #4/#12）
        self.policy.verify_approved(
            approval_id, kind=APPROVAL_KIND_PUBLISH,
            subject_ref=f"{knowledge_id}@v{version}", approver=approver,
            created_by=item["created_by"])
        with UnitOfWork(self.store) as tx:
            rc = self.repo.cas_knowledge(
                tx, knowledge_id, version, to_status="published",
                from_statuses=("draft",),
                extra_sets=", approved_by=?, approval_id=?,"
                           " published_at=?",
                extra_params=(approver, approval_id, _now()))
            tx.execute(
                "UPDATE knowledge_item_version SET status='superseded'"
                " WHERE knowledge_id=? AND status='published' AND"
                " version!=?", (knowledge_id, version))
        if rc == 0:
            raise CognitionConflictError(
                f"knowledge {knowledge_id}@v{version} 不在 draft 状态"
                "（CAS 拒绝）")
        return self.get(knowledge_id, version)

    def revoke(self, ctx: CognitiveContext, knowledge_id: str,
               version: int, *, actor: str, approval_id: str
               ) -> dict[str, Any]:
        """废止同样必须人类批准（02 §8.4，评审 #17）。"""
        _require_ctx(ctx)
        item = self.get(knowledge_id, version)
        self.policy.verify_approved(
            approval_id, kind=APPROVAL_KIND_REVOKE,
            subject_ref=f"{knowledge_id}@v{version}", approver=actor,
            created_by=item["created_by"])
        with UnitOfWork(self.store) as tx:
            rc = self.repo.cas_knowledge(
                tx, knowledge_id, version, to_status="revoked",
                from_statuses=("draft", "published", "superseded"))
        if rc == 0:
            raise CognitionConflictError(
                f"knowledge {knowledge_id}@v{version} 不可撤销"
                "（状态不允许）")
        return self.get(knowledge_id, version)

    # ---------- 检索面 ----------

    def effective(self, ctx: CognitiveContext, *,
                  knowledge_type: str | None = None,
                  include_history: bool = False) -> list[dict[str, Any]]:
        """默认只返回 published 且 as_of 生效中的条目；revoked/
        superseded/draft 永不返回；include_history 放开有效期限制。"""
        _require_ctx(ctx)
        as_of = ctx.as_of
        rows = self.repo.list_knowledge_by_status(
            "published", type_=knowledge_type)
        out = []
        for r in rows:
            d = self._dict(r)
            if include_history:
                out.append(d)
                continue
            frm = _parse_ts(d["effective_from"])
            to = _parse_ts(d["effective_to"])
            if frm is not None and as_of < frm:
                continue
            if to is not None and as_of >= to:
                continue
            out.append(d)
        return out

    def detect_conflicts(self, ctx: CognitiveContext, *,
                         knowledge_type: str
                         ) -> list[dict[str, Any]]:
        """同主题（type+title）≥2 个不同 knowledge_id 同时生效 →
        conflict report；不自动选边，交 Rules Agent 裁决。"""
        _require_ctx(ctx)
        eff = self.effective(ctx, knowledge_type=knowledge_type)
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in eff:
            groups.setdefault(item["title"], []).append(item)
        conflicts: list[dict[str, Any]] = []
        for title, items in sorted(groups.items()):
            ids = sorted({i["knowledge_id"] for i in items})
            if len(ids) >= 2:
                for i in items:
                    conflicts.append({
                        "knowledge_id": i["knowledge_id"],
                        "version": i["version"],
                        "title": title,
                        "conflict_group": title,
                        "reason": "同主题存在多个生效来源，需 Rules "
                                  "裁决（不自动最新者胜）",
                    })
        return conflicts

    # ---------- 旧表只读兼容投影 ----------

    def legacy_projection(self, ctx: CognitiveContext
                          ) -> list[dict[str, Any]]:
        """knowledge_document_v1 只读投影（迁移期兼容；不再新增旧写
        入口，新内容一律走 knowledge_item_version）。"""
        _require_ctx(ctx)
        rows = self.repo.list_legacy_knowledge_documents()
        out = []
        for r in rows:
            d = dict(r)
            d["_origin"] = "knowledge_document_v1"
            d["_writable"] = False
            out.append(d)
        return out
