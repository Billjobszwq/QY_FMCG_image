"""UMT-003 红测试：真实 Snapshot 必须由服务端 builder 生成。

手册 §3.1 UMT-003/004 验收口径：
- 逐文件验证：存在、SHA、标签、data.yaml、photo ID、规范门店、session；
- 质量与审核状态：human_final/accepted 才可入 pilot；waiting_human 不得
  伪造通过；auto_provisional 仅 experimental；
- 冻结协议零泄漏（五键）；近重复/重复 SHA 跨 split 拒绝；
- 拒绝客户端自由 JSON：API 不再接受任意 manifest 注册 Snapshot。

本测试在当前"API 接受自由 manifest"实现下必须 RED。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.modules.training_gov.service import (
    TrainingGovError,
    TrainingGovernanceService,
)
from src.platform.data.store import PlatformStore


@pytest.fixture()
def svc(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield TrainingGovernanceService(s)
    s.close()


def _make_photo(tmp_path: Path, name: str, content: bytes | None = None):
    p = tmp_path / "photos" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content or f"img-{name}".encode())
    return p


def _make_label(tmp_path: Path, name: str):
    p = tmp_path / "labels" / (Path(name).stem + ".txt")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("0 0.5 0.5 0.2 0.2\n")
    return p


def _entries(tmp_path: Path):
    t1, t2, v1 = (_make_photo(tmp_path, f"{n}.jpg") for n in ("t1", "t2", "v1"))
    return [
        {"path": str(t1), "label_path": str(_make_label(tmp_path, "t1.jpg")),
         "photo_id": "P1", "store": "门店A", "session": "门店A@2026-08-01",
         "split": "train", "review_status": "human_final",
         "quality_status": "accepted"},
        {"path": str(t2), "label_path": str(_make_label(tmp_path, "t2.jpg")),
         "photo_id": "P2", "store": "门店A", "session": "门店A@2026-08-01",
         "split": "train", "review_status": "human_final",
         "quality_status": "accepted"},
        {"path": str(v1), "label_path": str(_make_label(tmp_path, "v1.jpg")),
         "photo_id": "P3", "store": "门店B", "session": "门店B@2026-08-02",
         "split": "val", "review_status": "human_final",
         "quality_status": "accepted"},
    ]


class TestSnapshotBuilder:
    def test_build_happy_path_writes_datayaml(self, svc, tmp_path):
        out = svc.build_and_register_snapshot(
            "pilot_real", "v1", "product", _entries(tmp_path),
            actor="builder", datasets_root=tmp_path / ".datasets")
        snap = out["snapshot"]
        assert snap["status"] == "registered" and snap["trainable"] == 1
        ds = tmp_path / ".datasets" / "pilot_real_v1"
        assert (ds / "data.yaml").exists(), "builder 必须产出 data.yaml"
        man = json.loads(snap["manifest_json"])
        assert len(man["train"]) == 2 and len(man["val"]) == 1
        assert svc.gates()["registered_snapshots"] == 1

    def test_missing_file_rejected(self, svc, tmp_path):
        entries = _entries(tmp_path)
        entries[0]["path"] = str(tmp_path / "nope.jpg")
        with pytest.raises(TrainingGovError):
            svc.build_and_register_snapshot(
                "x", "v1", "product", entries, actor="b",
                datasets_root=tmp_path / ".datasets")

    def test_sha_leak_across_splits_rejected(self, svc, tmp_path):
        entries = _entries(tmp_path)
        entries[2]["path"] = entries[0]["path"]  # 同内容进 val
        entries[2]["photo_id"] = "P9"
        with pytest.raises(TrainingGovError):
            svc.build_and_register_snapshot(
                "x", "v1", "product", entries, actor="b",
                datasets_root=tmp_path / ".datasets")

    def test_auto_provisional_only_experimental(self, svc, tmp_path):
        entries = _entries(tmp_path)
        entries[0]["review_status"] = "auto_provisional"
        with pytest.raises(TrainingGovError):
            svc.build_and_register_snapshot(
                "x", "v1", "product", entries, actor="b",
                datasets_root=tmp_path / ".datasets")
        out = svc.build_and_register_snapshot(
            "x2", "v1", "experimental", entries, actor="b",
            datasets_root=tmp_path / ".datasets")
        assert out["snapshot"]["status"] == "registered"

    def test_waiting_human_not_faked_pass(self, svc, tmp_path):
        entries = _entries(tmp_path)
        entries[1]["quality_status"] = "waiting_human"
        with pytest.raises(TrainingGovError):
            svc.build_and_register_snapshot(
                "x", "v1", "product", entries, actor="b",
                datasets_root=tmp_path / ".datasets")

    def test_frozen_protocol_leak_rejected(self, svc, tmp_path):
        entries = _entries(tmp_path)
        proto = tmp_path / "protocols"
        proto.mkdir()
        sha = __import__("hashlib").sha256(
            Path(entries[0]["path"]).read_bytes()).hexdigest()
        (proto / "gold_v1.json").write_text(json.dumps(
            {"frozen": True, "role": "gold", "photo_ids": [],
             "sha256": [sha], "stores": [], "sessions": []}))
        with pytest.raises((TrainingGovError, RuntimeError)):
            svc.build_and_register_snapshot(
                "x", "v1", "product", entries, actor="b",
                datasets_root=tmp_path / ".datasets", protocol_dir=proto)

    def test_existing_dataset_dir_not_overwritten(self, svc, tmp_path):
        # run 目录已存在时必须拒绝覆盖（T0-3 红线）
        (tmp_path / ".datasets" / "y_v1").mkdir(parents=True)
        with pytest.raises(TrainingGovError):
            svc.build_and_register_snapshot(
                "y", "v1", "product", _entries(tmp_path), actor="b",
                datasets_root=tmp_path / ".datasets")


class TestApiRejectsFreeJson:
    def test_free_manifest_registration_rejected(self, tmp_path):
        """UMT-003：不得接受客户端自由 JSON + 自由文本冒充人工审核。"""
        from fastapi.testclient import TestClient

        from src.composition.build import (
            build_production_bundle,
            build_training_router,
        )
        from src.platform.api.app import create_app
        from src.platform.api.health import ServiceSpec, ServiceStatus

        from tests.platform.test_m5_training_gov import (
            FakeLS,
            FakeMonitor,
            FakeRecognition,
        )

        def fake_probe(spec: ServiceSpec) -> ServiceStatus:
            return ServiceStatus(name=spec.name, status="healthy",
                                 latency_ms=1, detail="fake")

        bundle = build_production_bundle(
            db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
            recognition_adapter=FakeRecognition(),
            monitor_adapter=FakeMonitor(),
            label_studio_adapter=FakeLS(), probe=fake_probe)
        app = create_app(services=(), probe=fake_probe, bundle=bundle,
                         training_router=build_training_router(bundle),
                         web_dist=tmp_path / "none")
        client = TestClient(app)
        r = client.post("/api/v1/training/snapshots", json={
            "name": "fake", "version": "v1",
            "manifest": {"train": [{"sha256": "a"}], "val": [{"sha256": "b"}]},
            "source_conclusion": "我看过了，通过",
        })
        assert r.status_code in (400, 404, 405, 410), (
            "自由 JSON manifest 注册必须被拒绝")
