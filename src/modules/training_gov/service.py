"""M5 训练治理服务：无授权不消耗算力；训练与发布两个独立审批。

红线：
- 训练启动需显式授权（platform_flag.training_authorized=true 且 IAM admin）；
- 平台第一阶段不执行训练，只产出 dry-run 计划与授权后命令；
- 发布独立审批，禁 auto_switch；candidate 才可发布。
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.eval.truebox_eval import evaluate_truebox
from src.platform.iam import can as iam_can


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
    """基于 truebox_eval 报告的真实 FP/photo 晋级门。

    不得使用 retrieval TopK 等代理指标。
    """
    recall = eval_report.get("recall_at_fp", {}).get("iou_0.50", {})
    n_images = int(eval_report.get("n_images", 0))
    n_bg = int(eval_report.get("n_background_fp", 0))
    fp_photo = (n_bg / n_images) if n_images else float("inf")
    checks = [
        {"name": "recall@FP1(IoU0.5)", "value": recall.get(1, 0.0),
         "threshold": min_recall_fp1_iou05, "op": ">=",
         "ok": recall.get(1, 0.0) >= min_recall_fp1_iou05},
        {"name": "recall@FP3(IoU0.5)", "value": recall.get(3, 0.0),
         "threshold": min_recall_fp3_iou05, "op": ">=",
         "ok": recall.get(3, 0.0) >= min_recall_fp3_iou05},
        {"name": "FP/photo(background)", "value": fp_photo,
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

    def list_snapshots(self) -> list[dict[str, Any]]:
        return self.store.list_dataset_snapshots()

    # ----- gates -----

    def gates(self) -> dict[str, Any]:
        authorized = self.store.get_flag("training_authorized") == "true"
        snaps = [s for s in self.store.list_dataset_snapshots()
                 if s["status"] == "registered"]
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
        imgsz: int = 1280,
        device: str = "mps",
        budget_minutes: int = 60,
        stop_lines: list[str] | None = None,
    ) -> dict[str, Any]:
        snap = self.store.get_dataset_snapshot(snapshot_id)
        if snap is None or snap["status"] != "registered":
            raise TrainingGovError(f"snapshot 不可用: {snapshot_id}")
        stop = stop_lines or [
            "val_recall@FP3 连续 2 epoch 无提升即停",
            "FP/photo > 1.0 即停",
            f"wall-clock > {budget_minutes}min 即停",
        ]
        mps_g0 = sys.platform == "darwin"
        command = [
            "python3", "-m", "src.training.train_v1",
            "--dataset", f"{snap['name']}@{snap['version']}",
            "--epochs", str(epochs), "--imgsz", str(imgsz),
            "--device", device, "--budget-minutes", str(budget_minutes),
        ]
        run = {
            "run_id": uuid.uuid4().hex,
            "snapshot_id": snapshot_id,
            "kind": "dry_run",
            "plan_json": json.dumps({
                "epochs": epochs, "imgsz": imgsz, "device": device,
                "mps_g0": mps_g0, "manifest_hash": snap["manifest_hash"],
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
        if self.store.get_flag("training_authorized") != "true":
            raise AuthorizationRequired(
                "training_authorized=false：训练启动需显式人工授权")
        if not iam_can(role, "training.approve"):
            raise AuthorizationRequired(f"角色 {role} 无 training.approve 权限")
        return self.store.update_training_run(
            run_id, kind="authorized", status="authorized", approved_by=actor)

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
