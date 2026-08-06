"""VLM-011 TDD：受治理 Qwen3-VL QLoRA launcher（门禁链 + 冻结命令，不执行）。

红线复述：
- 证据链缺失（snapshot/preflight/zero-shot/benchmark）一律 fail-closed；
- 只生成 MLX-VLM 真实参数，禁 --use-mps/--num-epochs；
- 第一轮上限：1 epoch、rank16、alpha32、batch≤benchmark 推荐、
  5,000–20,000 instance、vision frozen（train_vision 需独立授权）；
- 完成只产生 completed_candidate，发布仍需独立 admin 审批。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.modules.training_gov import (
    AuthorizationRequired,
    TrainingGovError,
    TrainingGovernanceService,
)
from src.platform.data.store import PlatformStore

SNAPSHOT_OK = {"train_instances": 8000, "manifest_sha256": "aa" * 32}
PREFLIGHT_OK = {"ok": True, "checks": {}, "blockers": []}
ZERO_SHOT_OK = {"coverage": 0.92, "accepted_precision": 0.91}
BENCHMARK_OK = {"recommended_batch_size": 2}

BASE_KW = dict(
    dataset_path=".datasets/vlm_v1/hf",
    output_dir=".models/qwen3vl_lora_r1",
    snapshot=SNAPSHOT_OK,
    preflight_report=PREFLIGHT_OK,
    zero_shot_report=ZERO_SHOT_OK,
    benchmark_report=BENCHMARK_OK,
)


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


@pytest.fixture()
def svc(store):
    return TrainingGovernanceService(store)


def _authorize(svc) -> None:
    svc.set_training_authorized(True, actor="adm", role="admin")


# ---------- 证据链门禁（fail-closed） ----------

def test_missing_snapshot_rejected(svc) -> None:
    _authorize(svc)
    kw = {**BASE_KW, "snapshot": None}
    with pytest.raises(TrainingGovError) as e:
        svc.plan_vlm_training(actor="adm", role="admin", **kw)
    assert "snapshot_missing" in str(e.value)


def test_missing_preflight_rejected(svc) -> None:
    _authorize(svc)
    kw = {**BASE_KW, "preflight_report": None}
    with pytest.raises(TrainingGovError) as e:
        svc.plan_vlm_training(actor="adm", role="admin", **kw)
    assert "preflight_missing" in str(e.value)


def test_preflight_not_ok_rejected(svc) -> None:
    _authorize(svc)
    kw = {**BASE_KW,
          "preflight_report": {"ok": False, "blockers": ["active_training"]}}
    with pytest.raises(TrainingGovError) as e:
        svc.plan_vlm_training(actor="adm", role="admin", **kw)
    assert "preflight_failed" in str(e.value)


def test_missing_zero_shot_rejected(svc) -> None:
    _authorize(svc)
    kw = {**BASE_KW, "zero_shot_report": None}
    with pytest.raises(TrainingGovError) as e:
        svc.plan_vlm_training(actor="adm", role="admin", **kw)
    assert "zero_shot_missing" in str(e.value)


def test_missing_benchmark_rejected(svc) -> None:
    _authorize(svc)
    kw = {**BASE_KW, "benchmark_report": None}
    with pytest.raises(TrainingGovError) as e:
        svc.plan_vlm_training(actor="adm", role="admin", **kw)
    assert "benchmark_missing" in str(e.value)


def test_output_dir_exists_rejected(svc, tmp_path: Path) -> None:
    _authorize(svc)
    out = tmp_path / "occupied"
    out.mkdir()
    kw = {**BASE_KW, "output_dir": str(out)}
    with pytest.raises(TrainingGovError) as e:
        svc.plan_vlm_training(actor="adm", role="admin", **kw)
    assert "output_dir_exists" in str(e.value)


def test_active_training_conflict_rejected(svc) -> None:
    _authorize(svc)
    # 制造一个执行中的 run（如当前 sku_v7_sam 情形的平台映射）
    from tests.platform.test_m5_training_gov import MANIFEST_OK
    snap = svc.register_snapshot("e2", "v1", "product", MANIFEST_OK,
                                 source_actor="a", source_conclusion="ok")
    run = svc.dry_run(snap["snapshot_id"], actor="op")
    svc.store.update_training_run(run["run_id"], status="running")
    with pytest.raises(TrainingGovError) as e:
        svc.plan_vlm_training(actor="adm", role="admin", **BASE_KW)
    assert "active_training_conflict" in str(e.value)


def test_unauthorized_rejected(svc) -> None:
    # 未设置 training_authorized
    with pytest.raises(AuthorizationRequired) as e:
        svc.plan_vlm_training(actor="op", role="operator", **BASE_KW)
    assert "training_unauthorized" in str(e.value)


# ---------- 第一轮参数上限 ----------

def test_batch_exceeds_benchmark_rejected(svc) -> None:
    _authorize(svc)
    with pytest.raises(TrainingGovError) as e:
        svc.plan_vlm_training(actor="adm", role="admin",
                              batch_size=4, **BASE_KW)
    assert "batch_exceeds_benchmark" in str(e.value)


def test_epochs_exceed_approved_rejected(svc) -> None:
    _authorize(svc)
    with pytest.raises(TrainingGovError) as e:
        svc.plan_vlm_training(actor="adm", role="admin",
                              epochs=3, **BASE_KW)
    assert "epochs_exceed_first_round" in str(e.value)


def test_rank_alpha_limits_rejected(svc) -> None:
    _authorize(svc)
    with pytest.raises(TrainingGovError) as e1:
        svc.plan_vlm_training(actor="adm", role="admin",
                              lora_rank=32, **BASE_KW)
    assert "rank_exceed_first_round" in str(e1.value)
    with pytest.raises(TrainingGovError) as e2:
        svc.plan_vlm_training(actor="adm", role="admin",
                              lora_alpha=64, **BASE_KW)
    assert "alpha_exceed_first_round" in str(e2.value)


def test_instance_range_enforced(svc) -> None:
    _authorize(svc)
    for bad in (4999, 20001):
        kw = {**BASE_KW, "snapshot": {**SNAPSHOT_OK, "train_instances": bad}}
        with pytest.raises(TrainingGovError) as e:
            svc.plan_vlm_training(actor="adm", role="admin", **kw)
        assert "instances_out_of_range" in str(e.value)


def test_train_vision_requires_separate_authorization(svc) -> None:
    _authorize(svc)
    with pytest.raises(AuthorizationRequired) as e:
        svc.plan_vlm_training(actor="adm", role="admin",
                              train_vision=True, **BASE_KW)
    assert "train_vision_unauthorized" in str(e.value)
    # admin 独立授权后可通过（仍需其余门禁全绿）
    svc.set_vlm_vision_authorized(True, actor="adm", role="admin")
    run = svc.plan_vlm_training(actor="adm", role="admin",
                                train_vision=True, **BASE_KW)
    assert "--train-vision" in json.loads(run["command_json"])


def test_set_vision_authorized_requires_admin(svc) -> None:
    with pytest.raises(AuthorizationRequired):
        svc.set_vlm_vision_authorized(True, actor="op", role="operator")


# ---------- 冻结命令（MLX-VLM 白名单） ----------

def test_full_plan_generates_frozen_command(svc) -> None:
    _authorize(svc)
    run = svc.plan_vlm_training(actor="adm", role="admin", **BASE_KW)
    assert run["kind"] == "dry_run"
    assert run["status"] == "vlm_dry_run"
    cmd = json.loads(run["command_json"])
    assert cmd[0:3] == ["python3", "-m", "mlx_vlm.lora"]
    for arg in ("--model-path", "--dataset", "--batch-size", "--epochs",
                "--learning-rate", "--grad-checkpoint",
                "--gradient-accumulation-steps", "--train-on-completions",
                "--lora-rank", "--lora-alpha", "--output-path"):
        assert arg in cmd
    # 业务模型名与训练基础模型固定
    plan = json.loads(run["plan_json"])
    assert plan["model_id"] == "qwen3-vl:4b"
    assert plan["base_model"] == "mlx-community/Qwen3-VL-4B-Instruct-4bit"
    # vision 默认冻结：不得出现 --train-vision
    assert "--train-vision" not in cmd


def test_command_never_contains_forbidden_args(svc) -> None:
    from src.training.vlm.train import FORBIDDEN_ARGS, build_mlx_command
    spec = {"model_path": "mlx-community/Qwen3-VL-4B-Instruct-4bit",
            "dataset_path": "ds", "output_dir": "out", "epochs": 1,
            "batch_size": 1, "learning_rate": 1e-5, "lora_rank": 16,
            "lora_alpha": 32, "gradient_accumulation_steps": 1,
            "train_vision": False}
    cmd = build_mlx_command(spec)
    assert not set(cmd) & set(FORBIDDEN_ARGS)
    assert "--use-mps" not in cmd and "--num-epochs" not in cmd


# ---------- 完成即 candidate，不自动发布 ----------

REQUIRED = ("adapter", "config", "loss", "tokens_per_second", "env_lock",
            "data_hash", "model_revision", "error_ledger")


def _artifacts() -> dict:
    return {k: f"{k}-evidence" for k in REQUIRED}


def test_complete_vlm_run_registers_candidate(svc) -> None:
    _authorize(svc)
    run = svc.plan_vlm_training(actor="adm", role="admin", **BASE_KW)
    out = svc.complete_vlm_training(run["run_id"], actor="op",
                                    artifacts=_artifacts())
    assert out["kind"] == "completed_candidate"
    assert out["status"] == "completed_candidate"
    # 发布仍为 none：不得自动发布
    assert out["publish_status"] == "none"
    plan = json.loads(out["plan_json"])
    assert set(plan["artifacts"]) >= set(REQUIRED)
    # 发布仍需独立 admin 审批
    svc.request_publish(run["run_id"], actor="op", role="operator")
    approved = svc.approve_publish(run["run_id"], actor="adm", role="admin")
    assert approved["publish_status"] == "approved"


def test_complete_vlm_run_requires_all_artifacts(svc) -> None:
    _authorize(svc)
    run = svc.plan_vlm_training(actor="adm", role="admin", **BASE_KW)
    bad = _artifacts()
    del bad["env_lock"]
    with pytest.raises(TrainingGovError) as e:
        svc.complete_vlm_training(run["run_id"], actor="op", artifacts=bad)
    assert "env_lock" in str(e.value)


def test_complete_only_for_vlm_plan(svc) -> None:
    from tests.platform.test_m5_training_gov import MANIFEST_OK
    snap = svc.register_snapshot("e2", "v1", "product", MANIFEST_OK,
                                 source_actor="a", source_conclusion="ok")
    run = svc.dry_run(snap["snapshot_id"], actor="op")
    with pytest.raises(TrainingGovError):
        svc.complete_vlm_training(run["run_id"], actor="op",
                                  artifacts=_artifacts())


# ---------- CLI 门禁入口（parse-only，不执行） ----------

def test_lora_cli_blocked(tmp_path: Path) -> None:
    import subprocess
    import sys

    missing = subprocess.run(
        [sys.executable, "-m", "scripts.run_qwen3vl_lora",
         "--preflight-report", str(tmp_path / "nope.json"),
         "--dataset", "ds", "--output-dir", str(tmp_path / "out")],
        capture_output=True, text=True, cwd=str(Path(__file__).parents[2]))
    assert missing.returncode == 2

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"ok": False,
                               "blockers": ["BLOCKED_BY_ACTIVE_TRAINING"]}))
    blocked = subprocess.run(
        [sys.executable, "-m", "scripts.run_qwen3vl_lora",
         "--preflight-report", str(bad),
         "--dataset", "ds", "--output-dir", str(tmp_path / "out")],
        capture_output=True, text=True, cwd=str(Path(__file__).parents[2]))
    assert blocked.returncode == 3

    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"ok": True}))
    frozen = subprocess.run(
        [sys.executable, "-m", "scripts.run_qwen3vl_lora",
         "--preflight-report", str(ok),
         "--dataset", "ds", "--output-dir", str(tmp_path / "out")],
        capture_output=True, text=True, cwd=str(Path(__file__).parents[2]))
    assert frozen.returncode == 4
    payload = json.loads(frozen.stdout)
    assert payload["blocked"] is True
    assert "--lora-rank" in payload["command"]
    assert "--use-mps" not in payload["command"]


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


def _fake_probe(spec):
    from src.platform.api.health import ServiceStatus
    return ServiceStatus(name=spec.name, status="healthy", latency_ms=1,
                         detail="fake")


def test_vlm_plan_api_e2e(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from src.composition.build import build_production_bundle, build_training_router
    from src.platform.api.app import create_app

    monkeypatch.setenv("PLATFORM_USERS", "admin:pw-admin:admin")
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=FakeRecognition(), monitor_adapter=FakeMonitor(),
        label_studio_adapter=FakeLS(), probe=_fake_probe)
    router = build_training_router(bundle)
    app = create_app(services=(), probe=_fake_probe, bundle=bundle,
                     training_router=router, web_dist=tmp_path / "none")
    client = TestClient(app)

    body = {**BASE_KW, "dataset_path": str(tmp_path / "hf"),
            "output_dir": str(tmp_path / "out")}

    # 未登录拒绝
    r0 = client.post("/api/v1/training/runs/vlm/plan", json=body)
    assert r0.status_code in (401, 403)

    r = client.post("/api/v1/auth/login",
                    json={"username": "admin", "password": "pw-admin"})
    h = {"X-CSRF-Token": r.json()["csrf_token"]}

    # 未授权 → 403
    r1 = client.post("/api/v1/training/runs/vlm/plan", json=body, headers=h)
    assert r1.status_code == 403

    # 授权后：证据缺失 → 400；证据齐全 → 200
    assert client.post("/api/v1/training/authorize", json={"value": True},
                       headers=h).status_code == 200
    bad = {**body, "preflight_report": None}
    assert client.post("/api/v1/training/runs/vlm/plan", json=bad,
                       headers=h).status_code == 400
    r2 = client.post("/api/v1/training/runs/vlm/plan", json=body, headers=h)
    assert r2.status_code == 200, r2.text
    assert r2.json()["run"]["status"] == "vlm_dry_run"
