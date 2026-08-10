"""P0-1 红测试：Profile 必须引用独立测试后的 m3_tvt_*_v2，且单源 DB。

- canonical38_classifier_e1 → m3_tvt_e1_v2（不得 m3_ablation_e1_v1）；
- canonical38_classifier_e5 → m3_tvt_e5_v2；
- shadow_compare → prod bundle + m3_tvt_e1_v2；
- Profile 定义来自数据库（唯一事实源），API 不维护第二份硬编码；
- 旧 ablation 状态 = EXPERIMENTAL_SUPERSEDED_BY_*。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.modules.training_control.profiles import derive_profiles
from src.platform.data.store import PlatformStore


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def test_profile_definitions_live_in_db(store):
    from src.modules.training_control.profiles import seed_profile_defs
    seed_profile_defs(store)
    rows = store._conn.execute(
        "SELECT profile_id, components_json FROM"
        " recognition_profile_def_v1").fetchall()
    ids = {r["profile_id"] for r in rows}
    assert {"production_legacy", "canonical38_classifier_e1",
            "canonical38_classifier_e5", "shadow_compare",
            "canonical38_vlm_real_candidate"} <= ids


def test_e1_e5_reference_tvt_not_ablation(store):
    ps = {p["profile_id"]: p for p in derive_profiles(store)}
    assert "m3_tvt_e1_v2" in ps["canonical38_classifier_e1"]["components"]
    assert "m3_ablation_e1_v1" not in \
        ps["canonical38_classifier_e1"]["components"]
    assert "m3_tvt_e5_v2" in ps["canonical38_classifier_e5"]["components"]
    assert "m3_ablation_e5_v1" not in \
        ps["canonical38_classifier_e5"]["components"]
    assert "prod_20260805_v5_r1_bundle" in \
        ps["shadow_compare"]["components"]
    assert "m3_tvt_e1_v2" in ps["shadow_compare"]["components"]


def test_superseded_ablation_status(store):
    store._conn.execute(
        "INSERT INTO model_artifact_registry_v1 (artifact_id, kind, path,"
        " sha256, candidate_status, created_at) VALUES"
        " ('m3_ablation_e1_v1','model','/x','a'*64,'X',datetime('now'))")
    store._conn.commit()
    from src.modules.training_control.profiles import ARTIFACT_STATUS_FIX
    assert ARTIFACT_STATUS_FIX["m3_ablation_e1_v1"] == \
        "EXPERIMENTAL_SUPERSEDED_BY_M3_TVT_E1_V2"
    assert ARTIFACT_STATUS_FIX["m3_ablation_e5_v1"] == \
        "EXPERIMENTAL_SUPERSEDED_BY_M3_TVT_E5_V2"
    assert ARTIFACT_STATUS_FIX["m3_tvt_e1_v2"] == \
        "CANDIDATE_PENDING_MICRO_GOLD"
