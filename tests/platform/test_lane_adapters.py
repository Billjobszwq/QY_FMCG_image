"""GLTC-005 红测试：四训练 Lane Adapter（任务书 Task 5 / 02 计划 Task 5）。

统一接口：validate_plan / build_command_or_callable / start /
stream_progress / request_safe_stop / collect_artifacts / evaluate。
adapter 返回结构化事件（TrainingEventV1），不只依赖 stdout 文本解析。
"""
from __future__ import annotations

import pytest

from src.modules.training_control import adapters as A
from src.modules.training_control import contracts as C


def _plan(lane, **kw):
    base = dict(lane=lane, dataset_snapshot_id="snap1",
                base_model_source="public:yolo26m",
                base_model_revision="r1", config_hash="ch",
                code_commit="cc")
    base.update(kw)
    return C.TrainingPlanV2(**base)


class TestAdapterRegistry:
    def test_four_adapters_registered(self):
        for lane in ("detector", "classifier", "segmenter", "vlm"):
            ad = A.get_adapter(lane)
            assert ad.lane == lane

    def test_unknown_lane_rejected(self):
        with pytest.raises(A.AdapterError):
            A.get_adapter("ocr")


class TestValidatePlan:
    def test_segmenter_train_without_mask_gold_blocked(self):
        ad = A.get_adapter("segmenter")
        blockers = ad.validate_plan(_plan("segmenter"),
                                    snapshot={"mode": "calibration_only",
                                              "trainable": False})
        codes = {b.code for b in blockers}
        assert "BLOCKED_BY_MASK_GOLD" in codes

    def test_segmenter_calibration_allowed(self):
        ad = A.get_adapter("segmenter")
        blockers = ad.validate_plan(_plan("segmenter"),
                                    snapshot={"mode": "calibration_only",
                                              "trainable": False},
                                    mode="calibration")
        assert all(b.code != "BLOCKED_BY_MASK_GOLD" for b in blockers)

    def test_legacy_parent_blocked_at_adapter(self):
        ad = A.get_adapter("detector")
        with pytest.raises(C.ContractError):
            ad.validate_plan(
                _plan("detector",
                      parent_artifact_id=".models/sku_v4/weights/best.pt"),
                snapshot={"trainable": True})

    def test_vlm_requires_isolated_env_probe(self):
        ad = A.get_adapter("vlm")
        blockers = ad.validate_plan(_plan("vlm",
                                          base_model_source="public:mlx-community/Qwen3-VL-4B-Instruct-4bit"),
                                    snapshot={"trainable": True},
                                    env_probe=lambda: False)
        assert any(b.code == "BLOCKED_BY_ENVIRONMENT" for b in blockers)
        ok = ad.validate_plan(_plan("vlm",
                                    base_model_source="public:mlx-community/Qwen3-VL-4B-Instruct-4bit"),
                              snapshot={"trainable": True},
                              env_probe=lambda: True)
        assert all(b.code != "BLOCKED_BY_ENVIRONMENT" for b in ok)


class TestCommandWhitelist:
    def test_unknown_args_rejected(self):
        ad = A.get_adapter("detector")
        with pytest.raises(A.AdapterError):
            ad.build_command_or_callable(
                _plan("detector"),
                args=["--epochs", "3", "--evil-flag", "1"],
                output_dir="/tmp/new_run_dir")

    def test_existing_output_dir_rejected(self, tmp_path):
        ad = A.get_adapter("detector")
        taken = tmp_path / "taken"
        taken.mkdir()
        with pytest.raises(A.AdapterError):
            ad.build_command_or_callable(
                _plan("detector"), args=["--epochs", "3"],
                output_dir=str(taken))

    def test_vlm_never_uses_ollama_quant_as_base(self):
        ad = A.get_adapter("vlm")
        with pytest.raises(A.AdapterError):
            ad.build_command_or_callable(
                _plan("vlm", base_model_source="ollama:qwen3-vl:4b"),
                args=[], output_dir="/tmp/ng_vlm_x")


class TestStructuredEvents:
    def test_progress_events_are_typed(self):
        ad = A.get_adapter("detector")
        events = ad.stream_progress([
            {"kind": "progress", "payload": {"epoch": 1, "loss": 0.5}},
            {"kind": "garbage line from stdout"} and
            {"kind": "progress", "payload": {"epoch": 2}}])
        assert all(isinstance(e, C.TrainingEventV1) for e in events)
        assert [e.kind for e in events] == ["progress", "progress"]

    def test_safe_stop_returns_stop_request_event(self):
        ad = A.get_adapter("classifier")
        ev = ad.request_safe_stop(run_id="r9", reason="stop_line")
        assert isinstance(ev, C.TrainingEventV1)
        assert ev.kind == "stop_requested"
        # 不得直接伪写 cancelled/终态
        assert ev.payload.get("confirmed") is not True
