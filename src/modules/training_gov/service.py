"""M5 训练治理服务：无授权不消耗算力；训练与发布两个独立审批。

红线：
- 训练启动需显式授权（platform_flag.training_authorized=true 且 IAM admin）；
- 平台第一阶段不执行训练，只产出 dry-run 计划与授权后命令；
- 发布独立审批，禁 auto_switch；candidate 才可发布。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.eval.truebox_eval import evaluate_truebox
from src.platform.iam import can as iam_can
from src.training.vlm.train import (
    AUTH_CODES,
    DEFAULT_BASE_MODEL,
    VlmPlanError,
    plan_vlm,
)

from .mps_gate import run_mps_g0

from .builder import BUILDER_VERSION, validate_and_stage


class TrainingGovError(Exception):
    """训练治理错误基类。"""


class AuthorizationRequired(TrainingGovError):
    """需要显式人工授权。"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_hash(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


# ---------- split guard ----------

def split_guard(manifest: dict[str, Any]) -> dict[str, Any]:
    """train/val 五键守卫（sha256/store/session 交集检测，fail-closed）。

    manifest: {"train": [{"sha256","store","session"}...], "val": [...]}
    """
    train = manifest.get("train", [])
    val = manifest.get("val", [])
    violations: list[dict[str, Any]] = []
    for key in ("sha256", "store", "session"):
        t = {x.get(key) for x in train if x.get(key)}
        v = {x.get(key) for x in val if x.get(key)}
        overlap = sorted(t & v)
        if overlap:
            violations.append({"key": key, "overlap": overlap})
    if not train or not val:
        violations.append({"key": "empty_split",
                           "overlap": ["train" if not train else "val"]})
    return {"ok": not violations, "violations": violations,
            "train_size": len(train), "val_size": len(val)}


# ---------- 晋级门（truebox FP/photo，禁 TopK） ----------

def promotion_gate(
    eval_report: dict[str, Any],
    *,
    min_recall_fp1_iou05: float = 0.6,
    min_recall_fp3_iou05: float = 0.8,
    max_fp_per_photo: float = 1.0,
) -> dict[str, Any]:
    """基于 truebox_eval 报告的真实 total FP/photo 晋级门。

    不得使用 retrieval TopK 等代理指标；FP 必须为 total FP
    （重复框+定位错误+背景误检），不得只数背景误检。
    """
    recall = eval_report.get("recall_at_fp", {}).get("iou_0.50", {})
    n_images = int(eval_report.get("n_images", 0))
    if "total_fp" in eval_report:  # truebox_eval_v2：total FP 守恒口径
        fp_photo = float(eval_report["total_fp"]) / n_images if n_images \
            else float("inf")
        fp_label = "FP/photo(total)"
    else:  # 旧 v1 报告：仅背景误检，明示降级口径
        fp_photo = (int(eval_report.get("n_background_fp", 0)) / n_images) \
            if n_images else float("inf")
        fp_label = "FP/photo(background-only, legacy v1)"
    checks = [
        {"name": "recall@FP1(IoU0.5)", "value": recall.get(1, 0.0),
         "threshold": min_recall_fp1_iou05, "op": ">=",
         "ok": recall.get(1, 0.0) >= min_recall_fp1_iou05},
        {"name": "recall@FP3(IoU0.5)", "value": recall.get(3, 0.0),
         "threshold": min_recall_fp3_iou05, "op": ">=",
         "ok": recall.get(3, 0.0) >= min_recall_fp3_iou05},
        {"name": fp_label, "value": fp_photo,
         "threshold": max_fp_per_photo, "op": "<=",
         "ok": fp_photo <= max_fp_per_photo},
    ]
    return {"pass": all(c["ok"] for c in checks), "checks": checks,
            "eval_version": eval_report.get("eval_version")}


# ---------- 统一推理导出 / 统一评估 ----------

