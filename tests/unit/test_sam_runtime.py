"""SAM runtime 设备门禁契约（手册§一.7 / §五）：
严格 MPS 验证，禁止 PYTORCH_ENABLE_MPS_FALLBACK 与静默 CPU fallback；
候选模型仅限 sam2.1_hiera_small / sam2.1_hiera_base_plus。"""
import pytest

from src.sam_assist import runtime


def test_device_gate_passes_on_mps_machine():
    rep = runtime.device_report()
    assert rep["mps_built"] is True
    assert rep["mps_available"] is True
    assert rep["device"] == "mps"
    assert rep["machine"] == "arm64"
    assert rep["python"] and rep["torch_version"]


def test_fallback_env_var_forbidden():
    """手册§一.7：不允许设置 PYTORCH_ENABLE_MPS_FALLBACK。"""
    env = {"PYTORCH_ENABLE_MPS_FALLBACK": "1"}
    with pytest.raises(runtime.DeviceGateError):
        runtime.check_device_gate(env=env)


def test_gate_fails_closed_when_mps_unavailable(monkeypatch):
    monkeypatch.setattr(runtime, "_mps_available", lambda: False)
    with pytest.raises(runtime.DeviceGateError):
        runtime.check_device_gate(env={})


def test_checkpoint_registry_only_small_and_base_plus():
    """手册§五：不得包含 Large / SAM 3；仅两个候选。"""
    keys = set(runtime.CHECKPOINTS.keys())
    assert keys == {"sam2.1_hiera_small", "sam2.1_hiera_base_plus"}
    for info in runtime.CHECKPOINTS.values():
        assert info["url"].startswith("https://dl.fbaipublicfiles.com/")
        assert info["license"] == "Apache-2.0"
        assert info["repo"] == "facebookresearch/sam2"


def test_embedding_cache_keyed_by_image_sha():
    cache = runtime.EmbeddingCache(max_entries=2)
    cache.put("a" * 64, "emb_a")
    assert cache.get("a" * 64) == "emb_a"
    assert cache.get("b" * 64) is None
    cache.put("b" * 64, "emb_b")
    cache.put("c" * 64, "emb_c")  # 触发淘汰
    assert cache.size() <= 2
