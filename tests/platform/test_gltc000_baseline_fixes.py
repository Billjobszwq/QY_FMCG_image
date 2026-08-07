"""GLTC-000 红测试：Task 0 基线修复（任务书 §三/§五，执行账本 D2/D3/D4）。

覆盖四个契约：
1. 错误优先级冻结（D3）：计划有效性 → 授权（AuthorizationRequired）→ 硬件 G0；
   未授权时即使 G0 失败也必须先报 AuthorizationRequired。
2. HardwareGateProvider 可注入（D4）：service 不硬绑宿主探针；
   真实 launch 路径（enqueue）必须重跑 provider（真实 G0），不得只信 dry-run 报告。
3. legacy dry-run 追加式 supersession（D2）：被标记 run 禁止批准/入队；
   历史行不改不删。
4. health disabled 服务（D1）：ml_backend legacy/disabled 不探测、不计 degraded。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.modules.training_gov.mps_gate import GATE_VERSION
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

G0_PASS = {
    "gate_version": GATE_VERSION, "ok": True,
    "checks": [{"name": "arch_arm64", "ok": True, "detail": "ok"}],
    "evidence": {},
}
G0_FAIL = {
    "gate_version": GATE_VERSION, "ok": False,
    "checks": [{"name": "power_ac", "ok": False, "detail": "Battery"}],
    "evidence": {},
}


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _svc(store, gate=None):
    calls: list = []

    def provider(**kw):
        calls.append(kw)
        return G0_PASS if gate is None else gate

    svc = TrainingGovernanceService(store, hardware_gate=provider)
    return svc, calls


def _dry(svc, store, gate=None) -> dict:
    snap = svc.register_snapshot("e2", "v1", "product", MANIFEST_OK,
                                 source_actor="a", source_conclusion="ok")
    return svc.dry_run(snap["snapshot_id"], actor="op")


class TestErrorPriorityFrozen:
    """D3：授权门先于硬件 G0 暴露给人。"""

    def test_unauthorized_reports_authorization_before_g0(self, store):
        svc, _ = _svc(store, gate=G0_FAIL)
        run = _dry(svc, store)
        # training_authorized=false（默认）→ 必须 AuthorizationRequired，
        # 而不是 G0 的 TrainingGovError
        with pytest.raises(AuthorizationRequired):
            svc.approve_plan(run["run_id"], actor="adm", role="admin")
        with pytest.raises(AuthorizationRequired):
            svc.start_training(run["run_id"], actor="adm", role="admin")

    def test_authorized_but_g0_fail_reports_hardware(self, store):
        svc, _ = _svc(store, gate=G0_FAIL)
        run = _dry(svc, store)
        svc.set_training_authorized(True, actor="adm", role="admin")
        with pytest.raises(TrainingGovError, match="MPS G0"):
            svc.approve_plan(run["run_id"], actor="adm", role="admin")

    def test_g0_pass_allows_approval(self, store):
        svc, _ = _svc(store, gate=G0_PASS)
        run = _dry(svc, store)
        svc.set_training_authorized(True, actor="adm", role="admin")
        out = svc.approve_plan(run["run_id"], actor="adm", role="admin")
        assert out["status"] == "approved"


class TestHardwareGateInjectable:
    """D4：service 经注入 provider 运行；默认路径仍是真实 run_mps_g0。"""

    def test_default_provider_is_real_gate(self, store):
        from src.modules.training_gov import service as svc_mod
        svc = TrainingGovernanceService(store)
        assert svc._hardware_gate is svc_mod.run_mps_g0 or \
            getattr(svc._hardware_gate, "__wrapped__", None) is not None

    def test_enqueue_reruns_gate_not_stale_report(self, store):
        """launch 路径重跑真实 G0：dry-run 时 pass，enqueue 时 fail → 拒绝。"""
        state = {"rep": G0_PASS}

        def provider(**kw):
            return state["rep"]

        svc = TrainingGovernanceService(store, hardware_gate=provider)
        run = _dry(svc, store)
        svc.set_training_authorized(True, actor="adm", role="admin")
        svc.approve_plan(run["run_id"], actor="adm", role="admin")

        class _Worker:
            def submit(self, *a, **kw):
                raise AssertionError("G0 未通过时不得提交 job")

        state["rep"] = G0_FAIL  # 环境在 dry-run 后恶化
        with pytest.raises(TrainingGovError, match="MPS G0"):
            svc.enqueue_training_job(run["run_id"], actor="adm",
                                     role="admin", worker=_Worker())

    def test_hermetic_fixture_never_touches_host(self, store):
        """注入 provider 的 dry_run 不得调用宿主 torch/sysctl。"""
        svc, calls = _svc(store, gate=G0_PASS)
        _dry(svc, store)
        assert len(calls) == 1  # 只走了注入 provider


class TestLegacyDryRunSupersession:
    """D2：追加式失效账本；被标记 run 禁止批准/入队，历史行保留。"""

    def test_supersession_ledger_append_only(self, store):
        svc, _ = _svc(store)
        run = _dry(svc, store)
        store.supersede_training_run(
            run["run_id"], reason="cli_args_removed",
            superseded_by="training_control_v2", git_commit="test")
        assert store.is_training_run_superseded(run["run_id"])
        # 历史行本身不改：status 仍 dry_run
        raw = store.get_training_run(run["run_id"])
        assert raw["status"] == "dry_run"

    def test_superseded_run_cannot_be_approved_or_enqueued(self, store):
        svc, _ = _svc(store)
        run = _dry(svc, store)
        svc.set_training_authorized(True, actor="adm", role="admin")
        store.supersede_training_run(
            run["run_id"], reason="cli_args_removed",
            superseded_by="training_control_v2", git_commit="test")
        with pytest.raises(TrainingGovError, match="legacy"):
            svc.approve_plan(run["run_id"], actor="adm", role="admin")
        with pytest.raises(TrainingGovError, match="legacy"):
            svc.start_training(run["run_id"], actor="adm", role="admin")

    def test_supersession_row_immutable(self, store):
        svc, _ = _svc(store)
        run = _dry(svc, store)
        store.supersede_training_run(
            run["run_id"], reason="cli_args_removed",
            superseded_by="training_control_v2", git_commit="test")
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute(
                "DELETE FROM training_run_supersession_v1")
        store._conn.commit()


class TestHealthDisabledService:
    """D1：disabled legacy 服务不探测、不计 degraded。"""

    def test_disabled_service_not_probed_and_not_degraded(self):
        from src.platform.api.health import (
            HEALTHY, ServiceSpec, ServiceStatus, aggregate_platform,
            probe_service)
        spec = ServiceSpec("ml_backend", "http://127.0.0.1:1", "/health",
                           critical=False, disabled=True,
                           description="legacy/disabled")

        def _boom(c):
            raise AssertionError("disabled 服务不得发起探测")

        st = probe_service(spec, client=_boom)
        assert st.status == "disabled"
        overall = aggregate_platform([
            (ServiceSpec("recognize", "x", "/h", critical=True),
             ServiceStatus("recognize", HEALTHY)),
            (spec, st)])
        assert overall == HEALTHY

    def test_default_services_marks_ml_backend_disabled(self):
        from src.platform.api.health import DEFAULT_SERVICES
        by_name = {s.name: s for s in DEFAULT_SERVICES}
        assert by_name["ml_backend"].disabled is True
