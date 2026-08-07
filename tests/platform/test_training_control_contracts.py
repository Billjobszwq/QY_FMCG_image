"""GLTC-001 红测试：四训练通道 V2 契约冻结（任务书 Task 1 / 01 文档 §2/§6/§7）。

契约范围：TrainingLane、TrainingPlanV2、TrainingRunV2、TrainingEventV1、
TrainingArtifactV1、ResourceLeaseV1、LaneReadiness/Blocker、DatasetSnapshotV2。
"""
from __future__ import annotations

import pytest

from src.modules.training_control import contracts as C
from src.modules.training_control import vocabulary as V


class TestTrainingLane:
    def test_lanes_frozen_to_four(self):
        assert set(V.TRAINING_LANES) == {
            "detector", "classifier", "segmenter", "vlm"}

    def test_invalid_lane_rejected(self):
        with pytest.raises(C.ContractError):
            C.TrainingPlanV2(
                lane="ocr", dataset_snapshot_id="d1",
                base_model_source="public:coco", base_model_revision="r1",
                config_hash="h", code_commit="c")


class TestLineageIsolation:
    """01 §2.2：parent 只允许 public/foundation base；与 teacher 结构分离。"""

    def _plan(self, **kw):
        base = dict(
            lane="detector", dataset_snapshot_id="d1",
            base_model_source="public:yolo26m", base_model_revision="r1",
            config_hash="h", code_commit="c")
        base.update(kw)
        return C.TrainingPlanV2(**base)

    def test_public_base_allowed(self):
        p = self._plan()
        assert p.lineage_family == "fmcg_nextgen_v1"

    def test_legacy_checkpoint_as_parent_rejected(self):
        for bad in (".models/sku_v4/weights/best.pt",
                    "prod_20260805_v5_r1",
                    ".models/classifier/best.pt",
                    "e2_pilot_run3"):
            with pytest.raises(C.ContractError, match="parent"):
                self._plan(parent_artifact_id=bad)

    def test_legacy_resume_or_ema_rejected(self):
        with pytest.raises(C.ContractError):
            self._plan(resume_from=".models/sku_v6_p1/last.pt")
        with pytest.raises(C.ContractError):
            self._plan(ema_from=".models/sku_v5/weights/best.pt")
        with pytest.raises(C.ContractError):
            self._plan(optimizer_state_from=".models/sku_v4/optim.pt")

    def test_proposal_teacher_only_legacy_prod(self):
        # proposal_teacher 允许生产 bundle（只产 provisional proposal）
        p = self._plan(proposal_teacher_bundle="prod_20260805_v5_r1")
        assert p.proposal_teacher_bundle == "prod_20260805_v5_r1"
        # 但 teacher 不能充当 parent
        with pytest.raises(C.ContractError):
            self._plan(parent_artifact_id="prod_20260805_v5_r1",
                       proposal_teacher_bundle="prod_20260805_v5_r1")

    def test_lineage_fields_complete(self):
        p = self._plan(parent_artifact_id="public:yolo26m@r1")
        d = p.lineage()
        for k in ("lineage_family", "training_lane", "base_model_source",
                  "base_model_revision", "parent_artifact_id",
                  "proposal_teacher_bundle", "dataset_snapshot_id",
                  "code_commit", "config_hash"):
            assert k in d


class TestRunStateMachine:
    def test_states_contain_required(self):
        required = {"DRAFT", "BLOCKED", "READY_FOR_APPROVAL", "APPROVED",
                    "QUEUED", "STARTING", "RUNNING", "STOPPING", "STOPPED",
                    "FAILED", "COMPLETED", "EVALUATING", "CANDIDATE_REJECTED",
                    "CANDIDATE_READY", "SHADOW", "PUBLISH_REQUESTED",
                    "PUBLISHED", "PUBLISH_REJECTED"}
        assert required <= set(V.RUN_STATES)

    def test_legal_transition(self):
        assert V.can_transition("DRAFT", "READY_FOR_APPROVAL")
        assert V.can_transition("RUNNING", "STOPPING")
        assert V.can_transition("STOPPING", "STOPPED")
        assert V.can_transition("COMPLETED", "EVALUATING")

    def test_illegal_transition_rejected(self):
        assert not V.can_transition("DRAFT", "RUNNING")
        assert not V.can_transition("RUNNING", "PUBLISHED")
        assert not V.can_transition("STOPPED", "RUNNING")
        # cancelled 不得冒充已停止：无 CANCELLED 直达终态捷径
        assert "CANCELLED" not in V.RUN_STATES


