"""GLTC Task 7：可靠训练 Worker（租约/冻结/heartbeat/safe-stop/orphan）。

红线：
- heavy accelerator lease 并发 1；MPS 与 MLX 互斥（经 store）；
- 提交时冻结 env/command/data/code/config hash；
- safe-stop 必须有 signal → checkpoint → 进程退出 → lease 释放证据，
  `cancelled` 不能代表已经杀死进程；
- orphan/崩溃恢复为 FAILED(orphaned)，不伪称 running；
- launch 前重跑真实 G0；mock 仅限测试注入。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

from src.modules.training_gov.mps_gate import run_mps_g0
from src.platform.data.store import StoreError


class WorkerError(RuntimeError):
    """Worker 错误（fail-closed）。"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_obj(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, OSError):
        return False


class ReliableWorker:
    def __init__(self, store: Any, *, hardware_gate: Any = None) -> None:
        self.store = store
        self._hardware_gate = hardware_gate  # 仅测试注入

    def _gate(self) -> Any:
        return self._hardware_gate if self._hardware_gate is not None \
            else run_mps_g0

    # ---- 提交（冻结 + 租约 + G0 重跑） ----

    def submit_run(self, run_id: str, *, lane: str, command: list[str],
                   env: dict[str, str], data_hash: str, code_hash: str,
                   config_hash: str, leases: list[str], actor: str,
                   plan_id: str = "") -> dict[str, Any]:
        # 1. launch 前重跑真实 G0（禁信旧报告）
        g0 = self._gate()(disk_root=".")
        if not g0.get("ok"):
            failed = [c["name"] for c in g0.get("checks", [])
                      if not c.get("ok")]
            raise WorkerError(
                f"MPS G0 未通过（worker 重跑），拒绝提交: {failed}")
        # 2. 租约获取（失败即回滚，不留残留）
        acquired: list[str] = []
        try:
            for res in leases:
                self.store.acquire_resource_lease(run_id=run_id,
                                                  resource=res)
                acquired.append(res)
        except StoreError as e:
            for res in acquired:
                self.store.release_resource_lease(run_id=run_id,
                                                  resource=res)
            raise WorkerError(f"资源租约冲突: {e}") from e
        # 3. 冻结 spec 并入库
        frozen = {
            "env_hash": _hash_obj(env),
            "command": list(command),
            "data_hash": data_hash,
            "code_hash": code_hash,
            "config_hash": config_hash,
        }
        self.store.create_training_run_v2(
            run_id, lane=lane, plan_id=plan_id, status="QUEUED",
            lease_json=json.dumps(leases), attempt=1)
        self.store.append_training_event(
            run_id, "lease_acquired",
            {"resources": leases, "actor": actor, "frozen": frozen})
        return {"run_id": run_id, "status": "QUEUED",
                "frozen": frozen, "leases": leases}

    # ---- 运行期 ----

    def mark_running(self, run_id: str, *, pid: int) -> None:
        self.store.update_training_run_v2(run_id, status="RUNNING",
                                          pid=pid, heartbeat_at=_utcnow())
        self.store.append_training_event(
            run_id, "started", {"pid": pid})

    def record_heartbeat(self, run_id: str) -> None:
        self.store.update_training_run_v2(run_id, heartbeat_at=_utcnow())

    # ---- 安全停止（证据链） ----

    def request_safe_stop(self, run_id: str, *, reason: str) -> None:
        run = self.store.get_training_run_v2(run_id)
        if run is None:
            raise WorkerError(f"未知 run: {run_id}")
        if run["status"] not in ("RUNNING", "STARTING"):
            raise WorkerError(
                f"仅 RUNNING/STARTING 可安全停止"
                f"（当前 {run['status']}）")
        self.store.update_training_run_v2(run_id, status="STOPPING")
        self.store.append_training_event(
            run_id, "stop_requested",
            {"reason": reason, "confirmed": False})

    def confirm_stopped(self, run_id: str, *, exit_code: int | None,
                        checkpoint_saved: bool,
                        process_exited: bool) -> None:
        """终态必须有进程退出证据；不得伪写 cancelled。"""
        if not process_exited:
            raise WorkerError(
                "无进程退出证据，不得写 STOPPED（cancelled 不等于已停止）")
        run = self.store.get_training_run_v2(run_id)
        if run is None or run["status"] != "STOPPING":
            raise WorkerError("仅 STOPPING 状态可确认停止")
        self.store.update_training_run_v2(run_id, status="STOPPED",
                                          pid=None)
        for res in json.loads(run.get("lease_json") or "[]"):
            try:
                self.store.release_resource_lease(run_id=run_id,
                                                  resource=res)
            except StoreError:
                pass
        self.store.append_training_event(
            run_id, "stopped",
            {"exit_code": exit_code,
             "checkpoint_saved": checkpoint_saved})

    # ---- orphan 恢复 ----

    def recover_orphans(self, *, stale_seconds: float = 120.0
                        ) -> list[str]:
        """进程不存在或心跳过期 → FAILED(orphaned)；释放租约。

        绝不把失联 run 伪称 running。"""
        recovered: list[str] = []
        now = datetime.now(timezone.utc)
        for run in self.store.list_training_runs_v2(
                statuses=("RUNNING", "STARTING", "STOPPING")):
            pid_alive = _pid_alive(run.get("pid"))
            stale = True
            hb = run.get("heartbeat_at")
            if hb:
                try:
                    age = (now - datetime.fromisoformat(hb)).total_seconds()
                    stale = age > stale_seconds
                except ValueError:
                    stale = True
            if pid_alive and not stale:
                continue
            self.store.update_training_run_v2(run["run_id"],
                                              status="FAILED", pid=None)
            for res in json.loads(run.get("lease_json") or "[]"):
                try:
                    self.store.release_resource_lease(
                        run_id=run["run_id"], resource=res)
                except StoreError:
                    pass
            self.store.append_training_event(
                run["run_id"], "failed",
                {"reason": "orphaned",
                 "pid_alive": pid_alive, "heartbeat_stale": stale})
            recovered.append(run["run_id"])
        return recovered
