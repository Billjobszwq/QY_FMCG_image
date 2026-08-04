"""W6/M2：Job/Attempt 状态机（显式转移表，可识别 orphaned，可恢复语义）。"""

from __future__ import annotations

JOB_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"succeeded", "failed"}),
    "failed": frozenset({"queued"}),  # 重试 = 重新排队（新 attempt）
    "succeeded": frozenset(),
    "cancelled": frozenset(),
}


class JobTransitionError(Exception):
    """非法状态转移。"""


def allowed_transitions(status: str) -> set[str]:
    if status not in JOB_TRANSITIONS:
        raise JobTransitionError(f"未知 job 状态: {status}")
    return set(JOB_TRANSITIONS[status])


def transition(current: str, target: str) -> str:
    if target not in allowed_transitions(current):
        raise JobTransitionError(f"非法转移: {current} -> {target}")
    return target
