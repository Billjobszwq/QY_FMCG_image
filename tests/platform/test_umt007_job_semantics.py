"""UMT-007 红测试：拆分 approve_plan 与 enqueue_training_job。

手册 §3.1 UMT-007 验收口径：
- 「批准训练计划」不消耗算力（不产生任何 job/子进程）；
- 「提交训练 Job」才经 M6 可恢复 Worker 产生 job/attempt/PID/log；
- 两动作语义与状态一致，未批准不得入队。

当前实现 start_training 只改状态不提交 Job，且无 approve/enqueue 拆分，
本测试必须 RED。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.composition.build import build_production_bundle, build_jobs_router
from src.modules.training_gov.service import (
    AuthorizationRequired,
    TrainingGovError,
    TrainingGovernanceService,
)
from src.platform.data.store import PlatformStore

MANIFEST_OK = {
    "train": [
        {"sha256": "a1", "store": "S1", "session": "T1"},
        {"sha256": "a2", "store": "S1", "session": "T1"},
    ],
    "val": [{"sha256": "b1", "store": "S2", "session": "T2"}],
}


class FakeWorker:
    def __init__(self) -> None:
        self.submitted: list[tuple[str, dict]] = []

    def submit(self, kind, payload, max_attempts=3):
        self.submitted.append((kind, payload))
        return f"job-fake-{len(self.submitted)}"


FAKE_G0 = {"gate_version": "g0-fake", "ok": True,
           "checks": [{"name": "fake_unit_evidence", "ok": True}],
           "evidence": {"note": "hermetic unit test fake G0"}}


@pytest.fixture()
def svc(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield TrainingGovernanceService(s, hardware_gate=lambda **kw: FAKE_G0)
    s.close()


def _dry(svc):
    snap = svc.register_snapshot("e2", "v1", "product", MANIFEST_OK,
                                 source_actor="a", source_conclusion="ok")
    return svc.dry_run(snap["snapshot_id"], actor="op")


class TestApprovePlan:
    def test_approve_requires_authorization(self, svc):
        run = _dry(svc)
        with pytest.raises(AuthorizationRequired):
            svc.approve_plan(run["run_id"], actor="adm", role="admin")

    def test_approve_no_job_no_compute(self, svc):
        """批准只落状态，不提交 job（不消耗算力）。"""
        run = _dry(svc)
        worker = FakeWorker()
        svc.set_training_authorized(True, actor="adm", role="admin")
        out = svc.approve_plan(run["run_id"], actor="adm", role="admin",
                               worker=worker)
        assert out["status"] == "approved"
        assert out["approved_by"] == "adm"
        assert worker.submitted == [], "批准阶段不得产生 job"


class TestEnqueueTrainingJob:
    def test_enqueue_requires_approved(self, svc):
        run = _dry(svc)
        svc.set_training_authorized(True, actor="adm", role="admin")
        with pytest.raises(TrainingGovError):
            svc.enqueue_training_job(run["run_id"], actor="adm", role="admin",
                                     worker=FakeWorker())

    def test_enqueue_creates_job_with_run_command(self, svc):
        run = _dry(svc)
        worker = FakeWorker()
        svc.set_training_authorized(True, actor="adm", role="admin")
        svc.approve_plan(run["run_id"], actor="adm", role="admin",
                         worker=worker)
        out = svc.enqueue_training_job(run["run_id"], actor="adm",
                                       role="admin", worker=worker)
        assert out["status"] == "queued" and out["job_id"]
        kind, payload = worker.submitted[-1]
        assert kind == "training.run"
        assert payload["command"] == json.loads(run["command_json"])
        assert payload["run_id"] == run["run_id"]
        assert svc.get_run(run["run_id"])["job_id"] == out["job_id"]


class TestWorkerExecution:
    def test_training_handler_produces_pid_and_log(self, tmp_path, monkeypatch):
        """training.run handler：真实子进程，留 PID 与日志文件。"""
        monkeypatch.setenv("PLATFORM_RUNS_ROOT", str(tmp_path / ".runs"))
        bundle = build_production_bundle(
            db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
            recognition_adapter=None, monitor_adapter=None,
            label_studio_adapter=None,
            probe=lambda spec: None)
        worker, _router = build_jobs_router(bundle)
        assert "training.run" in worker._handlers
        jid = worker.submit("training.run", {
            "run_id": "run-x", "command": ["/usr/bin/true"]})
        out = worker.poll()
        assert out and out[0]["status"] == "succeeded"
        job = bundle.store.get_job(jid)
        result = json.loads(job["result_json"] or "{}")
        assert result.get("pid"), "必须记录子进程 PID"
        log = Path(result["log"])
        assert log.exists(), "必须保留训练日志文件"
        attempts = bundle.store.list_attempts(jid)
        assert attempts and attempts[0]["status"] == "succeeded"
