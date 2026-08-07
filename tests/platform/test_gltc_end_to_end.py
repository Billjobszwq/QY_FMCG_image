"""GLTC-011：四训练通道控制链端到端 smoke（无真实训练）。

链路：Dataset Factory（gold=0 诚实）→ lane adapter 校验 →
TrainingControlGraph 状态机 → ReliableWorker 租约/停止 →
评估口径 → candidate 拒绝（指标未达标）。
全程 mock G0，不启动任何真实训练进程。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.modules.dataset_factory import service as factory
from src.modules.training_control import adapters as A
from src.modules.training_control import contracts as C
from src.modules.training_control import evaluation as E
from src.modules.training_control import worker as W
from src.modules.training_control.graph import GraphError, TrainingControlGraph
from src.modules.training_control.hooks import HookRegistry
from src.platform.data.store import PlatformStore

G0_PASS = {"gate_version": "mps_g0_v1", "ok": True,
           "checks": [{"name": "arch_arm64", "ok": True, "detail": "ok"}],
           "evidence": {}}


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def test_end_to_end_control_chain_blocked_by_gold(store, tmp_path):
    # 1. Dataset Factory：gold=0 → admitted=0，不写文件（诚实）
    rep = factory.build_snapshot("detector", rows=[], out_root=tmp_path,
                                 dataset_id="e2e_d1")
    assert rep["admitted"] == 0 and rep["published"] is False

    # 2. Adapter：非 trainable snapshot → BLOCKED_BY_DATASET
    ad = A.get_adapter("detector")
    plan = C.TrainingPlanV2(
        lane="detector", dataset_snapshot_id="e2e_d1",
        base_model_source="public:yolo26m", base_model_revision="r1",
        config_hash="ch", code_commit="cc")
    blockers = ad.validate_plan(plan, snapshot={"trainable": False})
    assert any(b.code == "BLOCKED_BY_DATASET" for b in blockers)

    # 3. Graph：状态机合法路径 + hook 推进 + 非法跃迁拒绝
    g = TrainingControlGraph()
    hooks = HookRegistry()
    rid = g.create_run(lane="detector", plan_id="p_e2e")
    g.advance(rid, "READY_FOR_APPROVAL", actor="admin")
    hooks.emit("HOOK_TRAINING_APPROVAL_REQUIRED", g, rid, actor="system")
    assert g.checkpoint(rid)["waiting_for"] == "human_approval"
    g.advance(rid, "APPROVED", actor="admin")
    g.advance(rid, "QUEUED", actor="admin")
    g.advance(rid, "STARTING", actor="worker")
    hooks.emit("HOOK_RUN_STARTED", g, rid, actor="worker")
    assert g.status(rid) == "RUNNING"
    with pytest.raises(GraphError):
        g.advance(rid, "PUBLISHED", actor="admin")

    # 4. Worker：提交（mock G0）→ 租约 → safe-stop 证据链
    w = W.ReliableWorker(store, hardware_gate=lambda **kw: G0_PASS)
    w.submit_run("runE2E", lane="detector",
                 command=["python3", "-m", "src.training.train_v1",
                          "--parse-check"],
                 env={"X": "1"}, data_hash="d" * 8, code_hash="c" * 8,
                 config_hash="f" * 8, leases=["mps"], actor="admin")
    w.mark_running("runE2E", pid=999999)
    w.request_safe_stop("runE2E", reason="stop_line")
    w.confirm_stopped("runE2E", exit_code=0, checkpoint_saved=True,
                      process_exited=True)
    assert store.get_training_run_v2("runE2E")["status"] == "STOPPED"
    assert store.list_active_leases() == []
    hooks.emit("HOOK_STOP_LINE_TRIGGERED", g, rid, actor="monitor")
    assert g.status(rid) == "STOPPING"

    # 5. 评估：指标未达标 → candidate 拒绝（不粉饰）
    rep_bad = {k: 0.0 for k in E.LANE_MIN_METRICS["detector"]}
    with pytest.raises(E.EvaluationError):
        E.register_candidate("runE2E", "detector", rep_bad,
                             frozen_set_hash="h" * 8,
                             error_ledger=[{"kind": "miss", "count": 1}])


def test_blind_isolation_and_production_untouched(store):
    """红线自检：本轮代码不改 CURRENT bundle、不碰 gold。"""
    from src.modules.training_control import legacy as L
    cap = L.LegacyInferenceCapability()
    cap.assert_use("assisted_proposal")
    with pytest.raises(L.LegacyModelError):
        cap.assert_use("training_parent")
    assert store.list_gold_regions() == []
