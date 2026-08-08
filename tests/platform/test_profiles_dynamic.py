"""纠偏 Task 7：Recognition Profile 状态必须从 Artifact/Eval/Blocker 动态派生。"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.platform.data.store import PlatformStore
from src.modules.training_control.profiles import derive_profiles


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _reg(store, aid, status):
    store._conn.execute(
        "INSERT INTO model_artifact_registry_v1 (artifact_id, kind, path,"
        " sha256, candidate_status, created_at) VALUES (?,?,?,?,?,datetime('now'))",
        (aid, "model", "/x", "a" * 64, status))
    store._conn.commit()


def test_eight_profiles_present(store):
    ps = derive_profiles(store)
    ids = {p["profile_id"] for p in ps}
    assert {"production_legacy", "nextgen_m1_pilot", "nextgen_m1_m2_pilot",
            "canonical38_classifier", "canonical38_cascade",
            "research83_classifier", "research83_full_cascade",
            "shadow_compare"} <= ids


def test_smoke_not_selectable(store):
    _reg(store, "nextgen_detector_smoke_v1", "SMOKE_ONLY_NOT_CANDIDATE")
    ps = {p["profile_id"]: p for p in derive_profiles(store)}
    assert ps["nextgen_m1_pilot"]["status"] == "disabled"
    assert "smoke_only" in ps["nextgen_m1_pilot"]["blockers"][0].lower() or \
        ps["nextgen_m1_pilot"]["blockers"]


def test_production_legacy_enabled_without_artifacts(store):
    ps = {p["profile_id"]: p for p in derive_profiles(store)}
    assert ps["production_legacy"]["status"] == "enabled"


def test_candidate_enables_profile(store):
    _reg(store, "nextgen_detector_smoke_v1", "CANDIDATE")
    ps = {p["profile_id"]: p for p in derive_profiles(store)}
    assert ps["nextgen_m1_pilot"]["status"] == "enabled"


def test_research83_marked_experimental(store):
    ps = {p["profile_id"]: p for p in derive_profiles(store)}
    assert any("实验" in t or "EXPERIMENT" in t.upper()
               for t in ps["research83_classifier"]["tags"])
