"""三层记忆生命周期服务（Task 6 / G4；评审修复后版本）。

不变量：
- L1 只追加（DB 触发器 + 服务层不提供 update/delete）；
- L2 仅 Consolidator 生成 candidate；(source_hash, consolidator_version)
  幂等；发布必须 governance approval 账本中的人类批准（maker≠checker）；
- L3 仅 Consolidator/Rules 提 candidate；**独立**事件数不足（去重后
  <3）、来源 L2 未发布、反例未清时不得发布；发布必须人类批准；
- candidate 永不进入 published 检索面；
- 角色与 principal 绑定校验（verify_role，评审 #13）；
- 所有持久化经 CognitionRepository/UoW。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from ...governance.policy_service import PolicyService
from ..context import CognitiveContext
from ..errors import (
    CognitionConflictError,
    CognitionPermissionDeniedError,
    CognitionValidationError,
)
from ..repository import CognitionRepository, UnitOfWork
from .consolidation import source_hash as _source_hash

CONSOLIDATOR_ROLES = frozenset({"consolidator"})
L3_PROPOSER_ROLES = frozenset({"consolidator", "rules_agent"})
MIN_INDEPENDENT_EVENTS = 3  # 单个案例不得形成 L3（04 §14）

# 角色 → 允许的 principal（服务端绑定；调用方自报 role 必须与
# principal 匹配，评审 #13。真实登记在 Task 4+ Policy 接管前为静态表）。
ROLE_PRINCIPALS: dict[str, frozenset[str]] = {
    "consolidator": frozenset({"memory_consolidator"}),
    "rules_agent": frozenset({"rules_agent"}),
}

APPROVAL_KIND_L2 = "cognition.l2.publish"
APPROVAL_KIND_L3 = "cognition.l3.publish"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_ctx(ctx: CognitiveContext | None) -> None:
    if ctx is None:
        raise CognitionValidationError("缺 CognitiveContext（fail-closed）")


def verify_role(actor_role: str, actor: str) -> None:
    principals = ROLE_PRINCIPALS.get(actor_role)
    if principals is None or actor not in principals:
        raise CognitionPermissionDeniedError(
            f"actor={actor!r} 不是 role={actor_role!r} 的登记 principal"
            "（角色不得自报冒用）")


class MemoryLifecycleService:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.repo = CognitionRepository(store)
        self.policy = PolicyService(store)

    # ---------- L1（所有角色 append-only） ----------

    def append_l1(self, ctx: CognitiveContext, *, task_id: str,
                  run_id: str, node_id: str, actor_id: str,
                  actor_kind: str, event_type: str,
                  payload: dict[str, Any],
                  permission_tags: tuple[str, ...] | list[str],
                  retention_class: str = "permanent",
                  context_meaning: str | None = None,
                  evidence_refs: list[str] | None = None,
                  supersedes: str | None = None) -> str:
        _require_ctx(ctx)
        if actor_kind not in ("human", "agent", "system"):
            raise CognitionValidationError(
                f"非法 actor_kind: {actor_kind}")
        if not event_type or not actor_id:
            raise CognitionValidationError("event_type/actor_id 必填")
        tags = list(permission_tags or [])
        if not tags or any(not isinstance(t, str) or not t for t in tags):
            raise CognitionValidationError(
                "permission_tags 必填（fail-closed，不得降级全局可见）")
        if supersedes is not None and self.repo.get_l1(supersedes) is None:
            raise CognitionValidationError(
                f"supersedes 目标不存在: {supersedes}")
        event_id = "l1-" + uuid.uuid4().hex[:16]
        with UnitOfWork(self.store) as tx:
            self.repo.insert_l1(
                tx, event_id=event_id, task_id=task_id, run_id=run_id,
                node_id=node_id, actor_id=actor_id, actor_kind=actor_kind,
                event_type=event_type, payload=dict(payload or {}),
                context_meaning=context_meaning,
                evidence_refs=list(evidence_refs or []),
                occurred_at=_now(), ingested_at=_now(),
                permission_tags=tuple(tags),
                retention_class=retention_class, supersedes=supersedes,
                tenant_id=ctx.tenant_id, customer_id=ctx.customer_id,
                project_id=ctx.project_id, data_scope=ctx.data_scope,
                test_run_id=ctx.test_run_id)
        return event_id

    def get_l1(self, event_id: str) -> dict[str, Any]:
        row = self.repo.get_l1(event_id)
        if row is None:
            raise CognitionValidationError(f"L1 事件不存在: {event_id}")
        return row

    # ---------- L2（Consolidator candidate + 人类发布） ----------

    def consolidate_l1_to_l2(self, ctx: CognitiveContext, *,
                             actor_role: str, actor: str, task_id: str,
                             period_start: str, period_end: str,
                             l1_ids: list[str],
                             entities: list[str] | None = None,
                             solution: str = "", result: str = "",
                             issues: list[str] | None = None,
                             conflicts: list[str] | None = None,
                             confidence: float = 0.5,
                             consolidator_version: str = "consolidator@1"
                             ) -> dict[str, Any]:
        _require_ctx(ctx)
        if actor_role not in CONSOLIDATOR_ROLES:
            raise CognitionPermissionDeniedError(
                f"role={actor_role} 不得写 L2（仅 Consolidator 可生成"
                " candidate；普通 Agent 只读）")
        verify_role(actor_role, actor)
        if not l1_ids:
            raise CognitionValidationError("l1_ids 必填")
        for eid in l1_ids:
            self.get_l1(eid)
        source_hash = _source_hash(task_id, l1_ids)
        existing = self.repo.find_l2_by_source_hash(
            source_hash, consolidator_version)
        if existing is not None:
            return self._l2_dict(existing)
        episode_id = "l2-" + uuid.uuid4().hex[:16]
        with UnitOfWork(self.store) as tx:
            self.repo.insert_l2(
                tx, episode_id=episode_id, task_id=task_id,
                period_start=period_start, period_end=period_end,
                entities=list(entities or []), solution=solution,
                result=result, issues=list(issues or []),
                conflicts=list(conflicts or []),
                source_l1_ids=list(l1_ids), source_hash=source_hash,
                consolidator_version=consolidator_version,
                confidence=confidence,
                permission_tags=tuple(ctx.permission_tags),
                created_by=actor, created_at=_now(),
                tenant_id=ctx.tenant_id, customer_id=ctx.customer_id,
                project_id=ctx.project_id, data_scope=ctx.data_scope,
                test_run_id=ctx.test_run_id)
        return self.get_l2(episode_id)

    def get_l2(self, episode_id: str) -> dict[str, Any]:
        row = self.repo.get_l2(episode_id)
        if row is None:
            raise CognitionValidationError(f"L2 不存在: {episode_id}")
        return self._l2_dict(row)

    @staticmethod
    def _l2_dict(row: Any) -> dict[str, Any]:
        d = dict(row)
        d["source_l1_ids"] = json.loads(d["source_l1_ids_json"] or "[]")
        d["entities"] = json.loads(d["entities_json"] or "[]")
        d["issues"] = json.loads(d["issues_json"] or "[]")
        d["conflicts"] = json.loads(d["conflicts_json"] or "[]")
        return d

    def count_l2(self) -> int:
        return len(self.repo.list_l2(status="candidate")) + len(
            self.repo.list_l2(status="published"))

    def publish_l2(self, episode_id: str, *, approver: str,
                   approval_id: str) -> dict[str, Any]:
        """人工发布门：governance approval 账本校验 + CAS。"""
        if not approver:
            raise CognitionValidationError("发布 L2 必须人类 approver")
        ep = self.get_l2(episode_id)
        self.policy.verify_approved(
            approval_id, kind=APPROVAL_KIND_L2,
            subject_ref=f"l2:{episode_id}", approver=approver,
            created_by=ep["created_by"])
        with UnitOfWork(self.store) as tx:
            rc = self.repo.cas_l2(
                tx, episode_id, to_status="published",
                from_statuses=("candidate",),
                extra_sets=", approved_by=?, published_at=?",
                extra_params=(approver, _now()))
        if rc == 0:
            raise CognitionConflictError(
                f"L2 {episode_id} 不在 candidate 状态（CAS 拒绝）")
        return self.get_l2(episode_id)

    def mark_l2_conflict(self, episode_id: str, *, actor: str
                         ) -> dict[str, Any]:
        """冲突并存标记（02 §4.2：不静默覆盖；评审 #9/#25）。"""
        with UnitOfWork(self.store) as tx:
            rc = self.repo.cas_l2(tx, episode_id, to_status="conflict",
                                  from_statuses=("candidate",
                                                 "published"))
        if rc == 0:
            raise CognitionConflictError(
                f"L2 {episode_id} 状态不允许标记 conflict")
        return self.get_l2(episode_id)

    def archive_l2(self, episode_id: str, *, actor: str,
                   approval_id: str) -> dict[str, Any]:
        self.policy.verify_approved(
            approval_id, kind="cognition.l2.archive",
            subject_ref=f"l2:{episode_id}", approver=actor,
            created_by=self.get_l2(episode_id)["created_by"])
        with UnitOfWork(self.store) as tx:
            rc = self.repo.cas_l2(tx, episode_id, to_status="archived",
                                  from_statuses=("published",))
        if rc == 0:
            raise CognitionConflictError(
                f"L2 {episode_id} 不在 published 状态，不可 archive")
        return self.get_l2(episode_id)

    def published_l2_episodes(self, ctx: CognitiveContext, *,
                              task_id: str = "") -> list[dict[str, Any]]:
        _require_ctx(ctx)
        return [self._l2_dict(r) for r in self.repo.list_l2(
            status="published", task_id=task_id)]

    # ---------- L3（candidate + 反例/最小事件数 + 人类发布） ----------

    def propose_l3(self, ctx: CognitiveContext, *, actor_role: str,
                   actor: str, statement: str,
                   source_l2_ids: list[str],
                   trigger_conditions: list[str] | None = None,
                   scope: dict[str, Any] | None = None,
                   confidence: float = 0.5,
                   counterexample_ids: list[str] | None = None
                   ) -> dict[str, Any]:
        _require_ctx(ctx)
        if actor_role not in L3_PROPOSER_ROLES:
            raise CognitionPermissionDeniedError(
                f"role={actor_role} 不得写 L3（仅 Consolidator/Rules 可"
                " 提 candidate）")
        verify_role(actor_role, actor)
        if not statement or not statement.strip():
            raise CognitionValidationError("statement 必填")
        # 独立事件：去重（评审 #3——重复 ID 不得虚增门）
        ids = sorted(set(source_l2_ids or []))
        if len(ids) < MIN_INDEPENDENT_EVENTS:
            raise CognitionValidationError(
                f"L3 至少需要 {MIN_INDEPENDENT_EVENTS} 个**独立**已发布"
                f" L2 事件（去重后 {len(ids)}）；单个案例不得形成方法论")
        for eid in ids:
            row = self.repo.get_l2(eid)
            if row is None:
                raise CognitionValidationError(f"L2 不存在: {eid}")
            if row["status"] != "published":
                raise CognitionValidationError(
                    f"L2 {eid} 未发布（status={row['status']}），"
                    "不得作为 L3 来源")
        methodology_id = "m-" + uuid.uuid4().hex[:12]
        with UnitOfWork(self.store) as tx:
            self.repo.insert_l3(
                tx, methodology_id=methodology_id, version=1,
                statement=statement,
                trigger_conditions=list(trigger_conditions or []),
                scope=dict(scope or {}), confidence=confidence,
                source_l2_ids=ids, supporting_event_count=len(ids),
                counterexample_ids=list(counterexample_ids or []),
                created_by=actor, created_at=_now(),
                tenant_id=ctx.tenant_id, customer_id=ctx.customer_id,
                project_id=ctx.project_id, data_scope=ctx.data_scope,
                test_run_id=ctx.test_run_id)
        return self.get_l3(methodology_id, 1)

    def get_l3(self, methodology_id: str, version: int) -> dict[str, Any]:
        row = self.repo.get_l3(methodology_id, version)
        if row is None:
            raise CognitionValidationError(
                f"L3 不存在: {methodology_id}@v{version}")
        d = dict(row)
        d["source_l2_ids"] = json.loads(d["source_l2_ids_json"] or "[]")
        d["counterexample_ids"] = json.loads(
            d["counterexample_ids_json"] or "[]")
        return d

    def record_counterexample(self, methodology_id: str, version: int,
                              *, counterexample_id: str, actor: str
                              ) -> dict[str, Any]:
        """反例补录（评审 #12：提议后仍可补录反例阻断发布）。"""
        m = self.get_l3(methodology_id, version)
        ids = set(m["counterexample_ids"]) | {counterexample_id}
        with UnitOfWork(self.store) as tx:
            rc = self.repo.append_l3_counterexamples(
                tx, methodology_id, version, sorted(ids))
        if rc == 0:
            raise CognitionConflictError(
                f"L3 {methodology_id}@v{version} 反例补录失败")
        return self.get_l3(methodology_id, version)

    def publish_l3(self, methodology_id: str, version: int, *,
                   approver: str, approval_id: str) -> dict:
        """人工发布门：approver 必填；反例未清禁止发布；approval 账本
        校验 + CAS + 旧版本 superseded。"""
        m = self.get_l3(methodology_id, version)
        if not approver:
            raise CognitionValidationError("发布 L3 必须人类 approver")
        if m["counterexample_ids"]:
            raise CognitionConflictError(
                f"L3 {methodology_id}@v{version} 存在未裁决反例"
                f" {m['counterexample_ids']}，禁止发布")
        self.policy.verify_approved(
            approval_id, kind=APPROVAL_KIND_L3,
            subject_ref=f"l3:{methodology_id}@v{version}",
            approver=approver, created_by=m["created_by"])
        with UnitOfWork(self.store) as tx:
            rc = self.repo.cas_l3(
                tx, methodology_id, version, to_status="published",
                from_statuses=("candidate",),
                extra_sets=", approved_by=?, approval_id=?,"
                           " published_at=?",
                extra_params=(approver, approval_id, _now()))
            if rc:
                tx.execute(
                    "UPDATE memory_l3_methodology_version SET"
                    " status='superseded' WHERE methodology_id=? AND"
                    " status='published' AND version!=?",
                    (methodology_id, version))
        if rc == 0:
            raise CognitionConflictError(
                f"L3 {methodology_id}@v{version} 不在 candidate 状态"
                "（CAS 拒绝）")
        return self.get_l3(methodology_id, version)

    def revoke_l3(self, methodology_id: str, version: int, *,
                  actor: str, approval_id: str) -> dict[str, Any]:
        """已发布 L3 被证伪 → revoked（评审 #9）。"""
        m = self.get_l3(methodology_id, version)
        self.policy.verify_approved(
            approval_id, kind="cognition.l3.revoke",
            subject_ref=f"l3:{methodology_id}@v{version}",
            approver=actor, created_by=m["created_by"])
        with UnitOfWork(self.store) as tx:
            rc = self.repo.cas_l3(
                tx, methodology_id, version, to_status="revoked",
                from_statuses=("published",))
        if rc == 0:
            raise CognitionConflictError(
                f"L3 {methodology_id}@v{version} 不在 published 状态，"
                "不可 revoke")
        return self.get_l3(methodology_id, version)

    def published_l3(self, ctx: CognitiveContext) -> list[dict[str, Any]]:
        """检索面只返回已发布方法论；candidate 永不可见。"""
        _require_ctx(ctx)
        out = []
        for row in self.repo.list_l3(status="published"):
            d = dict(row)
            d["source_l2_ids"] = json.loads(
                d["source_l2_ids_json"] or "[]")
            d["counterexample_ids"] = json.loads(
                d["counterexample_ids_json"] or "[]")
            out.append(d)
        return out
