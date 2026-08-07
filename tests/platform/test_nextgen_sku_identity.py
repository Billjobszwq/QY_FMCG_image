"""N2 Task 5：SKU/unknown/new packaging 治理契约。

- 208 Registry 冻结 + alias 版本；
- other/百事other/可乐other → unknown 分层，不强映射；
- 具体未映射名称 → alias_pending（人工裁决），禁猜映射；
- 已知名全部落 canonical sku_id；数据集只存 ID。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.modules.nextgen_data.sku_identity import (
    IdentityError,
    SkuIdentityService,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def svc():
    return SkuIdentityService(
        registry_path=ROOT / "data/sku_registry.json",
        aliases_path=ROOT / "data/sku_aliases.json")


class TestRegistryFreeze:
    def test_registry_208(self, svc):
        assert svc.registry_size() == 208
        assert svc.version() != ""

    def test_known_name_maps_to_canonical_id(self, svc):
        out = svc.resolve("2L百事")
        assert out["status"] == "mapped"
        assert out["sku_id"].startswith("ADM") or out["sku_id"]

    def test_display_name_is_not_identity(self, svc):
        # canonical id 稳定，显示名只是别名
        out = svc.resolve("2L百事")
        assert out["sku_id"] != "2L百事"


class TestUnknownTiers:
    def test_other_is_unknown_not_mapped(self, svc):
        assert svc.resolve("other")["status"] == "unknown"
        assert svc.resolve("百事other")["status"] == "brand_unknown"
        assert svc.resolve("可乐other")["status"] == "category_unknown"
        for n in ("other", "百事other", "可乐other"):
            assert svc.resolve(n)["sku_id"] is None, "禁止强映射"

    def test_specific_unmapped_name_alias_pending(self, svc):
        for n in ("24-元气森林-元气自在水-500ml-PET瓶-陈皮山楂水500ml",
                  "怡泉+C500ml柠檬味"):
            out = svc.resolve(n)
            assert out["status"] == "alias_pending", n
            assert out["sku_id"] is None, "禁猜映射，等待人工裁决"

    def test_unknown_name_never_guesses(self, svc):
        out = svc.resolve("完全不存在的东西XYZ")
        assert out["status"] in ("unknown", "alias_pending")
        assert out["sku_id"] is None


class TestPointMappingLedger:
    def test_map_points_summary(self, svc):
        points = [
            {"name": "2L百事"}, {"name": "other"},
            {"name": "百事other"}, {"name": "怡泉+C500ml柠檬味"}]
        rep = svc.map_points(points)
        assert rep["mapped"] == 1 and rep["unknown"] == 1
        assert rep["brand_unknown"] == 1 and rep["alias_pending"] == 1
        assert rep["total"] == 4