class TestEventsAndArtifacts:
    def test_event_schema_fields(self):
        e = C.TrainingEventV1(run_id="r1", seq=1, kind="progress",
                              payload={"epoch": 1})
        assert e.schema_version == "training-event.v1"
        with pytest.raises(C.ContractError):
            C.TrainingEventV1(run_id="r1", seq=1, kind="not_a_kind",
                              payload={})

    def test_event_kinds_cover_contract(self):
        assert {"started", "progress", "stop_requested", "stopped",
                "failed", "completed", "checkpoint_saved"} <= set(
                    V.EVENT_KINDS)

    def test_artifact_requires_hashes(self):
        with pytest.raises(C.ContractError):
            C.TrainingArtifactV1(run_id="r1", lane="detector",
                                 artifact_type="checkpoint", path="/x",
                                 sha256="")


class TestResourceLease:
    def test_heavy_resources_and_exclusivity(self):
        assert set(V.HEAVY_RESOURCES) == {"mps", "mlx"}
        # 同 run 不得同时持有 mps 与 mlx
        with pytest.raises(C.ContractError):
            C.validate_lease_set([
                C.ResourceLeaseV1(run_id="r1", resource="mps",
                                  mode="exclusive"),
                C.ResourceLeaseV1(run_id="r1", resource="mlx",
                                  mode="exclusive")])

    def test_heavy_concurrency_one(self):
        a = C.ResourceLeaseV1(run_id="r1", resource="mps",
                              mode="exclusive")
        b = C.ResourceLeaseV1(run_id="r2", resource="mps",
                              mode="exclusive")
        conflicts = C.lease_conflicts([a, b])
        assert conflicts and conflicts[0]["resource"] == "mps"
        # cpu/io 可共享
        c = C.ResourceLeaseV1(run_id="r2", resource="cpu", mode="shared")
        assert C.lease_conflicts([a, c]) == []


class TestReadinessAndSnapshot:
    def test_readiness_blocker_codes(self):
        r = C.LaneReadiness(lane="segmenter", ready=False, blockers=[
            C.Blocker(code="BLOCKED_BY_MASK_GOLD",
                      detail="无真实 mask gold")])
        assert r.blockers[0].code == "BLOCKED_BY_MASK_GOLD"
        assert "BLOCKED_BY_MASK_GOLD" in V.BLOCKER_CODES
        assert "CALIBRATION_ONLY" in V.BLOCKER_CODES

    def test_snapshot_v2_requires_audit_fields(self):
        with pytest.raises(C.ContractError):
            C.DatasetSnapshotV2(lane="detector", snapshot_id="s",
                                manifest_hash="", builder_version="b1",
                                schema_version="detector-snapshot.v1")
        s = C.DatasetSnapshotV2(
            lane="detector", snapshot_id="s", manifest_hash="h" * 8,
            builder_version="b1", schema_version="detector-snapshot.v1",
            split_report={"train": 1, "val": 1},
            exclusion_ledger=[], quality_histogram={},
            source_hashes={"asset_manifest": "x"})
        assert s.lane == "detector"

    def test_snapshot_lane_schema_version_distinct(self):
        # 四快照 schema 独立，不共享错误标签语义
        versions = {C.SNAPSHOT_SCHEMA_BY_LANE[l] for l in V.TRAINING_LANES}
        assert len(versions) == 4


class TestHooks:
    def test_all_required_hooks_defined(self):
        required = {
            "HOOK_DATASET_READY", "HOOK_LABEL_GOLD_READY",
            "HOOK_APPLE_RESOURCE_READY", "HOOK_TRAINING_APPROVAL_REQUIRED",
            "HOOK_RUN_STARTED", "HOOK_RUN_PROGRESS",
            "HOOK_STOP_LINE_TRIGGERED", "HOOK_RUN_FAILED",
            "HOOK_EVALUATION_READY", "HOOK_REGRESSION_BLOCKED",
            "HOOK_SHADOW_READY", "HOOK_PUBLISH_APPROVAL_REQUIRED",
            "HOOK_HUMAN_REVIEW_REQUIRED"}
        assert required <= set(V.HOOK_NAMES)
