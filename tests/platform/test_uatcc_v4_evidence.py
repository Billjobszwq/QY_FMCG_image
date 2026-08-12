"""UATCC T5：V4 证据口径测试。

- SKU 字段契约（sku_name/status/confidence/margin/box）；
- current 暴露 USER_SELECTED_UAT_MODEL（不写 PRODUCTION_APPROVED）；
- shadow v2 优先；rollback smoke 后 CURRENT 恢复。
"""
from __future__ import annotations

from src.platform.standard_profile import StandardProfileService


class TestSkuFieldContract:
    def test_extract_products_reads_sku_name(self):
        from scripts.recognition_shadow_compare import extract_products
        out = extract_products([
            {"sku_id": "A", "sku_name": "可乐", "status": "accepted"},
            {"sku_id": "B", "sku_name": "雪碧", "status": "accepted"}])
        assert out == ["可乐", "雪碧"]

    def test_detail_fields_complete(self):
        from scripts.recognition_shadow_compare import detail_products
        d = detail_products([{"sku_id": "A", "sku_name": "可乐",
                              "status": "accepted",
                              "classifier_conf": 0.9, "margin": 0.5,
                              "box": [1, 2, 3, 4]}])[0]
        for k in ("sku_id", "sku_name", "status", "confidence",
                  "margin", "box"):
            assert k in d


class TestModelStatusHonesty:
    def test_current_marks_user_selected_uat_model(self, tmp_path,
                                                   monkeypatch):
        monkeypatch.setenv("STANDARD_BUNDLES_DIR",
                           str(tmp_path / "bundles"))
        (tmp_path / "bundles" / "prod_v4_best_r1").mkdir(parents=True)
        (tmp_path / "bundles" / "CURRENT.json").write_text(
            '{"bundle_id": "prod_v4_best_r1"}', encoding="utf-8")
        svc = StandardProfileService.__new__(StandardProfileService)
        svc.bundles_dir = tmp_path / "bundles"
        cur = svc.current()
        assert cur["model_status"] == "USER_SELECTED_UAT_MODEL"
        assert "PRODUCTION_APPROVED" not in str(cur)

    def test_current_not_marked_for_other_bundles(self, tmp_path,
                                                  monkeypatch):
        svc = StandardProfileService.__new__(StandardProfileService)
        svc.bundles_dir = tmp_path / "bundles"
        (tmp_path / "bundles").mkdir(parents=True, exist_ok=True)
        (tmp_path / "bundles" / "CURRENT.json").write_text(
            '{"bundle_id": "prod_20260805_v5_r1"}', encoding="utf-8")
        cur = svc.current()
        assert "model_status" not in cur
