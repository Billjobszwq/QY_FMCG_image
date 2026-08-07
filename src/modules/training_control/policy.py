"""GLTC Task 6：GraphPolicy 与 Agent DomainCommand 白名单。

Agent 可以建议计划、解释阻断、触发经授权的 DomainCommand，
但不能直接写数据库、拼任意 shell、自行批准训练/发布。
客户档位（L/M/H/X）是服务策略，不是训练 lane。
"""
from __future__ import annotations

from typing import Any

from .graph import GraphError

# Agent 可触发的命令（只读/建议/停止类，不含批准与发布）
AGENT_ALLOWED_COMMANDS: frozenset[str] = frozenset({
    "training.plan.create",
    "training.plan.request_approval",
    "training.dataset.build",
    "training.run.status",
    "training.run.safe_stop",
    "training.explain_blockers",
})

# 仅人类可执行（Agent 一律拒绝）
HUMAN_ONLY_COMMANDS: frozenset[str] = frozenset({
    "training.authorize",
    "training.plan.approve",
    "training.run.launch",
    "training.publish.request",
    "training.publish.approve",
})


class AgentCommandGate:
    """DomainCommand 白名单校验（fail-closed）。"""

    def allowed(self) -> frozenset[str]:
        return AGENT_ALLOWED_COMMANDS

    def validate(self, command: str, payload: dict[str, Any],
                 *, actor_kind: str = "agent") -> None:
        if command in HUMAN_ONLY_COMMANDS:
            if actor_kind == "agent":
                raise GraphError(
                    f"命令 {command} 仅限人类执行，Agent 不得自批")
            return
        if command not in AGENT_ALLOWED_COMMANDS:
            raise GraphError(
                f"命令不在白名单（拒绝任意 SQL/shell/文件写）: {command}")
