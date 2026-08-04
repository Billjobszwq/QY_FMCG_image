"""UMT-005 红测试：MPS G0 必须真实实测，禁止 `sys.platform == "darwin"` 假判。

手册 §3.1 UMT-005 验收口径：实测 arm64、torch MPS built/available、
1024² 矩阵、模型一轮前向、无 CPU fallback、AC 电源、内存/swap/磁盘；
证据写入 run；任一失败训练保持禁用并输出具体失败项。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from src.modules.training_gov import mps_gate
from src.modules.training_gov.mps_gate import GATE_VERSION, run_mps_g0
from src.modules.training_gov.service import (
    TrainingGovError,
    TrainingGovernanceService,
)
from src.platform.data.store import PlatformStore

REQUIRED_CHECKS = {
    "arch_arm64", "torch_mps_built", "torch_mps_available",
    "matrix_1024x1024", "model_forward", "no_cpu_fallback",
    "power_ac", "memory", "disk_free", "swap_report",
}

MANIFEST_OK = {
    "train": [
        {"sha256": "a1", "store": "S1", "session": "T1"},
        {"sha256": "a2", "store": "S1", "session": "T1"},
    ],
    "val": [{"sha256": "b1", "store": "S2", "session": "T2"}],
}


@pytest.fixture()
def svc(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield TrainingGovernanceService(s)
    s.close()


class TestG0RealChecks:
    def test_g0_reports_all_required_checks(self):
        rep = run_mps_g0(disk_root=".")
        assert rep["gate_version"] == GATE_VERSION
        names = {c["name"] for c in rep["checks"]}
        assert REQUIRED_CHECKS <= names, f"缺检查项: {REQUIRED_CHECKS - names}"
        ev = rep["evidence"]
        assert "power_source" in ev and "memory" in ev and "disk" in ev
        # 每个失败项必须给出具体 detail
        assert all(c["detail"] for c in rep["checks"])

    def test_g0_is_not_fake_platform_check(self, monkeypatch):
        """非 arm64 架构必须失败，即使 sys.platform == 'darwin'。"""
        monkeypatch.setattr(mps_gate.platform, "machine", lambda: "x86_64")
        rep = run_mps_g0(disk_root=".")
        by_name = {c["name"]: c for c in rep["checks"]}
        assert by_name["arch_arm64"]["ok"] is False
        assert rep["ok"] is False

    def test_g0_rejects_cpu_fallback_env(self, monkeypatch):
        monkeypatch.setenv("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        rep = run_mps_g0(disk_root=".")
        by_name = {c["name"]: c for c in rep["checks"]}
        assert by_name["no_cpu_fallback"]["ok"] is False
        assert rep["ok"] is False

    def test_g0_battery_blocks_training(self, monkeypatch):
        monkeypatch.setattr(mps_gate, "power_source", lambda: "Battery Power")
        rep = run_mps_g0(disk_root=".")
        by_name = {c["name"]: c for c in rep["checks"]}
        assert by_name["power_ac"]["ok"] is False
        assert rep["ok"] is False

    @pytest.mark.skipif(sys.platform != "darwin", reason="主机门控：仅 macOS")
    def test_host_real_gate_with_ac_power(self, monkeypatch):
        """主机实测：AC 电源下全项应通过（矩阵/前向真实跑在 mps）。"""
        if mps_gate.power_source() != "AC Power":
            pytest.skip("未接 AC 电源，跳过主机全绿断言")
        rep = run_mps_g0(disk_root=".")
        assert rep["ok"] is True, json.dumps(
            [c for c in rep["checks"] if not c["ok"]], ensure_ascii=False)


class TestDryRunWiring:
    def test_dry_run_records_real_g0_evidence(self, svc):
        snap = svc.register_snapshot("e2", "v1", "product", MANIFEST_OK,
                                     source_actor="a", source_conclusion="ok")
        run = svc.dry_run(snap["snapshot_id"], actor="op")
        plan = json.loads(run["plan_json"])
        assert "mps_g0_report" in plan, "证据必须写入 run"
        rep = plan["mps_g0_report"]
        assert rep["gate_version"] == GATE_VERSION
        assert plan["mps_g0"] == rep["ok"]

    def test_start_blocked_when_g0_fails(self, svc, monkeypatch):
        """任一 G0 检查失败 → 训练启动保持禁用（UMT-005）。"""
        failing = {
            "gate_version": GATE_VERSION, "ok": False,
            "checks": [{"name": "power_ac", "ok": False,
                        "detail": "Battery Power"}],
            "evidence": {},
        }
        monkeypatch.setattr(
            "src.modules.training_gov.service.run_mps_g0",
            lambda **kw: failing)
        snap = svc.register_snapshot("e2", "v1", "product", MANIFEST_OK,
                                     source_actor="a", source_conclusion="ok")
        run = svc.dry_run(snap["snapshot_id"], actor="op")
        plan = json.loads(run["plan_json"])
        assert plan["mps_g0"] is False
        svc.set_training_authorized(True, actor="adm", role="admin")
        with pytest.raises(TrainingGovError, match="MPS G0"):
            svc.start_training(run["run_id"], actor="adm", role="admin")
