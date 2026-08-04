"""U0-2 / U1-004 红测试：演示 Snapshot 必须可标记为不可训练。

手册 U0 与 UMT-004 口径：
- 演示 Snapshot（2 train + 1 val 样板 manifest）不得参与训练门禁；
- 标记动作不物理删除（红线），状态在 DB 与 gates 一致；
- 标记后 dry_run/gates 必须排除该 Snapshot。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.modules.training_gov.service import (
    TrainingGovError,
    TrainingGovernanceService,
)
from src.platform.data.store import PlatformStore

from tests.platform.test_m5_training_gov import MANIFEST_OK


@pytest.fixture()
def svc(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield TrainingGovernanceService(s)
    s.close()


def test_mark_snapshot_demo_excludes_from_gates(svc) -> None:
    snap = svc.register_snapshot("demo", "v1", "product", MANIFEST_OK,
                                 source_actor="a", source_conclusion="演示")
    assert svc.gates()["registered_snapshots"] == 1
    out = svc.mark_snapshot_demo(snap["snapshot_id"], actor="auditor")
    assert out["trainable"] == 0
    assert out["status_note"]
    # gates 不得再把它算作可训练 Snapshot
    assert svc.gates()["registered_snapshots"] == 0
    assert svc.gates()["can_dry_run"] is False


def test_dry_run_rejects_demo_snapshot(svc) -> None:
    snap = svc.register_snapshot("demo", "v1", "product", MANIFEST_OK,
                                 source_actor="a", source_conclusion="演示")
    svc.mark_snapshot_demo(snap["snapshot_id"], actor="auditor")
    with pytest.raises(TrainingGovError):
        svc.dry_run(snap["snapshot_id"], actor="op")


def test_mark_is_audit_trail_not_deletion(svc) -> None:
    snap = svc.register_snapshot("demo", "v1", "product", MANIFEST_OK,
                                 source_actor="a", source_conclusion="演示")
    svc.mark_snapshot_demo(snap["snapshot_id"], actor="auditor")
    # 不物理删除：仍可查询，manifest 保留
    got = svc.get_snapshot(snap["snapshot_id"])
    assert got is not None
    assert got["manifest_hash"] == snap["manifest_hash"]
    assert got["trainable"] == 0
    # 幂等：重复标记不报错
    svc.mark_snapshot_demo(snap["snapshot_id"], actor="auditor")
