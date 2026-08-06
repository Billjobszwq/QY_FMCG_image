"""VLM-003：通用 hot/warm/cold 模型驻留管理器（ModelResidencyManager）。

设计要点（规格 2026-08-06）：
- 状态机：cold → loading → hot → unloading → cold；加载失败进入 failed（熔断，
  不再自动重试，需人工/治理流程介入）。
- 租约（lease）：acquire 返回带 run_id/attempt_id/deadline 的租约；
  max_concurrency 控制并发（qwen3-vl:4b 初期固定为 1，sleeping guardian）。
- 过期租约必须由显式 `reap_expired()` 回收，不自动清理（fail-closed：
  过期但未 reap 的租约仍占用并发名额，防止崩溃进程的资源被双重占用）。
- TTL 卸载：hot 且空闲超过 idle_ttl_s 的 warm/cold 模型回落到 cold；
  residency=hot 的模型永不自动卸载。
- 所有 register/load/acquire/release/unload/reap 均写 audit_event。
- 进程重启后：构造时 recover=True 将残留 loading 状态恢复为 cold。

本模块不含任何领域模型名称（YOLO/SAM/Qwen 均由 Domain Pack 经组合根注册）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from src.platform.data.store import PlatformStore

RESIDENCIES = ("hot", "warm", "cold")
STATES = ("cold", "loading", "hot", "unloading", "failed")


class ModelRuntimeError(Exception):
    """驻留管理器域错误（未注册、非法状态、加载失败、非法租约）。"""


class ModelBusy(ModelRuntimeError):
    """并发名额已满（fail-closed：排队或升级档位，不得并发超限）。"""


@dataclass(frozen=True)
class Lease:
    lease_id: str
    model_id: str
    run_id: str
    attempt_id: str | None
    deadline: str | None
    created_at: str


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


class ModelResidencyManager:
    """SQLite 持久化的驻留状态机；线程安全依赖 store 的 WAL + autocommit。"""

    def __init__(
        self,
        store: PlatformStore,
        *,
        now: Callable[[], str] | None = None,
        loader: Callable[[str], None] | None = None,
        recover: bool = False,
        actor: str = "model_residency",
    ) -> None:
        self._store = store
        self._now = now or (lambda: datetime.now(timezone.utc).isoformat())
        self._loader = loader
        self._actor = actor
        if recover:
            self._recover()

    # ---------- 注册 ----------

    def register(
        self,
        model_id: str,
        *,
        residency: str,
        max_concurrency: int,
        idle_ttl_s: int,
    ) -> None:
        if residency not in RESIDENCIES:
            raise ModelRuntimeError(f"非法 residency: {residency}（应为 hot/warm/cold）")
        if max_concurrency < 1:
            raise ModelRuntimeError("max_concurrency 必须 >= 1")
        now = self._now()
        initial_state = "hot" if residency == "hot" else "cold"
        try:
            self._store._conn.execute(
                "INSERT INTO model_residency(model_id, residency, state,"
                " max_concurrency, idle_ttl_s, last_used_at, registered_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    model_id, residency, initial_state, max_concurrency,
                    idle_ttl_s, now if initial_state == "hot" else None, now, now,
                ),
            )
        except Exception as e:  # sqlite3.IntegrityError 等
            raise ModelRuntimeError(f"model 已注册: {model_id}") from e
        self._audit("residency.register", model_id, {
            "residency": residency, "max_concurrency": max_concurrency,
            "idle_ttl_s": idle_ttl_s, "initial_state": initial_state,
        })

    # ---------- 状态查询 ----------

    def state(self, model_id: str) -> dict[str, Any]:
        row = self._model_row(model_id)
        leases = self._active_lease_rows(model_id)
        return {
            "model_id": model_id,
            "residency": row["residency"],
            "state": row["state"],
            "max_concurrency": row["max_concurrency"],
            "idle_ttl_s": row["idle_ttl_s"],
            "last_used_at": row["last_used_at"],
            "active_leases": len(leases),
            "leases": [
                {
                    "lease_id": l["lease_id"],
                    "run_id": l["run_id"],
                    "attempt_id": l["attempt_id"],
                    "deadline": l["deadline"],
                    "created_at": l["created_at"],
                }
                for l in leases
            ],
        }

    def models(self) -> list[dict[str, Any]]:
        rows = self._store._conn.execute(
            "SELECT model_id FROM model_residency ORDER BY registered_at"
        ).fetchall()
        return [self.state(r["model_id"]) for r in rows]

    # ---------- 租约 ----------

    def acquire(
        self,
        model_id: str,
        *,
        run_id: str,
        attempt_id: str | None = None,
        lease_ttl_s: float | None = None,
    ) -> Lease:
        row = self._model_row(model_id)
        state = row["state"]
        if state == "failed":
            raise ModelRuntimeError(
                f"model 处于 failed 状态，拒绝获取（需治理流程恢复）: {model_id}"
            )
        if state == "cold":
            self._load(model_id)
        elif state == "loading" or state == "unloading":
            raise ModelBusy(f"model 正在 {state}，暂时不可用: {model_id}")

        # fail-closed：过期但未 reap 的租约仍占用名额
        active = self._active_lease_rows(model_id)
        if len(active) >= row["max_concurrency"]:
            raise ModelBusy(
                f"model 并发已满（{len(active)}/{row['max_concurrency']}）: {model_id}"
            )

        now = self._now()
        lease_id = f"lease-{uuid.uuid4().hex[:16]}"
        deadline = None
        if lease_ttl_s is not None:
            deadline = (_parse_ts(now) + timedelta(seconds=lease_ttl_s)).isoformat()
        self._store._conn.execute(
            "INSERT INTO model_lease(lease_id, model_id, run_id, attempt_id,"
            " deadline, created_at) VALUES (?,?,?,?,?,?)",
            (lease_id, model_id, run_id, attempt_id, deadline, now),
        )
        self._store._conn.execute(
            "UPDATE model_residency SET last_used_at=?, updated_at=? WHERE model_id=?",
            (now, now, model_id),
        )
        self._audit("residency.acquire", model_id, {
            "lease_id": lease_id, "run_id": run_id,
            "attempt_id": attempt_id, "deadline": deadline,
        })
        return Lease(
            lease_id=lease_id, model_id=model_id, run_id=run_id,
            attempt_id=attempt_id, deadline=deadline, created_at=now,
        )

    def release(self, lease_id: str) -> None:
        row = self._store._conn.execute(
            "SELECT * FROM model_lease WHERE lease_id=?", (lease_id,)
        ).fetchone()
        if row is None:
            raise ModelRuntimeError(f"租约不存在: {lease_id}")
        if row["released_at"] is not None:
            raise ModelRuntimeError(f"租约已释放: {lease_id}")
        now = self._now()
        self._store._conn.execute(
            "UPDATE model_lease SET released_at=? WHERE lease_id=?", (now, lease_id)
        )
        self._store._conn.execute(
            "UPDATE model_residency SET last_used_at=?, updated_at=? WHERE model_id=?",
            (now, now, row["model_id"]),
        )
        self._audit("residency.release", row["model_id"], {
            "lease_id": lease_id, "run_id": row["run_id"],
        })

    def reap_expired(self) -> list[str]:
        """显式回收过期租约（崩溃进程占用的资源不得永久保留）。"""
        now = self._now()
        rows = self._store._conn.execute(
            "SELECT lease_id, model_id, run_id FROM model_lease"
            " WHERE released_at IS NULL AND deadline IS NOT NULL AND deadline < ?",
            (now,),
        ).fetchall()
        reaped: list[str] = []
        for r in rows:
            self._store._conn.execute(
                "UPDATE model_lease SET released_at=? WHERE lease_id=?",
                (now, r["lease_id"]),
            )
            self._audit("residency.reap", r["model_id"], {
                "lease_id": r["lease_id"], "run_id": r["run_id"],
            })
            reaped.append(r["lease_id"])
        return reaped

    # ---------- TTL 卸载 ----------

    def unload_idle(self) -> list[str]:
        """将空闲超过 TTL 的 hot 状态模型回落到 cold。

        residency=hot 的模型永不自动卸载；busy 模型不卸载。
        """
        now = _parse_ts(self._now())
        unloaded: list[str] = []
        rows = self._store._conn.execute(
            "SELECT * FROM model_residency WHERE state='hot' AND residency != 'hot'"
        ).fetchall()
        for row in rows:
            if self._active_lease_rows(row["model_id"]):
                continue
            if row["last_used_at"] is None:
                continue
            idle = (now - _parse_ts(row["last_used_at"])).total_seconds()
            if idle <= row["idle_ttl_s"]:
                continue
            self._store._conn.execute(
                "UPDATE model_residency SET state='cold', updated_at=? WHERE model_id=?",
                (now.isoformat(), row["model_id"]),
            )
            self._audit("residency.unload", row["model_id"], {
                "idle_seconds": idle, "ttl": row["idle_ttl_s"],
            })
            unloaded.append(row["model_id"])
        return sorted(unloaded)

    # ---------- 内部 ----------

    def _load(self, model_id: str) -> None:
        """cold → loading → hot；加载失败进入 failed（熔断，不自动重试）。"""
        now = self._now()
        self._store._conn.execute(
            "UPDATE model_residency SET state='loading', updated_at=? WHERE model_id=?",
            (now, model_id),
        )
        if self._loader is not None:
            try:
                self._loader(model_id)
            except Exception as e:
                self._store._conn.execute(
                    "UPDATE model_residency SET state='failed', updated_at=?"
                    " WHERE model_id=?",
                    (self._now(), model_id),
                )
                self._audit("residency.load_failed", model_id, {"error": str(e)})
                raise ModelRuntimeError(f"model 加载失败: {model_id}: {e}") from e
        self._store._conn.execute(
            "UPDATE model_residency SET state='hot', last_used_at=?, updated_at=?"
            " WHERE model_id=?",
            (self._now(), self._now(), model_id),
        )
        self._audit("residency.load", model_id, {})

    def _recover(self) -> None:
        """进程崩溃恢复：残留 loading 状态回落到 cold（显式，不静默）。"""
        rows = self._store._conn.execute(
            "SELECT model_id FROM model_residency WHERE state='loading'"
        ).fetchall()
        now = self._now()
        for r in rows:
            self._store._conn.execute(
                "UPDATE model_residency SET state='cold', updated_at=? WHERE model_id=?",
                (now, r["model_id"]),
            )
            self._audit("residency.recover", r["model_id"], {"from": "loading"})

    def _model_row(self, model_id: str):
        row = self._store._conn.execute(
            "SELECT * FROM model_residency WHERE model_id=?", (model_id,)
        ).fetchone()
        if row is None:
            raise ModelRuntimeError(f"model 未注册: {model_id}")
        return row

    def _active_lease_rows(self, model_id: str):
        return self._store._conn.execute(
            "SELECT * FROM model_lease WHERE model_id=? AND released_at IS NULL"
            " ORDER BY created_at",
            (model_id,),
        ).fetchall()

    def _audit(self, action: str, model_id: str, detail: dict[str, Any]) -> None:
        self._store.append_audit(
            actor=self._actor, action=action,
            subject_type="model_residency", subject_id=model_id, detail=detail,
        )
