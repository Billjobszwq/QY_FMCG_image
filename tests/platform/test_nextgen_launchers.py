"""N2 Task 8：四 Lane 真实 launcher 契约。

- 命令白名单 + 全冻结 hash（command/env/code/config/data/base）；
- 输出目录存在拒绝；新 attempt 新目录，失败 run 不覆盖；
- launch 前重跑真实 G0；lease 获取/释放；heartbeat/事件登记；
- safe-stop：信号→退出证据→终态→释放；不得伪 cancelled。
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.modules.training_control.launchers import (
    LauncherError,
    DetectorLauncher,
    ClassifierLauncher,
    SegmenterLauncher,
    VlmLauncher,
)
from src.modules.training_control.cycle import TrainingCycleService
from src.platform.data.store import PlatformStore

G0_PASS = {"gate_version": "mps_g0_v1", "ok": True,
           "checks": [{"name": "arch_arm64", "ok": True, "detail": "ok"}],
           "evidence": {}}


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _ctx(store, tmp_path):
    svc = TrainingCycleService(store)
    cid = svc.create_cycle(name="c", actor="t")
    pid = svc.register_plan(cid, lane="detector", hypothesis="h",
                            base_revision="public:yolo26m@r1",
                            dataset_hash="d" * 8, budget={"minutes": 5},
                            stop_lines=["x"], eval_set_hash="e" * 8,
                            actor="t")
    return svc, cid, pid


class TestFreezeAndWhitelist:
    def test_unknown_arg_rejected(self, store, tmp_path):
        svc, cid, pid = _ctx(store, tmp_path)
        l = DetectorLauncher(store, hardware_gate=lambda **kw: G0_PASS)
        with pytest.raises(LauncherError, match="白名单"):
            l.prepare(pid, run_name="r1",
                      args=["--epochs", "1", "--evil", "1"],
                      output_root=tmp_path, dataset_dir=tmp_path)

    def test_existing_output_dir_rejected(self, store, tmp_path):
        svc, cid, pid = _ctx(store, tmp_path)
        taken = tmp_path / "runs" / "r1"
        taken.mkdir(parents=True)
        l = DetectorLauncher(store, hardware_gate=lambda **kw: G0_PASS)
        with pytest.raises(LauncherError, match="存在"):
            l.prepare(pid, run_name="r1", args=["--epochs", "1"],
                      output_root=tmp_path, dataset_dir=tmp_path)

    def test_frozen_hashes_recorded(self, store, tmp_path):
        svc, cid, pid = _ctx(store, tmp_path)
        l = DetectorLauncher(store, hardware_gate=lambda **kw: G0_PASS)
        prep = l.prepare(pid, run_name="r1", args=["--epochs", "1"],
                         output_root=tmp_path, dataset_dir=tmp_path)
        for k in ("command_hash", "env_hash", "config_hash",
                  "dataset_hash", "base_revision"):
            assert prep[k], k
        assert prep["output_dir"].endswith("r1")


class TestLaunchGateAndLease:
    def test_launch_reruns_g0_and_acquires_lease(self, store, tmp_path):
        svc, cid, pid = _ctx(store, tmp_path)
        l = DetectorLauncher(store, hardware_gate=lambda **kw: G0_PASS)
        prep = l.prepare(pid, run_name="r1", args=["--epochs", "1"],
                         output_root=tmp_path, dataset_dir=tmp_path,
                         dry_run_cmd=["true"])
        run = l.launch(prep)
        att = svc.get_run_attempt(run["run_id"])
        assert att["status"] in ("STARTING", "RUNNING", "COMPLETED")
        assert "mps" in att["lease_json"]
        # 进程退出后 lease 必须释放
        time.sleep(0.2)
        l.collect_final_state(run["run_id"])
        assert store.list_active_leases() == []

    def test_launch_rejected_when_g0_fails(self, store, tmp_path):
        svc, cid, pid = _ctx(store, tmp_path)
        fail = {**G0_PASS, "ok": False}
        l = DetectorLauncher(store, hardware_gate=lambda **kw: fail)
        prep = l.prepare(pid, run_name="r2", args=["--epochs", "1"],
                         output_root=tmp_path, dataset_dir=tmp_path,
                         dry_run_cmd=["true"])
        with pytest.raises(LauncherError, match="G0"):
            l.launch(prep)

    def test_safe_stop_requires_exit_evidence(self, store, tmp_path):
        svc, cid, pid = _ctx(store, tmp_path)
        l = DetectorLauncher(store, hardware_gate=lambda **kw: G0_PASS)
        prep = l.prepare(pid, run_name="r3", args=["--epochs", "1"],
                         output_root=tmp_path, dataset_dir=tmp_path,
                         dry_run_cmd=["sleep", "30"])
        run = l.launch(prep)
        l.request_safe_stop(run["run_id"])
        att = svc.get_run_attempt(run["run_id"])
        assert att["status"] == "STOPPING"
        # 未确认退出不得写终态
        with pytest.raises(LauncherError):
            l.confirm_stopped(run["run_id"], process_exited=False)


class TestLaneSpecific:
    def test_segmenter_calibration_mode_default(self):
        assert SegmenterLauncher.MODE_DEFAULT == "calibration"

    def test_vlm_requires_isolated_venv(self, store, tmp_path):
        l = VlmLauncher(store, hardware_gate=lambda **kw: G0_PASS,
                        venv_probe=lambda: False)
        svc, cid, pid = _ctx(store, tmp_path)
        with pytest.raises(LauncherError, match="隔离环境"):
            l.prepare(pid, run_name="v1", args=[],
                      output_root=tmp_path, dataset_dir=tmp_path)

    def test_classifier_whitelist(self, store, tmp_path):
        svc, cid, pid = _ctx(store, tmp_path)
        l = ClassifierLauncher(store, hardware_gate=lambda **kw: G0_PASS)
        with pytest.raises(LauncherError, match="白名单"):
            l.prepare(pid, run_name="c1", args=["--bad"],
                      output_root=tmp_path, dataset_dir=tmp_path)
