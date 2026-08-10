"""P1-2 红测试：业务单测不得依赖真实 MPS。

证明：真实 G0 失败（无 MPS 沙箱语义）时，未注入 hardware_gate 的
service 在 enqueue 失败；显式注入 fake G0 evidence 后业务语义通过。
生产 _require_g0 逻辑不放宽。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.modules.training_gov import service as svc_mod
from src.modules.training_gov.service import (
    TrainingGovError,
    TrainingGovernanceService,
)
from src.platform.data.store import PlatformStore
from tests.platform.test_umt007_job_semantics import FakeWorker, MANIFEST_OK

FAKE_G0_OK = {"gate_version": "g0-fake", "ok": True,
              "checks": [{"name": "fake_unit_evidence", "ok": True}],
              "evidence": {"note": "explicit fake G0 for hermetic unit test"}}

G0_FAIL = {"gate_version": "g0-fake", "ok": False,
           "checks": [{"name": "mps_present", "ok": False}],
           "evidence": {"note": "simulated no-MPS sandbox"}}


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _run(svc):
    snap = svc.register_snapshot("e2", "v1", "product", MANIFEST_OK,
                                 source_actor="a", source_conclusion="ok")
    return svc.dry_run(snap["snapshot_id"], actor="op")


def test_uninjected_service_fails_without_mps(store, monkeypatch):
    """红：模拟无 MPS（真实 G0 返回 ok=False）且未注入 → enqueue 被 G0 门拦。"""
    monkeypatch.setattr(svc_mod, "run_mps_g0", lambda **kw: G0_FAIL)
    svc = TrainingGovernanceService(store)
    run = _run(svc)
    svc.set_training_authorized(True, actor="adm", role="admin")
    with pytest.raises(TrainingGovError):
        # 无 MPS 且未注入：approve 阶段即被 G0 门拦（业务测试不应到此）
        svc.approve_plan(run["run_id"], actor="adm", role="admin",
                         worker=FakeWorker())


def test_injected_fake_g0_keeps_business_semantics(store, monkeypatch):
    """绿路径：显式 fake G0 evidence → 无 MPS 环境业务语义仍通过。"""
    monkeypatch.setattr(svc_mod, "run_mps_g0", lambda **kw: G0_FAIL)
    svc = TrainingGovernanceService(store,
                                    hardware_gate=lambda **kw: FAKE_G0_OK)
    run = _run(svc)
    worker = FakeWorker()
    svc.set_training_authorized(True, actor="adm", role="admin")
    svc.approve_plan(run["run_id"], actor="adm", role="admin", worker=worker)
    out = svc.enqueue_training_job(run["run_id"], actor="adm", role="admin",
                                   worker=worker)
    assert out["status"] == "queued"
    assert len(worker.submitted) == 1
