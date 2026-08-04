"""M6：可恢复 JobWorker。

语义（对齐 jobs.py 状态机 queued→running→succeeded/failed，failed→queued 重试）：
- 原子认领（单语句 UPDATE + lease）：崩溃后 lease 过期可被重新排队；
- 重试：attempt_count < max_attempts → failed→queued（新 attempt 记账）；
- dead-letter：耗尽重试或 lease 过期且无剩余次数 → failed + error 'dead_letter: …'；
- 取消：仅 queued→cancelled（running 靠 lease 过期回收，避免强杀产生半完成副作用）；
- 背压：单轮 poll 最多认领 max_concurrent 个 job；
- 红线：崩溃恢复不重复完成/计量——每次执行有 attempt 记账，终态只写一次。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .data.store import PlatformStore
from .jobs import JobTransitionError, transition


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkerError(Exception):
    """Worker 域错误（未知 kind、非法取消等）。"""


class RecoverableJobWorker:
    def __init__(
        self,
        store: PlatformStore,
        handlers: Mapping[str, Callable[[dict[str, Any]], dict[str, Any]]],
        *,
        max_concurrent: int = 2,
        lease_seconds: int = 300,
        worker_id: str | None = None,
    ) -> None:
        self._store = store
        self._handlers = dict(handlers)
        self._max_concurrent = max_concurrent
        self._lease_seconds = lease_seconds
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"

    # ---------- 提交 ----------

    def submit(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        max_attempts: int = 3,
    ) -> str:
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        self._store.create_job(
            job_id=job_id, kind=kind, payload=payload, max_attempts=max_attempts
        )
        return job_id

    # ---------- 执行 ----------

    def poll(self) -> list[dict[str, Any]]:
        """先回收过期 lease（崩溃恢复），再按背压上限认领执行。

        本轮 requeue 的 job 不在同轮内重新认领（退让给下一轮/其他 worker，
        避免故障 job 在单轮内自循环耗尽重试）。
        """
        self.reclaim_expired_leases()
        processed: list[dict[str, Any]] = []
        requeued_now: set[str] = set()
        slots = self._max_concurrent
        while slots > 0:
            job = self._store.claim_next_job(
                worker_id=self.worker_id, lease_seconds=self._lease_seconds,
                exclude_job_ids=requeued_now,
            )
            if job is None:
                break
            outcome = self._execute(job)
            processed.append(outcome)
            if outcome["status"] == "requeued":
                requeued_now.add(job["job_id"])
            slots -= 1
        return processed

    def _execute(self, job: dict[str, Any]) -> dict[str, Any]:
        job_id = job["job_id"]
        attempt_no = self._store.increment_attempt(job_id)
        handler = self._handlers.get(job["kind"])
        ctx = {
            "job_id": job_id,
            "kind": job["kind"],
            "attempt_no": attempt_no,
            "payload": json.loads(job["payload_json"] or "{}"),
        }
        try:
            if handler is None:
                raise WorkerError(f"未注册 handler: {job['kind']}")
            result = handler(ctx)
            self._store.set_job_status(job_id, "succeeded", result_payload=result or {})
            self._store.clear_lease(job_id)
            self._store.record_attempt(
                job_id, attempt_no=attempt_no, status="succeeded",
                detail={"worker": self.worker_id},
            )
            return {"job_id": job_id, "status": "succeeded", "attempt_no": attempt_no}
        except Exception as e:  # noqa: BLE001 —— job 边界必须捕获一切
            exhausted = attempt_no >= int(job["max_attempts"])
            if exhausted:
                transition("running", "failed")
                self._store.set_job_status(
                    job_id, "failed", error=f"dead_letter: {e}"
                )
                self._store.record_attempt(
                    job_id, attempt_no=attempt_no, status="failed",
                    detail={"worker": self.worker_id, "dead_letter": True,
                            "error": str(e)},
                )
                return {"job_id": job_id, "status": "dead_letter",
                        "attempt_no": attempt_no}
            # 可重试：running→failed→queued（状态机显式转移）
            transition("running", "failed")
            self._store.set_job_status(job_id, "failed", error=str(e))
            transition("failed", "queued")
            self._store.set_job_status(job_id, "queued")
            self._store.clear_lease(job_id)
            self._store.record_attempt(
                job_id, attempt_no=attempt_no, status="failed",
                detail={"worker": self.worker_id, "error": str(e)},
            )
            return {"job_id": job_id, "status": "requeued", "attempt_no": attempt_no}

    # ---------- 崩溃恢复 ----------

    def reclaim_expired_leases(self) -> list[str]:
        """lease 过期的 running job：有余量 → 重新排队；耗尽 → dead-letter。"""
        recovered: list[str] = []
        for job in self._store.expired_running_leases(before_ts=_utcnow()):
            job_id = job["job_id"]
            if int(job["attempt_count"]) >= int(job["max_attempts"]):
                self._store.set_job_status(
                    job_id, "failed", error="dead_letter: lease 过期且重试耗尽"
                )
                continue
            transition("running", "failed")
            self._store.set_job_status(job_id, "failed", error="lease_expired")
            transition("failed", "queued")
            self._store.set_job_status(job_id, "queued")
            self._store.clear_lease(job_id)
            recovered.append(job_id)
        return recovered

    # ---------- 取消 ----------

    def cancel(self, job_id: str, *, actor: str) -> bool:
        job = self._store.get_job(job_id)
        try:
            transition(job["status"], "cancelled")
        except JobTransitionError:
            return False
        self._store.set_job_status(job_id, "cancelled", error=f"cancelled_by:{actor}")
        self._store.append_audit(
            actor=actor, action="job.cancel",
            subject_type="job", subject_id=job_id,
        )
        return True

    # ---------- 观测 ----------

    def stats(self) -> dict[str, Any]:
        counts = self._store.count_jobs_by_status()
        dead = self._store.list_jobs(status="failed", limit=1000)
        return {
            **counts,
            "dead_letters": sum(
                1 for j in dead if (j.get("error") or "").startswith("dead_letter:")
            ),
            "worker_id": self.worker_id,
            "max_concurrent": self._max_concurrent,
            "lease_seconds": self._lease_seconds,
        }
