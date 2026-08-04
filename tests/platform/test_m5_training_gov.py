"""M5 TDD：训练治理 —— split guard / dry-run / 授权门 / 发布分离 / 晋级门 / 统一评估。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.composition.build import build_production_bundle, build_training_router
from src.modules.training_gov import (
    AuthorizationRequired,
    TrainingGovError,
    TrainingGovernanceService,
    export_inference_manifest,
    promotion_gate,
    split_guard,
    unified_eval,
)
from src.platform.api.app import create_app
from src.platform.api.health import ServiceSpec, ServiceStatus
from src.platform.data.store import PlatformStore

MANIFEST_OK = {
    "train": [
        {"sha256": "a1", "store": "S1", "session": "T1"},
        {"sha256": "a2", "store": "S1", "session": "T1"},
    ],
    "val": [{"sha256": "b1", "store": "S2", "session": "T2"}],
}

MANIFEST_LEAK = {
    "train": [{"sha256": "a1", "store": "S1", "session": "T1"}],
    "val": [{"sha256": "a1", "store": "S1", "session": "T1"}],
}


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


@pytest.fixture()
def svc(store):
    return TrainingGovernanceService(store)


def _fake_probe(spec: ServiceSpec) -> ServiceStatus:
    return ServiceStatus(name=spec.name, status="healthy", latency_ms=1, detail="fake")


# ---------- split guard ----------

def test_split_guard_ok() -> None:
    g = split_guard(MANIFEST_OK)
    assert g["ok"] is True
    assert g["violations"] == []


def test_split_guard_detects_leak() -> None:
    g = split_guard(MANIFEST_LEAK)
    assert g["ok"] is False
    keys = {v["key"] for v in g["violations"]}
    assert {"sha256", "store", "session"} <= keys


def test_split_guard_empty_split() -> None:
    assert split_guard({"train": [], "val": []})["ok"] is False


# ---------- snapshot ----------

def test_register_snapshot_and_hash_determinism(svc) -> None:
    snap = svc.register_snapshot("e2_product", "v1", "product", MANIFEST_OK,
                                 source_actor="alice", source_conclusion="审核通过")
    snap2 = svc.register_snapshot("e2_product", "v2", "product", MANIFEST_OK,
                                  source_actor="alice", source_conclusion="审核通过")
    assert snap["manifest_hash"] == snap2["manifest_hash"]
    assert snap["status"] == "registered"
    assert svc.get_snapshot(snap["snapshot_id"])["name"] == "e2_product"


def test_register_snapshot_rejects_leak(svc) -> None:
    with pytest.raises(TrainingGovError):
        svc.register_snapshot("bad", "v1", "product", MANIFEST_LEAK,
                              source_actor="alice", source_conclusion="x")
    assert svc.list_snapshots() == []


# ---------- gates / dry-run / 授权门 ----------

def test_gates_block_without_authorization(svc) -> None:
    g = svc.gates()
    assert g["training_authorized"] is False
    assert g["can_train"] is False
    assert any("training_authorized=false" in r for r in g["reasons"])


def test_dry_run_produces_plan_without_starting(svc) -> None:
    snap = svc.register_snapshot("e2", "v1", "product", MANIFEST_OK,
                                 source_actor="a", source_conclusion="ok")
    run = svc.dry_run(snap["snapshot_id"], actor="op", epochs=3, budget_minutes=30)
    assert run["kind"] == "dry_run"
    import json
    cmd = json.loads(run["command_json"])
    assert cmd[0:3] == ["python3", "-m", "src.training.train_v1"]
    assert "--budget-minutes" in cmd and "30" in cmd
    plan = json.loads(run["plan_json"])
    assert plan["mps_g0"] is True  # darwin
    # dry-run 不改变授权状态
    assert svc.gates()["training_authorized"] is False


def test_start_training_requires_authorization(svc) -> None:
    snap = svc.register_snapshot("e2", "v1", "product", MANIFEST_OK,
                                 source_actor="a", source_conclusion="ok")
    run = svc.dry_run(snap["snapshot_id"], actor="op")
    with pytest.raises(AuthorizationRequired):
        svc.start_training(run["run_id"], actor="admin1", role="admin")
    # 授权（admin）后允许，但平台仍不执行训练，只标记 authorized
    svc.set_training_authorized(True, actor="admin1", role="admin")
    out = svc.start_training(run["run_id"], actor="admin1", role="admin")
    assert out["kind"] == "authorized"
    assert out["status"] == "authorized"
    assert out["approved_by"] == "admin1"


def test_authorize_requires_admin_role(svc) -> None:
    with pytest.raises(AuthorizationRequired):
        svc.set_training_authorized(True, actor="op", role="operator")
    with pytest.raises(AuthorizationRequired):
        svc.set_training_authorized(True, actor="x", role="viewer")


# ---------- 发布分离 ----------

def test_publish_separate_and_candidate_only(svc) -> None:
    snap = svc.register_snapshot("e2", "v1", "product", MANIFEST_OK,
                                 source_actor="a", source_conclusion="ok")
    run = svc.dry_run(snap["snapshot_id"], actor="op")
    svc.set_training_authorized(True, actor="adm", role="admin")
    svc.start_training(run["run_id"], actor="adm", role="admin")
    req = svc.request_publish(run["run_id"], actor="op", role="operator")
    assert req["publish_status"] == "requested"
    # dry_run/authorized 不是 candidate → 禁止发布
    with pytest.raises(TrainingGovError):
        svc.approve_publish(run["run_id"], actor="adm", role="admin")
    # candidate 才可发布
    svc.store.update_training_run(run["run_id"], kind="completed_candidate")
    out = svc.approve_publish(run["run_id"], actor="adm", role="admin")
    assert out["publish_status"] == "approved"
    # operator 不能批发布
    run2 = svc.dry_run(snap["snapshot_id"], actor="op")
    svc.store.update_training_run(run2["run_id"], kind="completed_candidate")
    with pytest.raises(AuthorizationRequired):
        svc.approve_publish(run2["run_id"], actor="op", role="operator")


# ---------- 晋级门（truebox FP/photo，禁 TopK） ----------

def _report(recall1, recall3, bg, n_images):
    return {"eval_version": "truebox_eval_v2", "n_images": n_images,
            "n_background_fp": bg, "total_fp": bg,
            "recall_at_fp": {"iou_0.50": {1: recall1, 3: recall3, 5: recall3}}}


def test_promotion_gate_pass_and_fail() -> None:
    ok = promotion_gate(_report(0.7, 0.9, 5, 10))
    assert ok["pass"] is True
    bad = promotion_gate(_report(0.2, 0.4, 30, 10))
    assert bad["pass"] is False
    names = [c["name"] for c in bad["checks"] if not c["ok"]]
    assert "recall@FP1(IoU0.5)" in names and "FP/photo(total)" in names


def test_promotion_gate_uses_total_fp_not_background_only() -> None:
    """UMT-002：门禁必须用 total FP（含重复/定位），不得只数背景。"""
    rep = _report(0.7, 0.9, 2, 10)   # background-only 看似过门
    rep["total_fp"] = 30             # 但 total FP 含重复/定位超阈
    assert promotion_gate(rep)["pass"] is False


# ---------- 统一评估 / 推理导出 ----------

def test_unified_eval_same_gt() -> None:
    images = [{"gt": [{"box": [0, 0, 10, 10]}]}, {"gt": [{"box": [0, 0, 10, 10]}]}]
    good = lambda img: [{"box": [0, 0, 10, 10], "conf": 0.9}]  # noqa: E731
    bad = lambda img: []  # noqa: E731
    out = unified_eval(images, {"P0": good, "E0": bad})
    assert out["predictors"]["P0"]["n_tp_iou0.5"] == 2
    assert out["predictors"]["E0"]["recall_at_fp"]["iou_0.50"][1] == 0.0


def test_export_inference_manifest_missing_fails(tmp_path: Path) -> None:
    f = tmp_path / "model.pt"
    f.write_bytes(b"weights")
    m = export_inference_manifest([
        {"stage": "P0", "name": "detector", "path": str(f)},
    ])
    assert m["entries"][0]["size_bytes"] == 7
    with pytest.raises(TrainingGovError):
        export_inference_manifest([
            {"stage": "P1", "name": "clf", "path": str(tmp_path / "nope.pt")},
        ])


# ---------- API E2E ----------

class FakeRecognition:
    def recognize(self, image_bytes: bytes, conf: float = 0.25) -> dict:
        return {"run_id": "fake", "count": 0, "products": [], "elapsed_ms": 1,
                "model": "fake"}


class FakeMonitor:
    def live(self):
        return {"ok": True}

    def overview(self):
        return {"ok": True}


class FakeLS:
    def health(self):
        return {"ok": True}


def test_training_api_e2e(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=FakeRecognition(), monitor_adapter=FakeMonitor(),
        label_studio_adapter=FakeLS(), probe=_fake_probe)
    router = build_training_router(bundle)
    app = create_app(services=(), probe=_fake_probe, bundle=bundle,
                     training_router=router, web_dist=tmp_path / "none")
    client = TestClient(app)

    # gates 初始阻断
    g = client.get("/api/v1/training/gates").json()
    assert g["training_authorized"] is False and g["can_train"] is False

    # snapshot 注册（guard 通过）
    r = client.post("/api/v1/training/snapshots", json={
        "name": "e2", "version": "v1", "manifest": MANIFEST_OK})
    assert r.status_code == 200, r.text
    sid = r.json()["snapshot"]["snapshot_id"]

    # 泄漏 manifest 被拒
    r2 = client.post("/api/v1/training/snapshots", json={
        "name": "bad", "version": "v1", "manifest": MANIFEST_LEAK})
    assert r2.status_code == 400

    # dry-run
    r3 = client.post("/api/v1/training/runs/dry-run", json={"snapshot_id": sid})
    assert r3.status_code == 200, r3.text
    rid = r3.json()["run"]["run_id"]

    # 无授权启动 → 403
    r4 = client.post(f"/api/v1/training/runs/{rid}/start",
                     headers={"X-Role": "admin"})
    assert r4.status_code == 403

    # operator 授权 → 403；admin 授权 → 200
    assert client.post("/api/v1/training/authorize", json={"value": True},
                       headers={"X-Role": "operator"}).status_code == 403
    assert client.post("/api/v1/training/authorize", json={"value": True},
                       headers={"X-Role": "admin"}).status_code == 200

    # admin 启动 → authorized（平台不执行训练）
    r5 = client.post(f"/api/v1/training/runs/{rid}/start",
                     headers={"X-Role": "admin", "X-Actor": "adm"})
    assert r5.status_code == 200, r5.text
    assert r5.json()["run"]["kind"] == "authorized"