def export_inference_manifest(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """E0/P0/P1 统一推理导出 manifest：逐文件 sha256，缺失即 fail-closed。"""
    out = []
    for e in entries:
        p = Path(e["path"])
        if not p.exists():
            raise TrainingGovError(f"推理制品缺失: {p}")
        data = p.read_bytes()
        out.append({
            "stage": e["stage"], "name": e["name"], "path": str(p),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        })
    return {"manifest_version": "inference_manifest_v1",
            "entries": out, "exported_at": _utcnow(),
            "manifest_hash": _canonical_hash(out)}


def unified_eval(
    images: list[dict[str, Any]],
    predictors: dict[str, Callable[[dict[str, Any]], list[dict[str, Any]]]],
) -> dict[str, Any]:
    """同一 GT 上对 E0/P0/P1（任意 predictor）做 truebox 统一评估。"""
    reports: dict[str, Any] = {}
    for name, fn in predictors.items():
        prepared = [{"gt": img["gt"], "preds": fn(img)} for img in images]
        reports[name] = evaluate_truebox(prepared)
    return {"eval_version": "unified_truebox_v1", "predictors": reports}


# ---------- 治理服务 ----------

class TrainingGovernanceService:
    def __init__(self, store: Any, *, hardware_gate: Any = None) -> None:
        self.store = store
        # GLTC D4：HardwareGateProvider 可注入（测试 hermetic）；
        # 未注入时默认真实 run_mps_g0（晚绑定，保留 monkeypatch 语义）。
        # mock 只允许在测试注入，不得进入真实 launch 路径。
        self._hardware_gate = hardware_gate

    def _resolve_gate(self) -> Any:
        return self._hardware_gate if self._hardware_gate is not None \
            else run_mps_g0

    def _require_active_run(self, run_id: str) -> None:
        """GLTC D2：被追加式标记 legacy/superseded 的 run 禁止一切
        批准/启动/入队；历史行保留作证据。"""
        if self.store.is_training_run_superseded(run_id):
            raise TrainingGovError(
                f"训练计划已被标记 legacy/superseded（non_executable），"
                f"禁止批准或入队: {run_id}")

    # ----- dataset snapshot -----

    def register_snapshot(
        self,
        name: str,
        version: str,
        mode: str,
        manifest: dict[str, Any],
        *,
        source_actor: str,
        source_conclusion: str,
        quality: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        guard = split_guard(manifest)
        if not guard["ok"]:
            raise TrainingGovError(
                f"split guard 未通过: {guard['violations']}"
            )
        snapshot = {
            "snapshot_id": uuid.uuid4().hex,
            "name": name,
            "version": version,
            "mode": mode,
            "manifest_hash": _canonical_hash(manifest),
            "manifest_json": json.dumps(manifest, ensure_ascii=False),
            "guard_json": json.dumps(guard, ensure_ascii=False),
            "source_actor": source_actor,
            "source_conclusion": source_conclusion,
            "quality_json": json.dumps(quality or {}, ensure_ascii=False),
            "status": "registered",
            "created_at": _utcnow(),
        }
        self.store.create_dataset_snapshot(snapshot)
        return snapshot

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        return self.store.get_dataset_snapshot(snapshot_id)

    def build_and_register_snapshot(
        self,
        name: str,
        version: str,
        mode: str,
        entries: list[dict[str, Any]],
        *,
        actor: str,
        datasets_root: Path,
        protocol_dir: Path | None = None,
    ) -> dict[str, Any]:
        """UMT-003：服务端 builder 生成真实 Snapshot（拒绝自由 JSON）。

        manifest 由逐文件校验结果推导，不接受客户端提交的 manifest；
        审核结论为结构化 builder 记录，不接受自由文本。
        """
        dest = Path(datasets_root) / f"{name}_{version}"
        try:
            manifest, report = validate_and_stage(
                entries, dest, mode=mode, protocol_dir=protocol_dir)
        except (ValueError, RuntimeError) as e:
            raise TrainingGovError(f"Snapshot builder 拒绝: {e}") from e
        conclusion = (
            f"{BUILDER_VERSION}: 逐文件校验通过"
            f"（train={report['train_size']}, val={report['val_size']},"
            f" mode={mode}）")
        snap = self.register_snapshot(
            name, version, mode, manifest,
            source_actor=f"{actor}:{BUILDER_VERSION}",
            source_conclusion=conclusion,
            quality=report,
        )
        self.store.append_audit(
            actor=actor, action="snapshot.build",
            subject_type="dataset_snapshot", subject_id=snap["snapshot_id"],
            detail={"name": name, "version": version,
                    "manifest_hash": snap["manifest_hash"],
                    "dest": report["dest"]})
        return {"snapshot": self.store.get_dataset_snapshot(
            snap["snapshot_id"]), "report": report}

    def list_snapshots(self) -> list[dict[str, Any]]:
        return self.store.list_dataset_snapshots()

    def mark_snapshot_demo(self, snapshot_id: str, *, actor: str) -> dict[str, Any]:
        """将 Snapshot 标记为演示/不可训练（U0-2/UMT-004）。

        审计式纠偏：不物理删除行与 manifest，仅置 trainable=0 并留备注。
        幂等。
        """
        snap = self.store.get_dataset_snapshot(snapshot_id)
        if snap is None:
            raise KeyError(snapshot_id)
        note = (f"demo/invalid_for_training：演示数据不得用于训练"
                f"（标记人 {actor}，{_utcnow()}）")
        out = self.store.mark_dataset_snapshot_trainable(
            snapshot_id, trainable=False, note=note)
        self.store.append_audit(
            actor=actor, action="snapshot.mark_demo",
            subject_type="dataset_snapshot", subject_id=snapshot_id,
            detail={"name": snap["name"], "version": snap["version"]})
        return out

    # ----- gates -----

    def gates(self) -> dict[str, Any]:
        authorized = self.store.get_flag("training_authorized") == "true"
        snaps = [s for s in self.store.list_dataset_snapshots()
                 if s["status"] == "registered" and s.get("trainable", 1)]
        reasons: list[str] = []
        if not authorized:
            reasons.append("training_authorized=false（需显式人工授权）")
        if not snaps:
            reasons.append("无已注册 DatasetSnapshot（split guard 通过）")
        return {
            "training_authorized": authorized,
            "registered_snapshots": len(snaps),
            "reasons": reasons,
            "can_dry_run": bool(snaps),
            "can_train": authorized and bool(snaps),
        }

    def set_training_authorized(self, value: bool, *, actor: str, role: str) -> None:
        if not iam_can(role, "training.approve"):
            raise AuthorizationRequired(f"角色 {role} 无 training.approve 权限")
        self.store.set_flag("training_authorized",
                            "true" if value else "false", actor)

    # ----- dry-run / start -----

    def dry_run(
        self,
        snapshot_id: str,
        *,
        actor: str,
        epochs: int = 3,
        imgsz: int = 960,
        device: str = "mps",
        budget_minutes: int = 60,
        stop_lines: list[str] | None = None,
        extra_args: list[str] | None = None,
        data_yaml: str | None = None,
    ) -> dict[str, Any]:
        """生成训练计划：命令只允许 train_v1.py 真实参数集（UMT-002）。

        命令在入库前经真实 argparse 预检；未知参数 fail-closed。
        预算/停止线为计划元数据，不是 train_v1 CLI 参数。
        """
        snap = self.store.get_dataset_snapshot(snapshot_id)
        if snap is None or snap["status"] != "registered":
            raise TrainingGovError(f"snapshot 不可用: {snapshot_id}")
        if not snap.get("trainable", 1):
            raise TrainingGovError(
                f"snapshot 已标记不可训练（演示/无效）: {snapshot_id}"
                f"；{snap.get('status_note', '')}")
        stop = stop_lines or [
            "val_recall@FP3 连续 2 epoch 无提升即停",
            "total FP/photo > 1.0 即停",
            f"wall-clock > {budget_minutes}min 即停",
        ]
        # UMT-005：MPS G0 必须真实实测，禁止 sys.platform 假判；证据写入 run
        g0 = self._resolve_gate()(disk_root=".")
        run_name = f"{snap['name']}_{snap['version']}"
        yaml_path = data_yaml or f".datasets/{run_name}/data.yaml"
        command = [
            "python3", "-m", "src.training.train_v1",
            "--data-yaml", yaml_path,
            "--run-name", run_name,
            "--epochs", str(epochs), "--imgsz", str(imgsz),
            "--device", device, "--parse-check",
        ] + list(extra_args or [])
        # CLI 预检：用 train_v1 真实 parser 解析，未知参数即拒绝
        try:
            from src.training.train_v1 import build_arg_parser
            build_arg_parser().parse_args(command[3:])
        except SystemExit as e:
            raise TrainingGovError(
                f"dry-run 命令未通过 train_v1 CLI 预检: {command[3:]}"
            ) from e
        run = {
            "run_id": uuid.uuid4().hex,
            "snapshot_id": snapshot_id,
            "kind": "dry_run",
            "plan_json": json.dumps({
                "epochs": epochs, "imgsz": imgsz, "device": device,
                "mps_g0": g0["ok"], "mps_g0_report": g0,
                "manifest_hash": snap["manifest_hash"],
            }, ensure_ascii=False),
            "command_json": json.dumps(command, ensure_ascii=False),
            "budget_json": json.dumps({"minutes": budget_minutes},
                                      ensure_ascii=False),
            "stop_lines_json": json.dumps(stop, ensure_ascii=False),
            "status": "dry_run",
            "publish_status": "none",
            "requested_by": actor,
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
        }
        self.store.create_training_run(run)
        return run

    def start_training(self, run_id: str, *, actor: str, role: str) -> dict[str, Any]:
        """授权门：flag + IAM 双校验。平台不执行训练，仅标记 authorized 并回显命令。

        错误优先级冻结（GLTC D3）：计划有效性 → 授权 → 硬件 G0。
        """
        run = self.store.get_training_run(run_id)
        if run is None:
            raise KeyError(run_id)
        self._require_active_run(run_id)
        if self.store.get_flag("training_authorized") != "true":
            raise AuthorizationRequired(
                "training_authorized=false：训练启动需显式人工授权")
        if not iam_can(role, "training.approve"):
            raise AuthorizationRequired(f"角色 {role} 无 training.approve 权限")
        self._require_g0(run)
        return self.store.update_training_run(
            run_id, kind="authorized", status="authorized", approved_by=actor)

    # ----- UMT-007：approve_plan / enqueue_training_job 拆分 -----

    def _require_g0(self, run: dict[str, Any]) -> None:
        plan = json.loads(run.get("plan_json") or "{}")
        if not plan.get("mps_g0"):
            failed = [c["name"] for c in
                      plan.get("mps_g0_report", {}).get("checks", [])
                      if not c.get("ok")]
            raise TrainingGovError(
                f"MPS G0 未通过，训练保持禁用；失败项: {failed or '无报告'}")

    def approve_plan(self, run_id: str, *, actor: str, role: str,
                     worker: Any = None) -> dict[str, Any]:
        """批准训练计划：只落状态，绝不提交 job/消耗算力（UMT-007）。

        错误优先级冻结（GLTC D3）：计划有效性 → 授权 → 硬件 G0。
        """
        run = self.store.get_training_run(run_id)
        if run is None:
            raise KeyError(run_id)
        self._require_active_run(run_id)
        if self.store.get_flag("training_authorized") != "true":
            raise AuthorizationRequired(
                "training_authorized=false：批准训练计划需显式人工授权")
        if not iam_can(role, "training.approve"):
            raise AuthorizationRequired(f"角色 {role} 无 training.approve 权限")
        self._require_g0(run)
        out = self.store.update_training_run(
            run_id, kind="authorized", status="approved", approved_by=actor)
        self.store.append_audit(
            actor=actor, action="training.approve_plan",
            subject_type="training_run", subject_id=run_id,
            detail={"note": "批准不消耗算力；启动需另行 enqueue"})
        return out

    def enqueue_training_job(self, run_id: str, *, actor: str, role: str,
                             worker: Any) -> dict[str, Any]:
        """提交训练 Job：仅已批准计划可入队；由可恢复 Worker 执行。

        GLTC D3：launch 路径重跑真实 G0，禁止只信 dry-run 时的旧报告。
        """
        run = self.store.get_training_run(run_id)
        if run is None:
            raise KeyError(run_id)
        self._require_active_run(run_id)
        # 幂等（UMT-109）：已入队/执行中的 run 重复提交返回同一 Job
        if run.get("status") in ("queued", "running") and run.get("job_id"):
            return {**run, "job_id": run["job_id"]}
        if run.get("status") != "approved":
            raise TrainingGovError(
                f"仅已批准的训练计划可入队（当前 status={run.get('status')}）")
        if self.store.get_flag("training_authorized") != "true":
            raise AuthorizationRequired(
                "training_authorized=false：提交训练 Job 需显式人工授权")
        if not iam_can(role, "training.approve"):
            raise AuthorizationRequired(f"角色 {role} 无 training.approve 权限")
        # 重跑真实 G0（环境可能在 dry-run 后恶化）；失败即拒绝提交
        fresh = self._resolve_gate()(disk_root=".")
        if not fresh.get("ok"):
            failed = [c["name"] for c in fresh.get("checks", [])
                      if not c.get("ok")]
            raise TrainingGovError(
                f"MPS G0 未通过（launch 重跑），训练保持禁用；"
                f"失败项: {failed or '无报告'}")
        command = json.loads(run["command_json"])
        job_id = worker.submit("training.run", {
            "run_id": run_id, "command": command,
            "budget_json": json.loads(run["budget_json"]),
            "stop_lines": json.loads(run["stop_lines_json"]),
        }, max_attempts=1)
        out = self.store.update_training_run(
            run_id, kind="started", status="queued", job_id=job_id)
        self.store.append_audit(
            actor=actor, action="training.enqueue_job",
            subject_type="training_run", subject_id=run_id,
            detail={"job_id": job_id, "command": command})
        return {**out, "job_id": job_id}

    # ----- 发布（独立审批，禁 auto_switch） -----

    def request_publish(self, run_id: str, *, actor: str, role: str) -> dict[str, Any]:
        if not iam_can(role, "training.request"):
            raise AuthorizationRequired(f"角色 {role} 无 training.request 权限")
        run = self.store.get_training_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return self.store.update_training_run(
            run_id, publish_status="requested", publish_requested_by=actor)

    def approve_publish(self, run_id: str, *, actor: str, role: str) -> dict[str, Any]:
        if not iam_can(role, "model.publish.approve"):
            raise AuthorizationRequired(
                f"角色 {role} 无 model.publish.approve 权限")
        run = self.store.get_training_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run["kind"] != "completed_candidate":
            raise TrainingGovError(
                "仅 completed_candidate 可发布；训练完成只产生 candidate，不自动发布")
        return self.store.update_training_run(
            run_id, publish_status="approved", publish_approved_by=actor)

    # ----- VLM-011：Qwen3-VL QLoRA 受治理 launcher -----

    # 完成制品必须全部注册，缺一即 fail-closed
    REQUIRED_VLM_ARTIFACTS = (
        "adapter", "config", "loss", "tokens_per_second", "env_lock",
        "data_hash", "model_revision", "error_ledger",
    )

    def set_vlm_vision_authorized(self, value: bool, *, actor: str,
                                  role: str) -> None:
        """train_vision 需独立授权动作（不得与 training_authorized 合并）。"""
        if not iam_can(role, "training.approve"):
            raise AuthorizationRequired(
                f"角色 {role} 无 training.approve 权限")
        self.store.set_flag("vlm_train_vision_authorized",
                            "true" if value else "false", actor)

    def plan_vlm_training(
        self,
        *,
        actor: str,
        role: str,
        dataset_path: str,
        output_dir: str,
        snapshot: dict[str, Any] | None = None,
        preflight_report: dict[str, Any] | None = None,
        zero_shot_report: dict[str, Any] | None = None,
        benchmark_report: dict[str, Any] | None = None,
        epochs: int = 1,
        batch_size: int = 1,
        learning_rate: float = 1e-5,
        lora_rank: int = 16,
        lora_alpha: int = 32,
        gradient_accumulation_steps: int = 1,
        train_vision: bool = False,
        model_path: str = DEFAULT_BASE_MODEL,
    ) -> dict[str, Any]:
        """VLM QLoRA 计划：证据链门禁全绿才产出冻结命令（不执行训练）。

        门禁：snapshot/preflight/zero-shot/benchmark 证据、输出目录占用、
        训练冲突（存在 queued/running run）、授权（flag+IAM）、第一轮
        参数上限、train_vision 独立授权。真实执行仍被资源门禁阻断。
        kind 复用 dry_run（schema 枚举不变），以 status=vlm_dry_run 区分。
        """
        authorized = (
            self.store.get_flag("training_authorized") == "true"
            and iam_can(role, "training.approve"))
        vision_authorized = (
            self.store.get_flag("vlm_train_vision_authorized") == "true"
            and iam_can(role, "training.approve"))
        active_training = any(
            r.get("status") in ("queued", "running")
            for r in self.store.list_training_runs())
        spec = {
            "model_path": model_path, "dataset_path": dataset_path,
            "output_dir": output_dir, "epochs": epochs,
            "batch_size": batch_size, "learning_rate": learning_rate,
            "lora_rank": lora_rank, "lora_alpha": lora_alpha,
            "gradient_accumulation_steps": gradient_accumulation_steps,
            "train_vision": train_vision,
        }
        evidence = {
            "snapshot": snapshot, "preflight_report": preflight_report,
            "zero_shot_report": zero_shot_report,
            "benchmark_report": benchmark_report,
            "active_training": active_training,
            "authorized": authorized,
            "vision_authorized": vision_authorized,
        }
        try:
            plan = plan_vlm(spec, evidence)
        except VlmPlanError as e:
            if set(e.blockers) & AUTH_CODES:
                raise AuthorizationRequired(str(e)) from e
            raise TrainingGovError(str(e)) from e
        run = {
            "run_id": uuid.uuid4().hex,
            "snapshot_id": None,
            "kind": "dry_run",
            "plan_json": json.dumps({
                **plan,
                "evidence": {
                    "snapshot_manifest_sha256": snapshot.get(
                        "manifest_sha256"),
                    "train_instances": snapshot.get("train_instances"),
                    "zero_shot_coverage": zero_shot_report.get("coverage"),
                    "recommended_batch_size": benchmark_report.get(
                        "recommended_batch_size"),
                },
            }, ensure_ascii=False),
            "command_json": json.dumps(plan["command"], ensure_ascii=False),
            "budget_json": json.dumps(
                {"minutes": 0,
                 "note": "真实预算由隔离环境 benchmark 实测确定"},
                ensure_ascii=False),
            "stop_lines_json": json.dumps([
                "loss 发散即停",
                "训练冲突/温度/swap 超阈即停",
            ], ensure_ascii=False),
            "status": "vlm_dry_run",
            "publish_status": "none",
            "requested_by": actor,
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
        }
        self.store.create_training_run(run)
        self.store.append_audit(
            actor=actor, action="vlm.plan_training",
            subject_type="training_run", subject_id=run["run_id"],
            detail={"model_id": plan["model_id"],
                    "base_model": plan["base_model"],
                    "limits": plan["limits"]})
        return run

    def complete_vlm_training(self, run_id: str, *, actor: str,
                              artifacts: dict[str, Any]) -> dict[str, Any]:
        """登记 VLM 训练结果：只产生 completed_candidate，不自动发布。

        adapter/config/loss/tokens/s/env_lock/数据 hash/模型 revision/
        错误样本账本必须全部注册；发布仍需独立 admin 审批且生产切换
        默认 false。
        """
        run = self.store.get_training_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if run["status"] != "vlm_dry_run":
            raise TrainingGovError(
                f"仅 vlm_dry_run 计划可登记为 completed_candidate"
                f"（当前 status={run.get('status')}）")
        missing = [k for k in self.REQUIRED_VLM_ARTIFACTS
                   if k not in artifacts]
        if missing:
            raise TrainingGovError(f"VLM 完成制品缺失: {missing}")
        plan = json.loads(run.get("plan_json") or "{}")
        plan["artifacts"] = artifacts
        out = self.store.update_training_run(
            run_id, kind="completed_candidate",
            status="completed_candidate",
            plan_json=json.dumps(plan, ensure_ascii=False))
        self.store.append_audit(
            actor=actor, action="vlm.complete_training",
            subject_type="training_run", subject_id=run_id,
            detail={"artifacts": sorted(artifacts),
                    "note": "candidate 不自动发布"})
        return out

    # ----- 视图 -----

    def list_runs(self) -> list[dict[str, Any]]:
        return self.store.list_training_runs()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.store.get_training_run(run_id)
