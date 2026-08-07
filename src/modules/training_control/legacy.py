"""GLTC Task 2：旧模型隔离与 Legacy Model Adapter（01 §2）。

红线：
- 只读扫描（不移动/不重命名/不删除任何 .models 文件）；
- 登记走追加式不可变账本（legacy_model_registry_v1）；
- prod_20260805_v5_r1 只作 LegacyInferenceCapability：
  识别 + assisted provisional proposal + 冻结基线评估；
  永远不是 nextgen 的 parent/resume/EMA/optimizer/teacher。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import contracts as C
from . import vocabulary as V

PRODUCTION_BUNDLE_ID = "prod_20260805_v5_r1"
_WEIGHT_SUFFIX = ".pt"


class LegacyModelError(RuntimeError):
    """旧模型治理错误（fail-closed）。"""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def classify_legacy_model(model_id: str) -> str:
    """登记状态分类（01 §2.1）。未知模型 fail-closed。"""
    if model_id == PRODUCTION_BUNDLE_ID:
        return "production_legacy"
    if model_id.startswith(("sku_v", "e2_")) or model_id in (
            "classifier", "archive", "registry"):
        # sku_v7_sam 为 experimental（治理偏差轮次，06 spec §2.2）
        if model_id == "sku_v7_sam":
            return "experimental_ended"
        return "historical"
    raise LegacyModelError(
        f"未知旧模型，拒绝自动分类（需人工裁定）: {model_id}")


def scan_model_inventory(root: Path | str) -> list[dict[str, Any]]:
    """只读扫描 .models/，生成 hash inventory。

    顶层目录 = 一个 model（bundles/ 下每个子目录 = 一个 bundle）。
    权重文件（*.pt）逐个 sha256；不移动/不修改任何文件。
    """
    root = Path(root)
    if not root.is_dir():
        raise LegacyModelError(f"模型目录不存在: {root}")
    entries: list[dict[str, Any]] = []

    def _weights_of(d: Path) -> list[dict[str, str]]:
        out = []
        for p in sorted(d.rglob(f"*{_WEIGHT_SUFFIX}")):
            if p.is_file():
                out.append({"path": str(p.relative_to(root)),
                            "sha256": _sha256_file(p),
                            "size": p.stat().st_size})
        return out

    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        if d.name == "bundles":
            for b in sorted(d.iterdir()):
                if b.is_dir():
                    entries.append({
                        "model_id": b.name,
                        "path": str(b.relative_to(root)),
                        "status": classify_legacy_model(b.name),
                        "weights": _weights_of(b)})
            continue
        if d.name == "__pycache__":
            continue
        try:
            status = classify_legacy_model(d.name)
        except LegacyModelError:
            status = "quarantined"  # 未识别目录证据保留，拒绝一切入口
        entries.append({
            "model_id": d.name,
            "path": str(d.relative_to(root)),
            "status": status,
            "weights": _weights_of(d)})
    return entries


def register_legacy_models(store: Any, inventory: list[dict[str, Any]],
                           *, git_commit: str) -> int:
    """追加式登记（幂等：已登记 model_id 不重复插入）。"""
    registered = 0
    existing = {r["model_id"] for r in store.list_legacy_models()}
    for e in inventory:
        if e["model_id"] in existing:
            continue
        store.register_legacy_model(
            model_id=e["model_id"], path=e["path"], status=e["status"],
            weights_json=json.dumps(e["weights"], ensure_ascii=False),
            git_commit=git_commit)
        registered += 1
    return registered


class LegacyInferenceCapability:
    """当前生产 bundle 的受限能力适配（01 §2.1/§5）。

    只允许：在线识别、assisted provisional proposal、冻结基线评估。
    禁止：作为 nextgen parent/resume/EMA/optimizer/teacher。
    """

    capability_id = "legacy.recognition.v2"
    proposals_are_provisional = True  # proposal 永远不等于人工真值

    def __init__(self, bundle_id: str = PRODUCTION_BUNDLE_ID) -> None:
        self.bundle_id = bundle_id
        self.allowed_uses = ("recognition", "assisted_proposal",
                             "baseline_evaluation")
        self.forbidden_uses = ("training_parent", "resume", "ema",
                               "optimizer_state", "distillation_teacher",
                               "gold_label")

    def assert_use(self, use: str) -> None:
        if use in self.forbidden_uses:
            raise LegacyModelError(
                f"production_legacy bundle 禁止用途: {use}")
        if use not in self.allowed_uses:
            raise LegacyModelError(f"未声明的用途: {use}")


def training_overview_projection(store: Any) -> dict[str, Any]:
    """统一 Web 顶部投影：production legacy 与 nextgen 四 lane 隔离。"""
    rows = store.list_legacy_models()
    prod = next((r for r in rows
                 if r["status"] == "production_legacy"), None)
    production = {
        "bundle_id": prod["model_id"] if prod else PRODUCTION_BUNDLE_ID,
        "status": "production_legacy",
        "serving": prod is not None,
        "lineage": "legacy（不参与 nextgen 训练血缘）",
    }
    nextgen = {}
    for lane in V.TRAINING_LANES:
        nextgen[lane] = {
            "lineage_family": C.LINEAGE_FAMILY,
            "runs": [],
            "latest_candidate": None,
        }
    return {"production": production, "nextgen_lanes": nextgen}
