"""CognitiveContext：所有认知读写的服务端唯一上下文（02 §1）。

硬约束：
- 任何字段不得由 LLM/外部输入填写或覆盖（untrusted_overrides 非 None
  且含任何键即拒绝，含 falsy Mapping 子类）；
- 缺 principal/tenant/action/as_of fail-closed；
- fixture（test/UAT）scope 不得被任何路径降级为 operational；
- operational 上下文不得携带 test_run_id（泄漏形态，fail-closed）；
- customer_id/project_id 为空的唯一情况由 EMPTY_SCOPE_POLICY 显式声明
  （V1 为静态声明；Task 4 起由版本化 Policy Service 接管）；
- data_scope 仅接受平台已登记集合；
- 反序列化任何异常归一为 CognitionValidationError（稳定错误码）。
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import Any, Mapping

from ..scope import DATA_SCOPES, FIXTURE_SCOPES, ExecutionContext
from .contracts import canonical_hash
from .errors import CognitionPolicyError, CognitionValidationError

# 平台级动作声明：允许 customer_id/project_id 为空（02 §1 的显式例外）。
# 任何未在此声明的动作携带空 customer/project → fail-closed。
EMPTY_SCOPE_POLICY: frozenset[str] = frozenset({
    "cognition.platform.health",
    "cognition.knowledge.search",
    "cognition.memory.search",
    "cognition.skills.search",
    "cognition.skills.can_execute",
    "cognition.research.start",
    # 平台级认知操作允许空 customer/project（平台级知识/索引摄取）
    "cognition.sources.ingest",
    "cognition.document.publish",
    "cognition.knowledge.draft",
    "cognition.knowledge.publish",
    "cognition.index.build",
    "cognition.index.activate",
    # R2-03：平台级 Research 动作允许空 customer/project；对已有 run
    # 的访问仍由 ResearchRunAccessPolicy 与 run 持久化 scope 对账。
    "cognition.read",
    "cognition.manage",
    "research.read",
    "research.run",
    "research.decide",
    "research.run.start",
    "research.run.resume",
    "research.run.cancel",
    "research.run.decide",
    "research.claims.read",
    "research.citations.verify",
    "research.synthesize",
})


def _permission_tags(value: Any) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise CognitionValidationError(
            "permission_tags 必须为字符串序列（拒绝裸字符串，"
            "防逐字符拆散安全标签）")
    for item in value:
        if not isinstance(item, str) or not item:
            raise CognitionValidationError(
                "permission_tags 元素必须为非空字符串")
    return tuple(sorted(value))  # 排序：集合语义 + hash 稳定


def _normalize_as_of(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as e:
            raise CognitionValidationError(
                f"as_of 无法解析: {value!r}") from e
    if not isinstance(value, datetime):
        raise CognitionValidationError("as_of 必须为 datetime")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)  # naive 视为 UTC
    return value.astimezone(timezone.utc)  # 统一 UTC，hash 稳定


@dataclass(frozen=True)
class CognitiveContext:
    principal_id: str
    tenant_id: str
    customer_id: str
    project_id: str
    test_run_id: str
    data_scope: str
    action: str
    permission_tags: tuple[str, ...]
    purpose: str
    correlation_id: str
    parent_run_id: str | None
    as_of: datetime

    def __post_init__(self) -> None:
        if not self.principal_id:
            raise CognitionValidationError(
                "CognitiveContext 缺 principal_id（fail-closed）")
        if not self.tenant_id:
            raise CognitionValidationError(
                "CognitiveContext 缺 tenant_id（fail-closed）")
        if not self.action:
            raise CognitionValidationError(
                "CognitiveContext 缺 action（fail-closed）")
        object.__setattr__(self, "as_of", _normalize_as_of(self.as_of))
        if self.data_scope not in DATA_SCOPES:
            raise CognitionValidationError(
                f"未知 data_scope: {self.data_scope}")
        if self.data_scope in FIXTURE_SCOPES and not self.test_run_id:
            raise CognitionValidationError(
                f"fixture scope {self.data_scope} 必须携带 test_run_id")
        if self.data_scope == "operational" and self.test_run_id:
            raise CognitionValidationError(
                "operational 上下文不得携带 test_run_id（泄漏形态）")
        object.__setattr__(self, "permission_tags",
                           _permission_tags(self.permission_tags))
        # 空 customer/project 仅允许 Policy 显式声明的动作（02 §1）
        if not self.customer_id and self.action not in EMPTY_SCOPE_POLICY:
            raise CognitionPolicyError(
                f"action={self.action} 未声明允许空 customer_id"
                "（EMPTY_SCOPE_POLICY）")
        if not self.project_id and self.action not in EMPTY_SCOPE_POLICY:
            raise CognitionPolicyError(
                f"action={self.action} 未声明允许空 project_id"
                "（EMPTY_SCOPE_POLICY）")

    # ---------- 序列化 ----------

    def to_dict(self) -> dict[str, Any]:
        return {
            "principal_id": self.principal_id,
            "tenant_id": self.tenant_id,
            "customer_id": self.customer_id,
            "project_id": self.project_id,
            "test_run_id": self.test_run_id,
            "data_scope": self.data_scope,
            "action": self.action,
            "permission_tags": list(self.permission_tags),
            "purpose": self.purpose,
            "correlation_id": self.correlation_id,
            "parent_run_id": self.parent_run_id,
            "as_of": self.as_of.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CognitiveContext":
        if not isinstance(data, Mapping):
            raise CognitionValidationError("CognitiveContext 需要 object")
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise CognitionValidationError(
                f"CognitiveContext 未知字段: {unknown}")
        missing = sorted(known - set(data))
        if missing:
            raise CognitionValidationError(
                f"CognitiveContext 缺失字段: {missing}")
        d = dict(data)
        tags = d.get("permission_tags")
        if isinstance(tags, (list, tuple)):
            d["permission_tags"] = list(tags)
        # 裸字符串等非法类型原样传入，由 _permission_tags fail-closed
        try:
            return cls(**d)
        except (CognitionPolicyError, CognitionValidationError):
            raise
        except (TypeError, ValueError) as e:
            raise CognitionValidationError(
                f"CognitiveContext 构造失败: {e}") from e

    def content_hash(self) -> str:
        return canonical_hash(self.to_dict())

    @classmethod
    def hash_of(cls, data: Mapping[str, Any]) -> str:
        return canonical_hash(data)

    # ---------- 语义辅助 ----------

    def is_fixture(self) -> bool:
        return self.data_scope in FIXTURE_SCOPES


def context_from_scope(scope: ExecutionContext, *, principal_id: str,
                       action: str, purpose: str = "",
                       permission_tags: tuple[str, ...] = (),
                       correlation_id: str = "",
                       parent_run_id: str | None = None,
                       as_of: datetime,
                       force_data_scope: str | None = None,
                       untrusted_overrides: Mapping[str, Any] | None = None
                       ) -> CognitiveContext:
    """从服务端 ScopeResolver 结果构造 CognitiveContext（唯一合法入口）。

    - `untrusted_overrides` 非 None 且含任何键即拒绝（含 falsy Mapping
      子类）：LLM/文档/网页/检索内容不得改写上下文任何字段；
    - `force_data_scope` 恒拒绝：不存在 scope 降级旁路；
    - scope.tenant_id 为空即拒绝（不做默认值洗白）。
    """
    if untrusted_overrides is not None and len(untrusted_overrides) > 0:
        raise CognitionPolicyError(
            "不可信输入试图覆盖服务端 CognitiveContext"
            f"（字段: {sorted(untrusted_overrides)}）")
    if force_data_scope is not None:
        raise CognitionPolicyError(
            "禁止强制改写 data_scope（fixture 不得降级 operational）")
    if not principal_id:
        raise CognitionValidationError("principal_id 必填（服务端身份）")
    if not action:
        raise CognitionValidationError("action 必填（策略决策输入）")
    if not scope.tenant_id:
        raise CognitionValidationError(
            "scope 缺 tenant_id（fail-closed，不得默认洗白）")
    return CognitiveContext(
        principal_id=principal_id,
        tenant_id=scope.tenant_id,
        customer_id=scope.customer_id or "",
        project_id=scope.project_id or "",
        test_run_id=scope.test_run_id or "",
        data_scope=scope.data_scope or "operational",
        action=action,
        permission_tags=permission_tags,
        purpose=purpose,
        correlation_id=correlation_id or scope.correlation_id or "",
        parent_run_id=parent_run_id or (scope.parent_run_id or None),
        as_of=as_of,
    )
