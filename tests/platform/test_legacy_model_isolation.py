"""GLTC-002 红测试：旧模型隔离与 Legacy Model Adapter（任务书 Task 2 / 01 §2）。

要求：
- 只读扫描生成 hash inventory（不移动/不删除文件）；
- 追加式登记 production_legacy/historical/experimental_ended/quarantined；
- prod_20260805_v5_r1 = LegacyInferenceCapability（识别 + provisional proposal）；
- 旧业务权重禁作 nextgen parent/resume/EMA/optimizer/teacher；
- UI/API 投影必须视觉/语义隔离 production legacy 与 nextgen。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.modules.training_control import contracts as C
from src.modules.training_control import legacy as L
from src.modules.training_control import vocabulary as V
from src.platform.data.store import PlatformStore


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _fake_models(tmp_path: Path) -> Path:
    root = tmp_path / ".models"
    for name in ("sku_v1", "sku_v4", "sku_v7_sam", "classifier",
                 "e2_p0_coco_s42", "archive"):
        d = root / name
        d.mkdir(parents=True)
        (d / "best.pt").write_bytes(f"weights-{name}".encode())
    bundles = root / "bundles" / "prod_20260805_v5_r1"
    bundles.mkdir(parents=True)
    (bundles / "detector.pt").write_bytes(b"prod-detector")
    (bundles / "manifest.json").write_text("{}")
    return root


class TestInventory:
    def test_scan_is_readonly_and_hashed(self, tmp_path):
        root = _fake_models(tmp_path)
        before = sorted(p.name for p in root.iterdir())
        inv = L.scan_model_inventory(root)
        after = sorted(p.name for p in root.iterdir())
        assert before == after, "inventory 必须只读，不得移动/新增文件"
        ids = {e["model_id"] for e in inv}
        assert {"sku_v1", "sku_v4", "sku_v7_sam", "classifier",
                "e2_p0_coco_s42", "prod_20260805_v5_r1"} <= ids
        prod = next(e for e in inv
                    if e["model_id"] == "prod_20260805_v5_r1")
        assert prod["weights"], "bundle 权重要进入 inventory"
        w = prod["weights"][0]
        expect = hashlib.sha256(b"prod-detector").hexdigest()
        assert w["sha256"] == expect

    def test_classification_rules(self):
        assert L.classify_legacy_model("prod_20260805_v5_r1") == \
            "production_legacy"
        assert L.classify_legacy_model("sku_v4") == "historical"
        assert L.classify_legacy_model("sku_v7_sam") == "experimental_ended"
        assert L.classify_legacy_model("e2_p0_coco_s42") == "historical"
        assert L.classify_legacy_model("classifier") == "historical"
        with pytest.raises(L.LegacyModelError):
            L.classify_legacy_model("unknown_model_x")


class TestRegistry:
    def test_register_append_only_and_idempotent(self, store, tmp_path):
        root = _fake_models(tmp_path)
        inv = L.scan_model_inventory(root)
        n = L.register_legacy_models(store, inv, git_commit="test")
        assert n >= 6
        # 幂等：重复登记不新增
        assert L.register_legacy_models(store, inv, git_commit="test") == 0
        rows = store.list_legacy_models()
        statuses = {r["model_id"]: r["status"] for r in rows}
        assert statuses["prod_20260805_v5_r1"] == "production_legacy"
        assert statuses["sku_v7_sam"] == "experimental_ended"

    def test_registry_immutable(self, store, tmp_path):
        import sqlite3
        root = _fake_models(tmp_path)
        L.register_legacy_models(store, L.scan_model_inventory(root),
                                 git_commit="test")
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute("DELETE FROM legacy_model_registry_v1")


class TestLegacyInferenceCapability:
    def test_capability_only_inference_and_provisional(self):
        cap = L.LegacyInferenceCapability(
            bundle_id="prod_20260805_v5_r1")
        assert cap.capability_id == "legacy.recognition.v2"
        assert "recognition" in cap.allowed_uses
        assert "assisted_proposal" in cap.allowed_uses
        assert "training_parent" not in cap.allowed_uses
        assert cap.proposals_are_provisional is True

    def test_legacy_weight_rejected_as_nextgen_input(self):
        # contracts 侧结构性拒绝（与 inventory 对账的引用格式）
        for ref in (".models/sku_v4/weights/best.pt",
                    "prod_20260805_v5_r1"):
            with pytest.raises(C.ContractError):
                C.validate_parent_ref(ref, field_name="parent_artifact_id")
        # public base 允许
        C.validate_parent_ref("public:yolo26m@r1",
                              field_name="parent_artifact_id")

    def test_projection_separates_legacy_and_nextgen(self, store, tmp_path):
        root = _fake_models(tmp_path)
        L.register_legacy_models(store, L.scan_model_inventory(root),
                                 git_commit="test")
        proj = L.training_overview_projection(store)
        assert proj["production"]["bundle_id"] == "prod_20260805_v5_r1"
        assert proj["production"]["status"] == "production_legacy"
        assert proj["production"]["serving"] is True
        # nextgen 四 lane 与 production 隔离展示
        assert set(proj["nextgen_lanes"].keys()) == set(V.TRAINING_LANES)
        for lane, info in proj["nextgen_lanes"].items():
            assert info["lineage_family"] == "fmcg_nextgen_v1"
            assert info["lineage_family"] != \
                proj["production"]["status"]
