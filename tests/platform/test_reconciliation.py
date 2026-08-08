"""纠偏 Task 1/2：状态纠正 + reconciliation 幂等追加 + 四方对账 fail-closed。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.platform.reconciliation import (
    ReconciliationError,
    ReconciliationService,
    CORRECT_STATUS,
)
from src.platform.data.store import PlatformStore


@pytest.fixture()
def store(tmp_path: Path):
    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _artifact(tmp_path, name="m.pt", content=b"weights"):
    p = tmp_path / name
    p.write_bytes(content)
    return p, hashlib.sha256(content).hexdigest()


def test_register_artifact_idempotent_and_append_only(store, tmp_path):
    p, sha = _artifact(tmp_path)
    svc = ReconciliationService(store)
    a1 = svc.register_artifact(
        artifact_id="nextgen_detector_smoke_v1", kind="model",
        path=str(p), sha256=sha, dataset_manifest_sha="d" * 16,
        source_commit="abc", dirty_diff_hash="x" * 16,
        model_base="yolo11n.pt(public)", label_source="sam_verified_pseudo",
        evidence_level="smoke_pseudo_interim",
        candidate_status="SMOKE_ONLY_NOT_CANDIDATE",
        blocker="1 epoch smoke only", actor="reconciliation",
        run_id="recon-1")
    a2 = svc.register_artifact(
        artifact_id="nextgen_detector_smoke_v1", kind="model",
        path=str(p), sha256=sha, dataset_manifest_sha="d" * 16,
        source_commit="abc", dirty_diff_hash="x" * 16,
        model_base="yolo11n.pt(public)", label_source="sam_verified_pseudo",
        evidence_level="smoke_pseudo_interim",
        candidate_status="SMOKE_ONLY_NOT_CANDIDATE",
        blocker="1 epoch smoke only", actor="reconciliation",
        run_id="recon-2")
    assert a2["duplicate"] is True
    rows = store._conn.execute(
        "SELECT COUNT(*) c FROM model_artifact_registry_v1").fetchone()
    assert rows["c"] == 1  # 幂等不重复插入


def test_hash_conflict_fail_closed(store, tmp_path):
    p, sha = _artifact(tmp_path)
    svc = ReconciliationService(store)
    svc.register_artifact(
        artifact_id="m1", kind="model", path=str(p), sha256=sha,
        dataset_manifest_sha="d" * 16, source_commit="abc",
        dirty_diff_hash="x" * 16, model_base="b", label_source="l",
        evidence_level="e", candidate_status="SMOKE_ONLY_NOT_CANDIDATE",
        blocker="", actor="r", run_id="r1")
    with pytest.raises(ReconciliationError):
        svc.register_artifact(
            artifact_id="m1", kind="model", path=str(p),
            sha256="f" * 64, dataset_manifest_sha="d" * 16,
            source_commit="abc", dirty_diff_hash="x" * 16, model_base="b",
            label_source="l", evidence_level="e",
            candidate_status="SMOKE_ONLY_NOT_CANDIDATE",
            blocker="", actor="r", run_id="r2")


def test_correct_statuses_frozen():
    assert CORRECT_STATUS["m1"] == "SMOKE_ONLY_NOT_CANDIDATE"
    assert CORRECT_STATUS["m2"] == "SMOKE_ONLY_NOT_CANDIDATE"
    assert CORRECT_STATUS["m3_random"] == "INVALID_FOR_BUSINESS_EVAL_LEAKED_SPLIT"
    assert CORRECT_STATUS["m3_grouped"] == "GROUPED_BASELINE_NOT_CANDIDATE"
    assert CORRECT_STATUS["m4_old"] == "PILOT_NOT_EVALUABLE_KB_COVERAGE_ZERO"
    assert CORRECT_STATUS["sam_v1"] == "EXPERIMENTAL_SELF_CONSISTENCY_NOT_CANDIDATE"


def test_four_way_reconciliation(store, tmp_path):
    p, sha = _artifact(tmp_path)
    svc = ReconciliationService(store)
    svc.register_artifact(
        artifact_id="mX", kind="model", path=str(p), sha256=sha,
        dataset_manifest_sha="d" * 16, source_commit="abc",
        dirty_diff_hash="x" * 16, model_base="b", label_source="l",
        evidence_level="e", candidate_status="SMOKE_ONLY_NOT_CANDIDATE",
        blocker="", actor="r", run_id="r1")
    rep = svc.reconcile_artifact("mX")  # 磁盘 sha == DB sha
    assert rep["consistent"] is True
    # 磁盘文件被改 → fail-closed
    p.write_bytes(b"tampered")
    rep2 = svc.reconcile_artifact("mX")
    assert rep2["consistent"] is False
