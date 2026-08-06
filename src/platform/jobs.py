"""W6/M2：Job/Attempt 状态机（显式转移表，可识别 orphaned，可恢复语义）。

Task 13：区分两类时间语义（禁止混淆）：
- attempt_timeout_at：单次尝试（如一次 VLM 推理）的超时，只影响当次 attempt，
  触发重试/降级，绝不等于整个任务过期；
- queue_deadline_at：队列业务 SLA（12h/48h），到期必须转人工/降级/expired 并写审计。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

JOB_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"succeeded", "failed", "expired"}),
    "failed": frozenset({"queued"}),  # 重试 = 重新排队（新 attempt）
    "succeeded": frozenset(),
    "cancelled": frozenset(),
    "expired": frozenset(),  # 队列 SLA 到期：终态，须转人工/降级处置
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


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def attempt_expired(job: dict[str, Any], *, now_iso: str | None = None) -> bool:
    """单次 attempt 是否超时（只影响当次尝试，不终止任务）。"""
    t = job.get("attempt_timeout_at")
    return bool(t) and (now_iso or _utcnow_iso()) >= t


def queue_deadline_passed(job: dict[str, Any], *, now_iso: str | None = None) -> bool:
    """队列业务 SLA 是否到期（到期必须转人工/降级/expired）。"""
    t = job.get("queue_deadline_at")
    return bool(t) and (now_iso or _utcnow_iso()) >= t


def expire_job_at_deadline(store, job_id: str, *, actor: str = "scheduler") -> str | None:
    """若 job 已过 queue_deadline_at 且处于非终态，则置为 expired 并写审计。

    返回 'expired'；未到 deadline、无 deadline 或 job 已终态时返回 None（不做任何事）。
    单次 attempt_timeout_at 过期不触发本函数语义——attempt 超时由 worker 重试/降级处理。
    """
    job = store.get_job(job_id)
    if job["status"] not in ("queued", "running"):
        return None  # 已终态，不得覆盖结果
    if not queue_deadline_passed(job):
        return None
    transition(job["status"], "expired")  # 状态机校验（非法即抛错）
    store.set_job_status(job_id, "expired", error="queue_deadline_expired")
    store.append_audit(
        actor=actor,
        action="job.queue_deadline_expired",
        subject_type="job",
        subject_id=job_id,
        detail={
            "queue_deadline_at": job.get("queue_deadline_at"),
            "kind": job.get("kind"),
            "prior_status": job["status"],
        },
    )
    return "expired"
