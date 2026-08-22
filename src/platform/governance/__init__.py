"""治理平面（Task 4 起）：版本化 Policy、告警、快照、暂停。

角色边界（服务层强制，不依赖 Prompt）：
- RulesAgentRole：只能 draft 规则与申请发布；
- SilentAgentRole：只能告警/快照/暂停请求；
- 发布规则、恢复熔断、发布 L3/Skill 等只有人类批准（approval 账本）。
"""


class GovernanceError(Exception):
    """治理域错误（稳定错误码随消息携带）。"""

    code = "GOVERNANCE_ERROR"

    def __init__(self, detail: str = "") -> None:
        super().__init__(f"{self.code}: {detail}" if detail else self.code)
        self.detail = detail


class GovernanceRoleError(GovernanceError):
    """角色越权（如非 silent_agent 发告警、maker=checker）。"""

    code = "GOVERNANCE_ROLE_DENIED"


class GovernanceConflictError(GovernanceError):
    """CAS/状态冲突（迟到写、重复决策、终态再迁移）。"""

    code = "GOVERNANCE_CONFLICT"
