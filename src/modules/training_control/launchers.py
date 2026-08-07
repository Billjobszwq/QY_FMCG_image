"""N2 Task 8：四 Lane 真实 launcher（冻结 hash/白名单/租约/safe-stop）。

红线：
- launch 前重跑真实 G0（注入仅限测试）；
- 输出目录存在拒绝；新 attempt 新目录；
- heavy lease：MPS 系 detector/classifier/segmenter，MLX 系 vlm 独占；
- safe-stop 必须有进程退出证据才能写终态（禁伪 cancelled）；
- 训练进程 stdout/stderr 落日志文件（ResourceRef），事件进 DB。
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cycle import TrainingCycleService

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class LauncherError(RuntimeError):
    """Launcher 错误（fail-closed）。"""


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaseLauncher:
    lane = ""
    allowed_flags: tuple[str, ...] = ()
    lease_resource = "mps"
    python: list[str] = [sys.executable]

    def __init__(self, store: Any, *, hardware_gate: Any = None,
                 venv_probe: Any = None) -> None:
        self.store = store
        self.svc = TrainingCycleService(store)
        self._hardware_gate = hardware_gate
        self._venv_probe = venv_probe
        self._procs: dict[str, subprocess.Popen] = {}

    # ---- prepare（冻结 + 校验，不启动进程） ----

    def _validate_args(self, args: list[str]) -> None:
        for a in args:
            if a.startswith("--") and a not in self.allowed_flags:
                raise LauncherError(
                    f"{self.lane} 参数白名单拒绝: {a}")

    def _env_probe(self) -> None:
        if self._venv_probe is not None and not self._venv_probe():
            raise LauncherError(f"{self.lane} 隔离环境不可用（fail-closed）")

    def build_command(self, *, run_name: str, args: list[str],
                      dataset_dir: Path, output_dir: Path) -> list[str]:
        raise NotImplementedError

    def prepare(self, plan_id: str, *, run_name: str, args: list[str],
                output_root: Path, dataset_dir: Path,
                dry_run_cmd: list[str] | None = None) -> dict[str, Any]:
        plan = self.svc.get_plan(plan_id)
        self._validate_args(args)
        self._env_probe()
        output_dir = Path(output_root) / "runs" / run_name
        if output_dir.exists():
            raise LauncherError(f"输出目录已存在，拒绝覆盖: {output_dir}")
        command = dry_run_cmd or self.build_command(
            run_name=run_name, args=args, dataset_dir=Path(dataset_dir),
            output_dir=output_dir)
        env = {k: os.environ.get(k, "") for k in
               ("PATH", "PYTHONPATH", "PYTORCH_ENABLE_MPS_FALLBACK")}
        frozen = {
            "command": command,
            "command_hash": _hash(json.dumps(command)),
            "env_hash": _hash(json.dumps(env, sort_keys=True)),
            "config_hash": _hash(json.dumps(
                {"lane": self.lane, "run_name": run_name,
                 "plan": plan_id})),
            "dataset_hash": plan["dataset_hash"],
            "base_revision": plan["base_revision"],
            "output_dir": str(output_dir),
        }
        run_id = self.svc.register_run_attempt(
            plan_id, attempt=1, command_hash=frozen["command_hash"],
            env_hash=frozen["env_hash"], output_dir=str(output_dir))
        return {"run_id": run_id, "plan_id": plan_id,
                "lane": self.lane, **frozen}

    # ---- launch（G0 重跑 + 租约 + 进程） ----

    def launch(self, prep: dict[str, Any]) -> dict[str, Any]:
        from src.modules.training_gov.mps_gate import run_mps_g0
        gate = self._hardware_gate if self._hardware_gate is not None \
            else run_mps_g0
        g0 = gate(disk_root=".")
        if not g0.get("ok"):
            raise LauncherError(
                "G0 未通过（launch 重跑），拒绝启动训练")
        try:
            self.store.acquire_resource_lease(
                run_id=prep["run_id"], resource=self.lease_resource)
        except Exception as e:
            raise LauncherError(f"资源租约获取失败: {e}") from e
        log_path = Path(prep["output_dir"]) / "run.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.svc.update_run_attempt(prep["run_id"], status="STARTING",
                                    lease_json=json.dumps(
                                        [self.lease_resource]))
        proc = subprocess.Popen(
            prep["command"], cwd=PROJECT_ROOT,
            stdout=log_path.open("ab"), stderr=subprocess.STDOUT)
        self._procs[prep["run_id"]] = proc
        self.svc.update_run_attempt(prep["run_id"], status="RUNNING",
                                    pid=proc.pid)
        self.store.append_training_event(
            prep["run_id"], "started",
            {"pid": proc.pid, "lease": self.lease_resource,
             "at": _utcnow()})
        return {"run_id": prep["run_id"], "pid": proc.pid}

    # ---- 状态收集 / safe-stop ----

    def collect_final_state(self, run_id: str) -> dict[str, Any]:
        proc = self._procs.get(run_id)
        att = self.svc.get_run_attempt(run_id)
        if proc is None:
            return att
        rc = proc.poll()
        if rc is None:
            self.svc.update_run_attempt(run_id, heartbeat_at=_utcnow())
            return att
        status = "COMPLETED" if rc == 0 else "FAILED"
        self.svc.update_run_attempt(run_id, status=status, pid=None)
        self._release(run_id)
        self.store.append_training_event(
            run_id, "completed" if rc == 0 else "failed",
            {"exit_code": rc, "at": _utcnow()})
        return self.svc.get_run_attempt(run_id)

    def request_safe_stop(self, run_id: str) -> None:
        proc = self._procs.get(run_id)
        self.svc.update_run_attempt(run_id, status="STOPPING")
        self.store.append_training_event(
            run_id, "stop_requested",
            {"reason": "safe_stop", "confirmed": False, "at": _utcnow()})
        if proc is not None and proc.poll() is None:
            proc.send_signal(signal.SIGTERM)  # 框架保存 checkpoint 后退出

    def confirm_stopped(self, run_id: str, *,
                        process_exited: bool,
                        exit_code: int | None = None) -> None:
        if not process_exited:
            raise LauncherError(
                "无进程退出证据，不得写终态（cancelled 不等于已停止）")
        self.svc.update_run_attempt(run_id, status="STOPPED", pid=None)
        self._release(run_id)
        self.store.append_training_event(
            run_id, "stopped",
            {"exit_code": exit_code, "confirmed": True, "at": _utcnow()})

    def _release(self, run_id: str) -> None:
        try:
            self.store.release_resource_lease(
                run_id=run_id, resource=self.lease_resource)
        except Exception:
            pass


class DetectorLauncher(BaseLauncher):
    lane = "detector"
    allowed_flags = ("--data-yaml", "--run-name", "--epochs", "--imgsz",
                     "--device", "--batch", "--parse-check", "--model")

    # nextgen lineage：base 只允许公开权重（禁旧业务 checkpoint）
    ALLOWED_BASES = ("yolo11n.pt", "yolov8n.pt", "yolo26m.pt")

    def build_command(self, *, run_name, args, dataset_dir, output_dir):
        if "--model" in args:
            base = args[args.index("--model") + 1]
            if base not in self.ALLOWED_BASES:
                raise LauncherError(
                    f"nextgen base 只允许公开权重: {base}")
        return [sys.executable, "-m", "src.training.train_v1",
                "--data-yaml", str(Path(dataset_dir) / "data.yaml"),
                "--run-name", run_name, *args]


class ClassifierLauncher(BaseLauncher):
    lane = "classifier"
    allowed_flags = ("--data-dir", "--classes", "--epochs", "--batch",
                     "--lr", "--device", "--output-dir", "--unknown-class")

    def build_command(self, *, run_name, args, dataset_dir, output_dir):
        return [sys.executable, "-m", "src.training.classifier.finetune",
                "--data-dir", str(dataset_dir),
                "--output-dir", str(output_dir), *args]


class SegmenterLauncher(BaseLauncher):
    """M2：轻量 YOLO-seg 学生（学审核后 SAM mask）。
    SAM 本体冻结；无 human mask gold 时仅 calibration 模式。"""
    lane = "segmenter"
    MODE_DEFAULT = "calibration"
    allowed_flags = ("--mode", "--data-yaml", "--run-name", "--epochs",
                     "--imgsz", "--device", "--batch")

    def build_command(self, *, run_name, args, dataset_dir, output_dir):
        mode = self.MODE_DEFAULT
        if "--mode" in args:
            mode = args[args.index("--mode") + 1]
        if mode == "train":
            raise LauncherError(
                "segmenter train 模式需 human mask gold 门"
                "（当前仅 calibration）")
        return [sys.executable, "-m", "src.training.segmenter.calibrate",
                "--data-yaml", str(Path(dataset_dir) / "data.yaml"),
                "--run-name", run_name,
                *[a for i, a in enumerate(args)
                  if a != "--mode" and (i == 0 or args[i-1] != "--mode")]]


class VlmLauncher(BaseLauncher):
    """M4：qwen3-vl:4b MLX QLoRA。独占 MLX lease；隔离 venv。"""
    lane = "vlm"
    lease_resource = "mlx"
    allowed_flags = ("--model", "--data", "--train", "--iters",
                     "--batch-size", "--grad-checkpoint", "--lora-rank",
                     "--lora-alpha", "--learning-rate", "--adapter-path",
                     "--steps-per-report", "--steps-per-eval",
                     "--max-seq-length")

    def __init__(self, store, *, hardware_gate=None, venv_probe=None):
        super().__init__(store, hardware_gate=hardware_gate,
                         venv_probe=venv_probe)
        self._default_probe = venv_probe

    def _env_probe(self) -> None:
        probe = self._venv_probe or (
            lambda: (PROJECT_ROOT / ".venv_mlx_vlm").is_dir())
        if not probe():
            raise LauncherError("vlm 隔离环境 .venv_mlx_vlm 不可用")

    def build_command(self, *, run_name, args, dataset_dir, output_dir):
        venv_py = PROJECT_ROOT / ".venv_mlx_vlm/bin/python"
        return [str(venv_py), "-m", "mlx_vlm.train",
                "--data", str(dataset_dir),
                "--adapter-path", str(output_dir), *args]
