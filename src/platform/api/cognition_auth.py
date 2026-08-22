"""R2-03：cognition/research API 唯一上下文工厂 + Research run 访问策略。

安全契约（round-2-hardening/01 §4）：
- 客户端可以请求 customer/project/test_run，但不能自证有权访问；
  必须由 IAM action permission + ScopeResolver 服务端验证；
- run ID 不是授权凭证：读取/变更已有 run 必须与其持久化 scope 完全匹配；
- citations/synthesize 使用 run 持久化 scope，不接受 query 参数改写；
- 无权与不存在使用统一安全响应，不泄露 question/state/counts。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from ..cognition.context import CognitiveContext, context_from_scope
from ..cognition.errors import CognitionPermissionDeniedError
from ..iam import IAMService
from ..scope import ScopeResolver, ScopeViolation


def _tags_for(principal: Mapping[str, Any]) -> tuple[str, ...]:
    """permission_tags：admin/平台角色更宽；其余最小化（fail-closed）。"""
    if principal.get("role") == "admin":
        return ("public", "internal")
    return ("public",)


def is_platform_principal(iam: IAMService,
                          principal: Mapping[str, Any]) -> bool:
    """平台级主体：env admin 或 IAM owner/platform_admin membership。
    平台例外必须由 IAM 明确授权（role bundle），不由 role 字符串
    硬编码其他角色。"""
    if principal.get("role") == "admin":
        return True
    try:
        return iam.visible_customers(principal["actor"]) is None
    except Exception:
        return False


def build_context(*, store: Any, iam: IAMService,
                  principal: Mapping[str, Any], permission: str,
                  action: str = "",
                  customer_id: str = "", project_id: str = "",
                  test_run_id: str = "",
                  permission_tags: tuple[str, ...] | None = None
                  ) -> CognitiveContext:
    """session principal -> IAM authorize -> ScopeResolver ->
    context_from_scope（唯一 API 构造器）。

    - `permission` 必须是已注册 IAM scope（如 research.run）；
      IAM authorize 校验 permission 与 customer/project membership；
    - `action` 是写入 CognitiveContext 的动作描述，缺省同 permission；
    - ScopeResolver 解析 operational/UAT/parent scope；fail-closed；
    - 平台级主体（env admin / owner / platform_admin）视为已授权
      （由 IAM bundle 决定，非硬编码旁路）。
    """
    if not principal or not principal.get("actor"):
        raise CognitionPermissionDeniedError("缺 session principal")
    if not is_platform_principal(iam, principal):
        if not iam.authorize(principal["actor"], permission,
                             customer_id=customer_id,
                             project_id=project_id):
            raise CognitionPermissionDeniedError(
                f"principal {principal['actor']!r} 无 {permission}"
                " 权限或无 customer/project membership")
    try:
        scope = ScopeResolver(store).resolve(
            test_run_id=test_run_id, customer_id=customer_id,
            project_id=project_id, actor_id=principal["actor"],
            source="api", tenant_id="local")
    except ScopeViolation as e:
        raise CognitionPermissionDeniedError(
            f"scope 解析失败（fail-closed）: {e}")
    tags = (permission_tags if permission_tags is not None
            else _tags_for(principal))
    return context_from_scope(
        scope, principal_id=principal["actor"], action=action or permission,
        purpose="api", permission_tags=tuple(tags),
        as_of=datetime.now(timezone.utc))


def context_from_run(run: Mapping[str, Any], *, principal_id: str,
                     action: str,
                     permission_tags: tuple[str, ...] | None = None
                     ) -> CognitiveContext:
    """从 run 持久化 scope 派生上下文（citations/synthesize 与已授权
    操作使用；不接受 query 参数改写，round-2 §4.2）。"""
    return CognitiveContext(
        principal_id=principal_id,
        tenant_id=run.get("tenant_id", "local") or "local",
        customer_id=run.get("customer_id", "") or "",
        project_id=run.get("project_id", "") or "",
        test_run_id=run.get("test_run_id", "") or "",
        data_scope=run.get("data_scope", "operational") or "operational",
        action=action,
        permission_tags=(permission_tags if permission_tags is not None
                         else tuple(run.get("permission_tags") or
                                    ("public",))),
        purpose="api", correlation_id="", parent_run_id=None,
        as_of=datetime.now(timezone.utc))


class ResearchRunAccessPolicy:
    """run ID 不是授权凭证：读取/变更已有 run 必须 IAM permission +
    持久化 scope 完全匹配。平台角色例外必须由 IAM 明确授权。"""

    def __init__(self, iam: IAMService) -> None:
        self.iam = iam

    def require(self, ctx: CognitiveContext, run: Mapping[str, Any], *,
                permission: str,
                principal: Mapping[str, Any] | None = None) -> None:
        # 1) IAM action permission（平台角色视为已授权）
        if principal is not None and is_platform_principal(
                self.iam, principal):
            pass
        elif not self.iam.authorize(ctx.principal_id, permission,
                                    customer_id=run.get("customer_id", "")
                                    or "",
                                    project_id=run.get("project_id", "")
                                    or ""):
            raise CognitionPermissionDeniedError(
                f"无 {permission} 权限")
        # 2) tenant / data_scope / test_run 完全一致
        if (run.get("tenant_id", "local") or "local") != ctx.tenant_id:
            raise CognitionPermissionDeniedError("tenant 不匹配")
        if (run.get("data_scope", "operational") or
                "operational") != ctx.data_scope:
            raise CognitionPermissionDeniedError("data_scope 不匹配")
        if (run.get("test_run_id", "") or "") != ctx.test_run_id:
            raise CognitionPermissionDeniedError("test_run 不匹配")
        # 3) customer/project 匹配；平台主体例外（IAM 已明确授权跨客户）
        is_platform = (is_platform_principal(self.iam, principal)
                       if principal is not None else
                       self.iam.visible_customers(ctx.principal_id)
                       is None)
        rc = run.get("customer_id", "") or ""
        rp = run.get("project_id", "") or ""
        if not is_platform:
            if rc != ctx.customer_id:
                raise CognitionPermissionDeniedError("customer 不匹配")
            if rp != ctx.project_id:
                raise CognitionPermissionDeniedError("project 不匹配")


def safe_404() -> str:
    """统一安全响应消息：不泄露 run 是否存在/内容。"""
    return "research run 不存在或无权访问"
