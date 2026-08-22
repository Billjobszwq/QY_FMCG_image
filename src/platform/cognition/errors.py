"""认知内核错误分类（fail-closed，任务书 §八.4）。

区分 validation / policy / permission / conflict / retryable / provider /
budget / integrity；不用空结果掩盖异常。稳定错误码随消息携带。
"""
from __future__ import annotations


class CognitionError(Exception):
    """认知内核域错误基类。code 为稳定错误码。"""

    code = "COGNITION_ERROR"

    def __init__(self, detail: str = "") -> None:
        super().__init__(f"{self.code}: {detail}" if detail else self.code)
        self.detail = detail


class CognitionValidationError(CognitionError):
    """输入契约校验失败（缺字段/非法枚举/未知字段）。"""

    code = "COGNITION_VALIDATION_FAILED"


class CognitionPolicyError(CognitionError):
    """Policy 决策拒绝（含不可信输入试图覆盖服务端上下文）。"""

    code = "COGNITION_POLICY_DENIED"


class CognitionPermissionDeniedError(CognitionError):
    """权限/ACL/tenant/customer 过滤拒绝（fail-closed，不回退全局）。"""

    code = "COGNITION_PERMISSION_DENIED"


class CognitionConflictError(CognitionError):
    """状态冲突（版本/CAS/并发/知识冲突待裁决）。"""

    code = "COGNITION_CONFLICT"


class CognitionRetryableError(CognitionError):
    """可重试的暂时性失败（调用方可带退避重试）。"""

    code = "COGNITION_RETRYABLE"


class CognitionProviderError(CognitionError):
    """外部 provider（embedding/reranker/LLM/web）不可用或降级。"""

    code = "COGNITION_PROVIDER_UNAVAILABLE"


class CognitionBudgetError(CognitionError):
    """预算耗尽（query/token/cost/deadline/loop）。"""

    code = "COGNITION_BUDGET_EXCEEDED"


class CognitionIntegrityError(CognitionError):
    """完整性违规（hash 不匹配/不可变对象被改/snapshot 漂移）。"""

    code = "COGNITION_INTEGRITY_VIOLATION"
