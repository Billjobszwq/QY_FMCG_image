"""N2 Task 7：四类 DatasetSnapshot 契约（02 设计 §5）。

- label source tier 与训练权重；model_proposal/unreviewed 拒入；
- human gold 仅作 eval/calibration，pseudo 不进冻结 eval；
- 五键（SHA/store/session/near-dup/package）零泄漏；
- CandidateSet builder 签名无 GT；原子发布、目录存在拒绝。
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from src.modules.nextgen_data.snapshots import (
    LABEL_TIERS,
    SnapshotError,
    build_detector_snapshot,
    build_classifier_snapshot,
    build_segmenter_snapshot,
    build_vlm_snapshot,
    group_split,
)


def _sample(i, sku="SKU-1", label="legacy_coordinate_verified",
            store="S1", session="T1", nd="", pkg="PKG-1",
            box=(10, 10, 50, 60), split_hint=None):
    return {"asset_id": f"a{i}", "photo_sha256": f"sha{i:04d}",
            "region_id": f"r{i}", "box": list(box), "sku_id": sku,
            "package_version_id": pkg, "label_source": label,
            "store": store, "session": session, "near_dup_group": nd,
            "width": 100, "height": 200, "split_hint": split_hint}


class TestLabelTiers:
    def test_tiers_frozen(self):
        assert set(LABEL_TIERS) == {"human_gold",
                                    "legacy_coordinate_verified",
                                    "sam_verified_pseudo",
                                    "model_proposal",
                                    "unknown_new_packaging"}

    def test_model_proposal_rejected_from_training(self, tmp_path):
        samples = [_sample(1, label="model_proposal")]
        with pytest.raises(SnapshotError, match="label_source"):
            build_detector_snapshot(samples, out_root=tmp_path,
                                    snapshot_id="d_bad")

    def test_tier_weights(self, tmp_path):
        samples = [_sample(1, label="human_gold"),
                   _sample(2, label="legacy_coordinate_verified"),
                   _sample(3, label="sam_verified_pseudo")]
        rep = build_detector_snapshot(samples, out_root=tmp_path,
                                      snapshot_id="d_w")
        w = {s["label_source"]: s["sample_weight"]
             for s in rep["manifest"]["samples"]}
        assert w["human_gold"] > w["legacy_coordinate_verified"] \
            >= w["sam_verified_pseudo"]


class TestGoldEvalSeparation:
    def test_pseudo_never_in_frozen_eval(self, tmp_path):
        samples = [_sample(i, label="sam_verified_pseudo")
                   for i in range(8)] + \
                  [_sample(100 + i, label="human_gold") for i in range(4)]
        rep = build_detector_snapshot(samples, out_root=tmp_path,
                                      snapshot_id="d_eval")
        eval_ids = {s["region_id"] for s in
                    rep["manifest"]["samples"] if s["split"] == "eval"}
        eval_labels = {s["label_source"] for s in
                       rep["manifest"]["samples"] if s["split"] == "eval"}
        assert eval_labels <= {"human_gold"}, "pseudo 不得进冻结 eval"


class TestSplitGuard:
    def test_five_key_leakage_rejected(self, tmp_path):
        a = _sample(1, store="SX", session="TX", nd="G1", pkg="PX")
        b = _sample(2, store="SX", session="TX", nd="G1", pkg="PX",
                    split_hint="val")
        with pytest.raises(SnapshotError, match="leak"):
            build_detector_snapshot([a, b], out_root=tmp_path,
                                    snapshot_id="d_leak")


class TestSegmenterAndVlm:
    def test_segmenter_requires_masks(self, tmp_path):
        s = _sample(1)  # 无 mask_ref
        with pytest.raises(SnapshotError, match="mask"):
            build_segmenter_snapshot([s], out_root=tmp_path,
                                     snapshot_id="s_bad")

    def test_segmenter_with_mask_trainable(self, tmp_path):
        s = {**_sample(1), "mask_rle": "0:10", "tight_box": [1, 1, 5, 5]}
        rep = build_segmenter_snapshot([s], out_root=tmp_path,
                                       snapshot_id="s_ok")
        assert rep["manifest"]["trainable"] is True

    def test_vlm_candidate_builder_no_gt(self):
        from src.modules.dataset_factory.service import build_candidate_set
        sig = inspect.signature(build_candidate_set)
        assert not (set(sig.parameters) &
                    {"gt", "gt_sku", "answer", "label", "target"})

    def test_vlm_snapshot_includes_context_and_target(self, tmp_path):
        s = {**_sample(1), "ocr_text": "百事可乐",
             "candidates": [{"sku_id": "SKU-1", "score": 0.9}]}
        rep = build_vlm_snapshot([s], out_root=tmp_path,
                                 snapshot_id="v_ok")
        m = rep["manifest"]["samples"][0]
        assert m["target_type"] in ("closed_set", "unknown", "new_package",
                                    "abstain")
        assert "candidates" in m and "context" in m

    def test_classifier_crops_inherit_split(self, tmp_path):
        samples = [_sample(i) for i in range(6)]
        rep = build_classifier_snapshot(samples, out_root=tmp_path,
                                        snapshot_id="c_ok")
        for s in rep["manifest"]["samples"]:
            assert s["crop"]["split"] == s["split"]


class TestAtomicPublish:
    def test_existing_dir_rejected(self, tmp_path):
        (tmp_path / "taken").mkdir()
        with pytest.raises(SnapshotError, match="存在"):
            build_detector_snapshot([_sample(1)], out_root=tmp_path,
                                    snapshot_id="taken")

    def test_exclusion_ledger_present(self, tmp_path):
        rep = build_detector_snapshot([_sample(1)], out_root=tmp_path,
                                      snapshot_id="d_led")
        m = rep["manifest"]
        for k in ("manifest_hash", "builder_version", "schema_version",
                  "split_report", "exclusion_ledger", "source_hashes",
                  "quality_histogram"):
            assert k in m
