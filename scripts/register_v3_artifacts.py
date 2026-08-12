#!/usr/bin/env python3
"""ABOSV3 T8：登记 V3 相关制品到 Artifact Registry（幂等）。

- prod_v4_best_r1_bundle：V4 best detector bundle（初始
  SHADOW_PENDING_SWITCH；切换服务在验证后置 CANDIDATE）；
- classifier_base_9295：实验分类器（必须与 detector 组合）。

用法：python scripts/register_v3_artifacts.py
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    from src.platform.data.store import PlatformStore
    from src.platform.reconciliation import ReconciliationService
    store = PlatformStore(ROOT / ".platform" / "platform.sqlite")
    svc = ReconciliationService(store)

    bundle_dir = ROOT / ".models" / "bundles" / "prod_v4_best_r1"
    det = bundle_dir / "detector.pt"
    if not det.exists():
        print("[ERROR] 先运行 scripts/build_v4_best_bundle.py")
        return 1
    rows = {r["artifact_id"] for r in store._conn.execute(
        "SELECT artifact_id FROM model_artifact_registry_v1").fetchall()}

    if "prod_v4_best_r1_bundle" not in rows:
        svc.register_artifact(
            artifact_id="prod_v4_best_r1_bundle", kind="detector_bundle",
            path=str(det), sha256=sha(det),
            dataset_manifest_sha="batch1_val294_v4",
            source_commit="abos-v3-T8", dirty_diff_hash="",
            model_base="yolo-sku-v4", label_source="kb_auto+human",
            evidence_level="shadow_pending",
            candidate_status="SHADOW_PENDING_SWITCH",
            blocker="待 shadow/回滚验证后由平台切换启用",
            actor="abos-v3-script", run_id="v3-register")
        print("[OK] 登记 prod_v4_best_r1_bundle（SHADOW_PENDING_SWITCH）")
    else:
        print("[SKIP] prod_v4_best_r1_bundle 已存在")

    clf = ROOT / "best" / "classifier_base_9295.pth"
    if "classifier_base_9295" not in rows and clf.exists():
        svc.register_artifact(
            artifact_id="classifier_base_9295", kind="classifier",
            path=str(clf), sha256=sha(clf),
            dataset_manifest_sha="classifier_base",
            source_commit="legacy-best", dirty_diff_hash="",
            model_base="resnet-classifier", label_source="kb_auto+human",
            evidence_level="experimental",
            candidate_status="EXPERIMENTAL_CLASSIFIER_REQUIRES_DETECTOR",
            blocker="分类器不可单独处理原图：必须与 detector 组合",
            actor="abos-v3-script", run_id="v3-register")
        print("[OK] 登记 classifier_base_9295（实验，需 detector 组合）")
    else:
        print("[SKIP] classifier_base_9295 已存在或缺文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
