"""U2-2 红测试：数据中心接真实 Asset 台账（移除"CAS 未启用"假状态）。

手册 §4/指令：数据中心必须接入真实 Asset/CAS、质量、用途、血缘、审核
和冻结状态；数据来自 U3 不可变台账 source_asset_inventory_v1 +
SHA 去重 + 用途分流，禁止占位假状态。

当前平台无 /api/v1/assets 端点，本测试必须 RED。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (
    build_jobs_router, build_production_bundle, build_training_router)
from src.platform.api.app import create_app
from src.platform.api.health import ServiceSpec, ServiceStatus


def _fake_probe(spec: ServiceSpec) -> ServiceStatus:
    return ServiceStatus(name=spec.name, status="healthy", latency_ms=1,
                         detail="fake")


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    from tests.platform.test_m5_training_gov import (
        FakeLS, FakeMonitor, FakeRecognition)

    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "u22-admin-pw")
    monkeypatch.setenv("PLATFORM_DATASETS_ROOT", str(tmp_path / ".datasets"))
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=FakeRecognition(), monitor_adapter=FakeMonitor(),
        label_studio_adapter=FakeLS(), probe=_fake_probe)
    _worker, jobs_router = build_jobs_router(bundle)
    app = create_app(services=(), probe=_fake_probe, bundle=bundle,
                     training_router=build_training_router(bundle, _worker),
                     jobs_router=jobs_router,
                     web_dist=tmp_path / "none")
    # 种入真实台账数据（U3 口径）
    st = bundle.store
    st.register_inventory_asset(
        source_id="batch3_clean", source_type="manifest_sha_dict",
        source_uri="m.json#p1", photo_id="p1", sha256="a" * 64)
    st.register_inventory_asset(
        source_id="batch1_manifest", source_type="manifest_photos_dict",
        source_uri="m2.json#p1", photo_id="p1", sha256="a" * 64)
    st.register_inventory_asset(
        source_id="protocols", source_type="protocol_dir",
        source_uri=".data_protocol/gold_v2.json#q", photo_id="q",
        sha256="b" * 64)
    st.register_inventory_asset(
        source_id="bad_samples", source_type="directory",
        source_uri="bad_samples/x.jpg", photo_id="x", sha256="c" * 64)
    return TestClient(app), bundle


class TestAssetsSummaryAPI:
    def test_summary_from_real_ledger(self, client):
        client, _ = client
        r = client.get("/api/v1/assets/summary")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["total_refs"] == 4
        assert d["unique_sha"] == 3, "a*64 跨来源重复一次"
        assert d["exact_dup_groups"] == 1
        assert d["rows_without_purpose"] == 0

    def test_summary_has_purpose_and_frozen(self, client):
        client, _ = client
        d = client.get("/api/v1/assets/summary").json()
        assert d["purposes"]["eval_frozen"] == 1
        assert d["purposes"]["quality_negative"] == 1
        assert d["purposes"]["detector_training"] == 2
        assert d["leak_frozen_into_training"] == 0


class TestAssetsListAPI:
    def test_list_real_rows_with_purpose(self, client):
        client, _ = client
        r = client.get("/api/v1/assets", params={"limit": 10})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["count"] == 4
        assert len(d["items"]) == 4
        row = d["items"][0]
        for k in ("source_id", "source_uri", "photo_id", "sha256",
                  "purposes", "registered_at"):
            assert k in row, f"缺少字段 {k}"
        assert row["purposes"], "每行必须带用途"

    def test_list_filter_by_source_and_paging(self, client):
        client, _ = client
        r = client.get("/api/v1/assets",
                       params={"source_id": "protocols", "limit": 10})
        d = r.json()
        assert d["count"] == 1
        assert d["items"][0]["purposes"] == ["eval_frozen"]
        r2 = client.get("/api/v1/assets", params={"limit": 2, "offset": 2})
        assert len(r2.json()["items"]) == 2
        assert r2.json()["count"] == 4
