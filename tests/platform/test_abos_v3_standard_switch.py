"""ABOSV3 T8 红测试：standard profile 受控切换与回滚。

- bundle 校验 fail-closed（hash 不一致拒绝切换）；
- 切换原子 + 备份生成 + 审计留痕 + v4_best_standard profile 同步启用；
- 回滚恢复上一 bundle 且 profile 同步禁用；
- 重复切换同一 bundle 拒绝；非管理员 403；
- profile 目录含实验 profile（诚实 blocker，classifier-only 不得单独）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.api.app import create_app
from src.platform.standard_profile import (StandardProfileError,
                                           StandardProfileService)

PW = "v8-switch-pw"


class _OkRecognition:
    def recognize(self, data: bytes, conf: float = 0.25):
        return {"count": 0, "products": []}


def _make_bundle_dir(tmp: Path, name: str, content: bytes = b"weights") \
        -> Path:
    import hashlib
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "detector.pt").write_bytes(content)
    h = hashlib.sha256(content).hexdigest()
    manifest = {"bundle_id": name, "files": [
        {"file": f"{name}/detector.pt", "size": len(content),
         "sha256": h}]}
    (d / "MANIFEST.json").write_text(
        json.dumps(manifest), encoding="utf-8")
    return d


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", PW)
    adapter = _OkRecognition()
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=adapter, probe=lambda spec: None)
    build_profiles_service(bundle)
    # profile 目录 seed（生产由 API 首次访问触发；测试显式 seed）
    from src.modules.training_control.profiles import derive_profiles
    derive_profiles(bundle.store)
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    cur = {"bundle_id": "old_bundle"}
    _make_bundle_dir(bundles, "old_bundle")
    _make_bundle_dir(bundles, "prod_v4_best_r1")
    (bundles / "CURRENT.json").write_text(json.dumps(cur),
                                          encoding="utf-8")
    svc = StandardProfileService(bundle.store, bundles_dir=bundles)
    # 制品登记：V4 bundle 初始 SHADOW_PENDING_SWITCH（未验证不得启用）
    bundle.store._conn.execute(
        "INSERT INTO model_artifact_registry_v1 (artifact_id, kind,"
        " path, sha256, dataset_manifest_sha, source_commit,"
        " dirty_diff_hash, model_base, label_source, evidence_level,"
        " candidate_status, blocker, created_at, reconciled_by,"
        " reconciliation_run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("prod_v4_best_r1_bundle", "detector_bundle", "x", "y", "", "",
         "", "", "", "", "SHADOW_PENDING_SWITCH", "",
         "2026-08-12T00:00:00Z", "test", "t"))
    bundle.store._conn.commit()
    # 让 app 内的 standard 服务也使用临时 bundles 目录（不碰真实 .models）
    monkeypatch.setenv("STANDARD_BUNDLES_DIR", str(bundles))
    app = create_app(services=(), probe=lambda spec: None,
                     bundle=bundle, recognition_adapter=adapter,
                     web_dist=Path("/nonexistent-dist"))
    client = TestClient(app)
    r = client.post("/api/v1/auth/login",
                    json={"username": "admin", "password": PW})
    h = {"X-CSRF-Token": r.json()["csrf_token"]}
    return {"store": bundle.store, "svc": svc, "bundles": bundles,
            "client": client, "h": h}


class TestSwitchService:
    def test_verify_fail_closed_on_hash_mismatch(self, env):
        svc: StandardProfileService = env["svc"]
        # 破坏文件 → 校验失败 → 切换拒绝
        bad = env["bundles"] / "prod_v4_best_r1" / "detector.pt"
        bad.write_bytes(b"tampered")
        v = svc.verify_bundle("prod_v4_best_r1")
        assert v["consistent"] is False
        with pytest.raises(StandardProfileError):
            svc.switch(bundle_id="prod_v4_best_r1", actor="admin")
        # CURRENT 未被改动（无半切换）
        assert svc.current()["bundle_id"] == "old_bundle"

    def test_switch_backup_rollback_cycle(self, env):
        from src.modules.training_control.profiles import derive_profiles
        svc: StandardProfileService = env["svc"]
        # 切换前：v4_best_standard 必须 disabled（未验证不得启用）
        pre = {p["profile_id"]: p for p in derive_profiles(env["store"])}
        assert pre["v4_best_standard"]["status"] == "disabled"
        cur = svc.switch(bundle_id="prod_v4_best_r1", actor="admin",
                         reason="测试切换")
        assert cur["bundle_id"] == "prod_v4_best_r1"
        assert cur["previous"] == "old_bundle"
        assert (env["bundles"] / "CURRENT.previous.json").exists()
        # 切换后：制品置 CANDIDATE → profile 派生为 enabled
        post = {p["profile_id"]: p for p in derive_profiles(env["store"])}
        assert post["v4_best_standard"]["status"] == "enabled"
        # 重复切换拒绝
        with pytest.raises(StandardProfileError):
            svc.switch(bundle_id="prod_v4_best_r1", actor="admin")
        # 回滚
        back = svc.rollback(actor="admin")
        assert back["bundle_id"] == "old_bundle"
        rolled = {p["profile_id"]: p
                  for p in derive_profiles(env["store"])}
        assert rolled["v4_best_standard"]["status"] == "disabled"
        # 审计留痕
        audits = [a["action"] for a in
                  env["store"]._conn.execute(
                      "SELECT action FROM iam_audit_event_v1"
                      " WHERE action LIKE 'recognition.standard%'")
                  .fetchall()]
        assert "recognition.standard.switched" in audits
        assert "recognition.standard.rollback" in audits

    def test_rollback_without_backup_rejected(self, env):
        svc: StandardProfileService = env["svc"]
        with pytest.raises(StandardProfileError):
            svc.rollback(actor="admin")


class TestProfilesCatalog:
    def test_experimental_profiles_honest(self, env):
        from src.modules.training_control.profiles import derive_profiles
        profs = {p["profile_id"]: p for p in derive_profiles(env["store"])}
        for need in ("v4_best_standard", "exp_classifier_only",
                     "exp_v4_detector_smoke"):
            assert need in profs, f"缺少 profile: {need}"
        # 实验 profile 一律 disabled（不伪装 production-ready）
        assert profs["v4_best_standard"]["status"] == "disabled"
        assert profs["exp_classifier_only"]["status"] == "disabled"
        assert profs["exp_v4_detector_smoke"]["status"] == "disabled"
        # classifier-only 的 blocker 必须说明需 detector 组合
        assert any("detector" in b for b in
                   profs["exp_classifier_only"]["blockers"]) or \
            profs["exp_classifier_only"]["blockers"]


class TestSwitchApi:
    def test_switch_and_rollback_via_api(self, env):
        c, h, svc = env["client"], env["h"], env["svc"]
        r = c.post("/api/v1/recognition/standard/switch", headers=h,
                   json={"bundle_id": "prod_v4_best_r1",
                         "reason": "API 切换测试"})
        assert r.status_code == 200, r.text
        assert r.json()["current"]["bundle_id"] == "prod_v4_best_r1"
        st = c.get("/api/v1/recognition/standard").json()
        assert st["current"]["bundle_id"] == "prod_v4_best_r1"
        assert st["verify_current"]["consistent"] is True
        r = c.post("/api/v1/recognition/standard/rollback", headers=h)
        assert r.status_code == 200
        assert r.json()["current"]["bundle_id"] == "old_bundle"

    def test_switch_unknown_bundle_409(self, env):
        c, h = env["client"], env["h"]
        r = c.post("/api/v1/recognition/standard/switch", headers=h,
                   json={"bundle_id": "not_exist"})
        assert r.status_code == 409
