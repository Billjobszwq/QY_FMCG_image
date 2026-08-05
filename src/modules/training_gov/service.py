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
    def __init__(self, store: Any) -> None:
        self.store = store

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
        g0 = run_mps_g0(disk_root=".")
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
        """授权门：flag + IAM 双校验。平台不执行训练，仅标记 authorized 并回显命令。"""
        run = self.store.get_training_run(run_id)
        if run is None:
            raise KeyError(run_id)
        self._require_g0(run)
        if self.store.get_flag("training_authorized") != "true":
            raise AuthorizationRequired(
                "training_authorized=false：训练启动需显式人工授权")
        if not iam_can(role, "training.approve"):
            raise AuthorizationRequired(f"角色 {role} 无 training.approve 权限")
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
        """批准训练计划：只落状态，绝不提交 job/消耗算力（UMT-007）。"""
        run = self.store.get_training_run(run_id)
        if run is None:
            raise KeyError(run_id)
        self._require_g0(run)
        if self.store.get_flag("training_authorized") != "true":
            raise AuthorizationRequired(
                "training_authorized=false：批准训练计划需显式人工授权")
        if not iam_can(role, "training.approve"):
            raise AuthorizationRequired(f"角色 {role} 无 training.approve 权限")
        out = self.store.update_training_run(
            run_id, kind="authorized", status="approved", approved_by=actor)
        self.store.append_audit(
            actor=actor, action="training.approve_plan",
            subject_type="training_run", subject_id=run_id,
            detail={"note": "批准不消耗算力；启动需另行 enqueue"})
        return out

    def enqueue_training_job(self, run_id: str, *, actor: str, role: str,
                             worker: Any) -> dict[str, Any]:
        """提交训练 Job：仅已批准计划可入队；由可恢复 Worker 执行。"""
        run = self.store.get_training_run(run_id)
        if run is None:
            raise KeyError(run_id)
        # 幂等（UMT-109）：已入队/执行中的 run 重复提交返回同一 Job
        if run.get("status") in ("queued", "running") and run.get("job_id"):
            return {**run, "job_id": run["job_id"]}
        if run.get("status") != "approved":
            raise TrainingGovError(
                f"仅已批准的训练计划可入队（当前 status={run.get('status')}）")
        self._require_g0(run)
        if self.store.get_flag("training_authorized") != "true":
            raise AuthorizationRequired(
                "training_authorized=false：提交训练 Job 需显式人工授权")
        if not iam_can(role, "training.approve"):
            raise AuthorizationRequired(f"角色 {role} 无 training.approve 权限")
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

    # ----- 视图 -----

    def list_runs(self) -> list[dict[str, Any]]:
        return self.store.list_training_runs()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.store.get_training_run(run_id)
