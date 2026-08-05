"""U3-4 红测试：用途与冻结角色分流（每源照片有 disposition，协议不泄漏）。

手册 §5/§7/指令：所有源照片必须归入至少一种用途（detector 训练 /
classifier-retrieval / 包装版本-未知 SKU / 质量负样本 / 评估冻结集 /
待标注 / 拒绝证据）；frozen protocol 只用于评估，禁止泄漏进训练用途。

当前平台没有分流规则引擎，本测试必须 RED。
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def store(tmp_path: Path):
    from src.platform.data.store import PlatformStore

    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


class TestDispositionRules:
    def test_every_default_source_has_purpose(self):
        """每个来源族必须映射到至少一种用途，不得有空档。"""
        from src.platform.assets.disposition import (PURPOSES,
                                                     assign_dispositions)
        from src.platform.assets.inventory import DEFAULT_SOURCES

        for spec in DEFAULT_SOURCES:
            ps = assign_dispositions(spec["source_id"],
                                     spec["path"] + "#x")
            assert ps, f"来源 {spec['source_id']} 无用途映射"
            assert all(p in PURPOSES for p in ps)

    def test_bad_samples_are_quality_negative_and_evidence(self):
        from src.platform.assets.disposition import assign_dispositions

        ps = assign_dispositions("bad_samples", "bad_samples/x.jpg")
        assert "quality_negative" in ps
        assert "rejection_evidence" in ps
        assert "detector_training" not in ps, "坏样本不得进 detector 训练"

    def test_gold_protocol_is_eval_frozen_only(self):
        from src.platform.assets.disposition import assign_dispositions

        ps = assign_dispositions(
            "protocols", ".data_protocol/gold_v2.json#p1")
        assert ps == ["eval_frozen"], f"gold 协议只能评估冻结，得到 {ps}"
        for name in ("calibration_v1.json#p", "dev_v1.json#p",
                     "diagnostic_v1.json#p", "gold_holdout.json#p"):
            ps = assign_dispositions("protocols", f".data_protocol/{name}")
            assert ps == ["eval_frozen"], name

    def test_unlabeled_field_and_dir_photos_go_to_label(self):
        from src.platform.assets.disposition import assign_dispositions

        for sid in ("photo1106", "photo1107", "pepsi_cola", "field_blobs"):
            ps = assign_dispositions(sid, "照片1106/1.jpg")
            assert "to_label" in ps, sid

    def test_reference_packshots_for_classifier(self):
        from src.platform.assets.disposition import assign_dispositions

        ps = assign_dispositions("p1_reference", "搭建初期P1/x/1.jpg")
        assert "classifier_retrieval" in ps
        assert "packaging_unknown_sku" in ps


class TestDispositionReport:
    def _seed(self, store):
        store.register_inventory_asset(
            source_id="bad_samples", source_type="directory",
            source_uri="bad_samples/x.jpg", photo_id="x", sha256="a" * 64)
        store.register_inventory_asset(
            source_id="protocols", source_type="protocol_dir",
            source_uri=".data_protocol/gold_v2.json#p1", photo_id="p1",
            sha256="b" * 64)
        store.register_inventory_asset(
            source_id="batch3_clean", source_type="manifest_sha_dict",
            source_uri=".batch3_clean/clean_manifest.json#p2",
            photo_id="p2", sha256="c" * 64)
        store.register_inventory_asset(
            source_id="photo1106", source_type="directory",
            source_uri="照片1106/1.jpg", photo_id="1.jpg", sha256="d" * 64)

    def test_report_every_row_has_disposition(self, store):
        from src.platform.assets.disposition import disposition_report

        self._seed(store)
        rep = disposition_report(store)
        assert rep["total_rows"] == 4
        assert rep["rows_without_purpose"] == 0, "每行必须有至少一种用途"
        dist = rep["distribution"]
        assert dist["quality_negative"] >= 1
        assert dist["eval_frozen"] >= 1
        assert dist["to_label"] >= 1

    def test_no_frozen_leak_into_training(self, store):
        """协议泄漏测试：eval_frozen 与 detector_training 必须不相交。"""
        from src.platform.assets.disposition import disposition_report

        self._seed(store)
        rep = disposition_report(store)
        assert rep["leak_frozen_into_training"] == 0
        frozen = set(rep["assets_eval_frozen"])
        training = set(rep["assets_detector_training"])
        assert not (frozen & training)
