"""Skill 生命周期服务（Task 7 / G5；评审修复后版本）。

状态机：draft → validated → published → degraded / revoked（CAS，
发布+旧版本降级同一事务，评审 #10）。
发布门（02 §5 + 评审 #4/#12）：input/output schema、execution_ref、
risk_level、evaluation_ref 缺一不可，且必须有 governance approval 账本
中已批准的 approval（maker≠checker）。
核心边界：**Skill RAG 命中（search）不等于允许执行（can_execute）**。
所有持久化经 CognitionRepository/UoW。
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

SKILL_TYPES = ("builtin", "curated", "derived")
RISK_LEVELS = ("low", "medium", "high", "critical")

APPROVAL_KIND_PUBLISH = "cognition.skill.publish"
APPROVAL_KIND_REVOKE = "cognition.skill.revoke"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_ctx(ctx: CognitiveContext | None) -> None:
    if ctx is None:
        raise CognitionValidationError("缺 CognitiveContext（fail-closed）")


class SkillService:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.repo = CognitionRepository(store)
        self.policy = PolicyService(store)

    # ---------- draft / validate / publish ----------

    def draft(self, ctx: CognitiveContext, *, skill_id: str, name: str,
              description: str, skill_type: str,
              input_schema: dict, output_schema: dict,
              execution_ref: str, tool_scopes: list[str],
              risk_level: str, applicable_scenarios: list[str],
              forbidden_scenarios: list[str], source_refs: list[str],
              evaluation_ref: str,
              permission_tags: tuple[str, ...] | list[str],
              dependency_versions: dict | None = None,
              approval_policy_id: str = "") -> dict[str, Any]:
        _require_ctx(ctx)
        if skill_type not in SKILL_TYPES:
            raise CognitionValidationError(
                f"非法 skill_type: {skill_type}")
        if risk_level and risk_level not in RISK_LEVELS:
            raise CognitionValidationError(
                f"非法 risk_level: {risk_level}")
        if not skill_id or not name:
            raise CognitionValidationError("skill_id/name 必填")
        # permission_tags fail-closed（与 sources/L1/knowledge 一致，
        # 评审 #6）
        tags = list(permission_tags or [])
        if not tags or any(not isinstance(t, str) or not t for t in tags):
            raise CognitionValidationError(
                "permission_tags 必填且为非空字符串序列（fail-closed）")
        version = self.repo.max_skill_version(skill_id) + 1
        with UnitOfWork(self.store) as tx:
            self.repo.insert_skill_version(
                tx, skill_id=skill_id, version=version, name=name,
                description=description, skill_type=skill_type,
                input_schema=dict(input_schema or {}),
                output_schema=dict(output_schema or {}),
                execution_ref=execution_ref,
                tool_scopes=list(tool_scopes or []),
                dependency_versions=dict(dependency_versions or {}),
                applicable_scenarios=list(applicable_scenarios or []),
                forbidden_scenarios=list(forbidden_scenarios or []),
                risk_level=risk_level,
                approval_policy_id=approval_policy_id,
                permission_tags=tuple(tags),
                source_refs=list(source_refs or []),
                evaluation_ref=evaluation_ref,
                created_by=ctx.principal_id, created_at=_now(),
                tenant_id=ctx.tenant_id, customer_id=ctx.customer_id,
                project_id=ctx.project_id, data_scope=ctx.data_scope,
                test_run_id=ctx.test_run_id)
        return self.get(skill_id, version)

    def get(self, skill_id: str, version: int) -> dict[str, Any]:
        row = self.repo.get_skill_version(skill_id, version)
        if row is None:
            raise CognitionValidationError(
                f"skill 不存在: {skill_id}@v{version}")
        return self._dict(row)

    @staticmethod
    def _dict(row: Any) -> dict[str, Any]:
        d = dict(row)
        d["input_schema"] = json.loads(d["input_schema_json"] or "{}")
        d["output_schema"] = json.loads(d["output_schema_json"] or "{}")
        d["tool_scopes"] = json.loads(d["tool_scopes_json"] or "[]")
        return d

    def validate(self, ctx: CognitiveContext, skill_id: str,
                 version: int, *, actor: str) -> dict[str, Any]:
        """draft→validated：schema 必须为 JSON object（完整性由发布门
        强制）。"""
        _require_ctx(ctx)
        item = self.get(skill_id, version)
        for key in ("input_schema", "output_schema"):
            if not isinstance(item[key], dict):
                raise CognitionValidationError(
                    f"{key} 必须为 JSON object")
        with UnitOfWork(self.store) as tx:
            rc = self.repo.cas_skill(tx, skill_id, version,
                                     to_status="validated",
                                     from_statuses=("draft",))
        if rc == 0:
            raise CognitionConflictError(
                f"skill {skill_id}@v{version} 不在 draft 状态"
                "（CAS 拒绝）")
        return self.get(skill_id, version)

    def publish(self, ctx: CognitiveContext, skill_id: str,
                version: int, *, approver: str, approval_id: str
                ) -> dict[str, Any]:
        """发布门：schema/execution_ref/risk/eval 缺一不可 + 人类批准
        账本（maker≠checker）；发布与旧版本降级同一事务。"""
        _require_ctx(ctx)
        item = self.get(skill_id, version)
        if not item["input_schema"] or not item["output_schema"]:
            raise CognitionValidationError(
                "发布必须有 input/output schema")
        if not item["execution_ref"]:
            raise CognitionValidationError("发布必须有 execution_ref")
        if not item["risk_level"]:
            raise CognitionValidationError("发布必须有 risk_level")
        if not item["evaluation_ref"]:
            raise CognitionValidationError(
                "发布必须有 evaluation_ref（评测证据）")
        if not approver:
            raise CognitionValidationError("发布必须人类 approver")
        self.policy.verify_approved(
            approval_id, kind=APPROVAL_KIND_PUBLISH,
            subject_ref=f"{skill_id}@v{version}", approver=approver,
            created_by=item["created_by"])
        with UnitOfWork(self.store) as tx:
            rc = self.repo.cas_skill(
                tx, skill_id, version, to_status="published",
                from_statuses=("validated",),
                extra_sets=", approved_by=?, published_at=?",
                extra_params=(approver, _now()))
            if rc:
                tx.execute(
                    "UPDATE skill_definition_version SET status='revoked'"
                    " WHERE skill_id=? AND status='published' AND"
                    " version!=?", (skill_id, version))
        if rc == 0:
            raise CognitionConflictError(
                f"skill {skill_id}@v{version} 不在 validated 状态"
                "（必须先 validate；CAS 拒绝）")
        return self.get(skill_id, version)

    def degrade(self, ctx: CognitiveContext, skill_id: str,
                version: int, *, actor: str, reason: str
                ) -> dict[str, Any]:
        """published→degraded（评测退化/故障）。"""
        _require_ctx(ctx)
        if not reason:
            raise CognitionValidationError("degrade 必须给出 reason")
        with UnitOfWork(self.store) as tx:
            rc = self.repo.cas_skill(
                tx, skill_id, version, to_status="degraded",
                from_statuses=("published",),
                extra_sets=", degraded_reason=?",
                extra_params=(reason,))
        if rc == 0:
            raise CognitionConflictError(
                f"skill {skill_id}@v{version} 不在 published 状态，"
                "不可 degrade（CAS 拒绝）")
        return self.get(skill_id, version)

    def revoke(self, ctx: CognitiveContext, skill_id: str,
               version: int, *, actor: str, approval_id: str
               ) -> dict[str, Any]:
        """废止必须人类批准（02 §8.4）。"""
        _require_ctx(ctx)
        item = self.get(skill_id, version)
        self.policy.verify_approved(
            approval_id, kind=APPROVAL_KIND_REVOKE,
            subject_ref=f"{skill_id}@v{version}", approver=actor,
            created_by=item["created_by"])
        with UnitOfWork(self.store) as tx:
            rc = self.repo.cas_skill(
                tx, skill_id, version, to_status="revoked",
                from_statuses=("published", "degraded"))
        if rc == 0:
            raise CognitionConflictError(
                f"skill {skill_id}@v{version} 不可 revoke（状态不允许）")
        return self.get(skill_id, version)

    # ---------- 发现面（RAG） vs 执行面 ----------

    def search(self, ctx: CognitiveContext, *, query: str
               ) -> list[dict[str, Any]]:
        """发现面：子串匹配 name/description，返回除 revoked 外各状态
        候选（V1 词法基线；Task 8 接入联邦检索）。命中 ≠ 可执行。"""
        _require_ctx(ctx)
        q = (query or "").strip()
        rows = self.repo.list_skills_not_revoked()
        out = []
        for r in rows:
            d = self._dict(r)
            if not q or q in d["name"] or q in d["description"]:
                out.append(d)
        return out

    def can_execute(self, ctx: CognitiveContext, skill_id: str
                    ) -> dict[str, Any]:
        """执行面独立判定：仅 published 版本可执行；high/critical 风险
        需人工 gate。Skill RAG 命中/旧资产投影都不构成执行授权。"""
        _require_ctx(ctx)
        rows = self.repo.list_skill_versions(skill_id)
        published = next((self._dict(r) for r in rows
                          if r["status"] == "published"), None)
        if published is None:
            return {"allowed": False, "requires_human_gate": False,
                    "reasons": ["无 published 版本（命中/投影不构成"
                                "执行授权）"]}
        if published["risk_level"] in ("high", "critical"):
            return {"allowed": False, "requires_human_gate": True,
                    "reasons": [f"risk={published['risk_level']} 需人工"
                                " gate"]}
        return {"allowed": True, "requires_human_gate": False,
                "reasons": []}

    # ---------- 旧表只读兼容投影 ----------

    def legacy_projection(self, ctx: CognitiveContext
                          ) -> list[dict[str, Any]]:
        """agent_asset_v1(kind='skill') 只读投影；不构成执行授权。"""
        _require_ctx(ctx)
        out = []
        for r in self.repo.list_legacy_skill_assets():
            d = dict(r)
            d["_origin"] = "agent_asset_v1"
            d["_writable"] = False
            out.append(d)
        return out
