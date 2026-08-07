"""N2 Task 11：Recognition Profile 五入口同口径契约。

- 5 个版本化 profile；未就绪可见但禁用 + blocker；
- 识别请求必须传 recognition_profile_id（禁任意权重路径）；
- 单文件/批量/URL/外部 API/Agent 共用同一契约。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.modules.training_control.profiles import (
    REQUIRED_PROFILES,
    ProfileError,
    ProfileRegistry,
)
from src.platform.data.store import PlatformStore


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


class TestProfileCatalog:
    def test_required_profiles_present(self, store):
        reg = ProfileRegistry(store)
        ids = {p["profile_id"] for p in reg.list_profiles()}
        assert ids == {"production_legacy", "nextgen_detector",
                       "nextgen_detector_segmenter_classifier",
                       "full_cascade_qwen", "shadow_compare"}

    def test_production_legacy_enabled_others_blocked(self, store):
        reg = ProfileRegistry(store)
        by_id = {p["profile_id"]: p for p in reg.list_profiles()}
        assert by_id["production_legacy"]["status"] == "enabled"
        for pid in ("nextgen_detector",
                    "nextgen_detector_segmenter_classifier",
                    "full_cascade_qwen"):
            p = by_id[pid]
            assert p["status"] == "disabled"
            assert p["blockers"], f"{pid} 必须显示 blocker"

    def test_no_arbitrary_weight_path_allowed(self, store):
        reg = ProfileRegistry(store)
        with pytest.raises(ProfileError):
            reg.resolve("/Users/x/.models/sku_v4/weights/best.pt")
        with pytest.raises(ProfileError):
            reg.resolve("not_a_profile")

    def test_resolve_returns_components_and_policy(self, store):
        reg = ProfileRegistry(store)
        p = reg.resolve("production_legacy")
        assert p["components"]["detector"].startswith("prod_")
        assert p["policy_version"]


class TestFiveEntryPoints:
    def test_all_entry_points_use_same_contract(self, store):
        from src.modules.training_control.profiles import ENTRY_POINTS
        assert set(ENTRY_POINTS) == {"single_file", "batch", "url",
                                     "external_api", "internal_agent"}
        reg = ProfileRegistry(store)
        for ep in ENTRY_POINTS:
            req = reg.build_recognition_request(
                entry_point=ep, source=f"src-{ep}",
                profile_id="production_legacy")
            assert req["recognition_profile_id"] == "production_legacy"
            assert req["entry_point"] == ep

    def test_disabled_profile_request_rejected(self, store):
        reg = ProfileRegistry(store)
        with pytest.raises(ProfileError, match="禁用"):
            reg.build_recognition_request(
                entry_point="single_file", source="x.jpg",
                profile_id="full_cascade_qwen")
