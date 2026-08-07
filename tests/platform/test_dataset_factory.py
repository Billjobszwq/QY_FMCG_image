"""GLTC-003 红测试：Dataset Factory 四 builder（任务书 Task 3 / 01 §3）。

契约：
- 共同准入：active queue + human_final/gold_verified；prediction/unreviewed/
  submitted/conflict/superseded/model_provisional/rq_v1/frozen 一律拒入；
- split 守卫：SHA/store/session/near-dup/package 泄漏 fail-closed；
- staging → 原子发布；目标目录已存在拒绝覆盖；
- exclusion ledger、quality histogram、source hashes、manifest hash 齐全；
- D3 无 mask gold 只产 calibration（trainable=False）；
- D4 候选构造签名不接受 GT；
- 派生 crop 继承原图 split；四快照 manifest 独立。
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from src.modules.dataset_factory import service as F


def _row(region_id="r1", sha="s1", store="S1", session="T1",
         sku_id="SKU-1", review_status="human_final",
         queue_version="rq_v2", protocol="active_v1",
         box=(10, 20, 100, 200), mask_ref="", split="train",
         near_dup="", package="PKG-1"):
    return {
        "asset_id": f"a-{sha}-{region_id}", "photo_id": f"p-{sha}",
        "photo_sha256": sha, "region_id": region_id, "box": list(box),
        "sku_id": sku_id, "sku_name": f"名称{sku_id}",
        "package_version_id": package, "review_status": review_status,
        "queue_version": queue_version, "protocol": protocol,
        "store": store, "session": session, "near_dup_group": near_dup,
        "mask_ref": mask_ref, "split": split,
        "image_width": 1000, "image_height": 2000,
    }


@pytest.fixture()
def out_root(tmp_path: Path) -> Path:
    return tmp_path / "snapshots"


class TestAdmission:
    def test_only_human_final_and_gold_verified_admitted(self, out_root):
        rows = [_row(review_status=st) for st in
                ("human_final", "gold_verified", "prediction", "unreviewed",
                 "submitted", "conflict", "superseded", "model_provisional")]
        rep = F.build_snapshot("detector", rows=rows, out_root=out_root,
                               dataset_id="adm1")
        assert rep["admitted"] == 2
        excluded = {e["reason"] for e in rep["exclusion_ledger"]}
        assert "forbidden_label_source" in excluded

    def test_invalid_queue_and_frozen_protocol_rejected(self, out_root):
        rows = [_row(queue_version="rq_v1"),
                _row(protocol="diagnostic_v1"),
                _row(protocol="calibration_v1"),
                _row()]  # 唯一合法
        rep = F.build_snapshot("detector", rows=rows, out_root=out_root,
                               dataset_id="adm2")
        assert rep["admitted"] == 1
        reasons = {e["reason"] for e in rep["exclusion_ledger"]}
        assert "invalid_queue_version" in reasons
        assert "frozen_protocol" in reasons

    def test_unknown_sku_not_forced_into_registry(self, out_root):
        rows = [_row(sku_id="unknown"), _row(sku_id="new_packaging")]
        rep = F.build_snapshot("classifier", rows=rows, out_root=out_root,
                               dataset_id="adm3")
        # unknown/new_packaging 允许保留原语义进入快照，不被改写
        m = json.loads((out_root / "adm3" / "manifest.json").read_text())
        targets = {s["sku_id"] for s in m["samples"]}
        assert {"unknown", "new_packaging"} <= targets


class TestSplitGuard:
    def test_sha_store_session_leak_rejected(self, out_root):
        rows = [_row(sha="s1", split="train"),
                _row(sha="s1", region_id="r2", split="val"),  # SHA 泄漏
                _row(sha="s2", store="S1", split="val"),      # 门店泄漏
                _row(sha="s3", store="S2", session="T1",
                     split="val"),                            # session 泄漏
                _row(sha="s4", store="S2", session="T2",
                     near_dup="g1", split="val"),
                _row(sha="s5", store="S3", session="T3",
                     near_dup="g1", split="train")]           # 近重复泄漏
        with pytest.raises(F.SplitLeakageError) as e:
            F.build_snapshot("detector", rows=rows, out_root=out_root,
                             dataset_id="sg1")
        keys = {v["key"] for v in e.value.violations}
        assert {"sha256", "store", "session", "near_dup_group"} <= keys

    def test_crop_inherits_photo_split(self, out_root):
        rows = [_row(sha="c1", split="train")]
        rep = F.build_snapshot("classifier", rows=rows, out_root=out_root,
                               dataset_id="sg2")
        m = json.loads((out_root / "sg2" / "manifest.json").read_text())
        assert m["samples"][0]["split"] == "train"
        assert m["samples"][0]["crop"]["split"] == "train"


class TestAtomicPublish:
    def test_existing_target_rejected(self, out_root):
        (out_root / "dup1").mkdir(parents=True)
        with pytest.raises(F.PublishError):
            F.build_snapshot("detector", rows=[_row()], out_root=out_root,
                             dataset_id="dup1")

    def test_staging_not_left_behind_on_success(self, out_root):
        F.build_snapshot("detector", rows=[_row()], out_root=out_root,
                         dataset_id="ok1")
        assert (out_root / "ok1" / "manifest.json").exists()
        assert not (out_root / ".staging-ok1").exists()

    def test_zero_rows_writes_nothing(self, out_root):
        rep = F.build_snapshot("detector", rows=[], out_root=out_root,
                               dataset_id="zero1")
        assert rep["admitted"] == 0
        assert not (out_root / "zero1").exists()


class TestSnapshotAudit:
    def test_manifest_audit_fields(self, out_root):
        rep = F.build_snapshot("detector", rows=[_row()],
                               out_root=out_root, dataset_id="au1")
        m = json.loads((out_root / "au1" / "manifest.json").read_text())
        for k in ("schema_version", "builder_version", "manifest_hash",
                  "split_report", "quality_histogram", "exclusion_ledger",
                  "source_hashes", "lane"):
            assert k in m, f"缺审计字段 {k}"
        assert rep["manifest_hash"] == m["manifest_hash"]

    def test_four_lanes_have_distinct_schemas(self, out_root):
        hashes = {}
        for lane in ("detector", "classifier", "segmenter", "vlm"):
            rows = [_row(mask_ref="cas://mask1" if lane == "segmenter"
                         else "")]
            rep = F.build_snapshot(lane, rows=rows, out_root=out_root,
                                   dataset_id=f"sch_{lane}")
            hashes[lane] = rep["schema_version"]
        assert len(set(hashes.values())) == 4


class TestSegmenterGoldGate:
    def test_no_mask_gold_only_calibration(self, out_root):
        rows = [_row(mask_ref="")]  # 只有 bbox，无真实 mask gold
        rep = F.build_snapshot("segmenter", rows=rows, out_root=out_root,
                               dataset_id="cal1")
        assert rep["trainable"] is False
        assert rep["mode"] == "calibration_only"

    def test_mask_gold_allows_trainable(self, out_root):
        rows = [_row(mask_ref="cas://mask1")]
        rep = F.build_snapshot("segmenter", rows=rows, out_root=out_root,
                               dataset_id="cal2")
        assert rep["trainable"] is True
        assert rep["mode"] == "trainable"


class TestVlmCandidates:
    def test_candidate_builder_signature_forbids_gt(self):
        sig = inspect.signature(F.build_candidate_set)
        forbidden = {"gt", "gt_sku", "gt_class", "answer", "label",
                     "target"}
        assert not (set(sig.parameters) & forbidden), \
            "CandidateSet 构造不得接受 GT"

    def test_candidates_short_of_k_not_padded_with_gt(self, out_root):
        # registry 只有 2 个候选时 topk=8 自然截断，不补真值
        cs = F.build_candidate_set(query_text="茉莉乌龙",
                                   registry_ids=["SKU-1", "SKU-2"], topk=8)
        assert len(cs) == 2
