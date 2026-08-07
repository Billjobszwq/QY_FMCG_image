"""GLTC-008 红测试：统一训练控制 API（任务书 Task 8 / 01 §10）。

- lanes/readiness/overview/legacy 只读公开投影；
- production legacy 与 nextgen 分离展示；
- readiness 如实反映 blocker（gold=0、mask gold=0、授权=false）；
- 数据集构建等写端点需登录 session（未登录 401）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _client(tmp_path):
    from src.composition.build import (build_production_bundle,
                                     build_training_control_router)
    from src.platform.api.app import create_app

    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=None, monitor_adapter=None,
        label_studio_adapter=None, probe=lambda spec: None)
    app = create_app(services=(), probe=lambda spec: None, bundle=bundle,
                     web_dist=tmp_path / "none",
                     training_control_router=build_training_control_router(
                         bundle))
    return TestClient(app), bundle


@pytest.fixture()
def client(tmp_path: Path):
    c, bundle = _client(tmp_path)
    return c, bundle


class TestLanesProjection:
    def test_lanes_returns_four_lanes_and_production(self, client):
        c, _ = client
        d = c.get("/api/v1/training/lanes").json()
        assert set(d["lanes"].keys()) == {
            "detector", "classifier", "segmenter", "vlm"}
        prod = d["production"]
        assert prod["status"] == "production_legacy"
        assert prod["lineage"] != "fmcg_nextgen_v1"
        # nextgen 与 production 明确分离
        for lane, info in d["lanes"].items():
            assert info["lineage_family"] == "fmcg_nextgen_v1"

    def test_readiness_reports_honest_blockers(self, client):
        c, _ = client
        d = c.get("/api/v1/training/lanes/detector/readiness").json()
        codes = {b["code"] for b in d["blockers"]}
        assert "BLOCKED_BY_GOLD" in codes           # gold_region=0
        assert "BLOCKED_BY_AUTHORIZATION" in codes  # flag=false
        assert d["ready"] is False

    def test_segmenter_blocked_by_mask_gold(self, client):
        c, _ = client
        d = c.get("/api/v1/training/lanes/segmenter/readiness").json()
        codes = {b["code"] for b in d["blockers"]}
        assert "BLOCKED_BY_MASK_GOLD" in codes

    def test_unknown_lane_404(self, client):
        c, _ = client
        assert c.get("/api/v1/training/lanes/ocr/readiness").status_code == 404


class TestOverviewAndLegacy:
    def test_overview_structure(self, client):
        c, _ = client
        d = c.get("/api/v1/training/overview").json()
        for k in ("production", "lanes", "gold", "leases",
                  "training_authorized"):
            assert k in d
        assert d["gold"]["usable_regions"] == 0
        assert d["training_authorized"] is False

    def test_legacy_models_listing(self, client):
        c, bundle = client
        bundle.store.register_legacy_model(
            model_id="prod_20260805_v5_r1", path="bundles/x",
            status="production_legacy", git_commit="t")
        d = c.get("/api/v1/training/legacy-models").json()
        assert d["count"] == 1
        assert d["models"][0]["status"] == "production_legacy"


class TestWriteEndpointsRequireSession:
    def test_dataset_build_unauthenticated_401(self, client):
        c, _ = client
        r = c.post("/api/v1/training/datasets/detector/build")
        assert r.status_code == 401
