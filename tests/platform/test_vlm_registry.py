"""VLM-002：FMCG 级联 8 项 Capability 注册 + 通用运行元数据字段（TDD）。

红线：
- 平台侧字段只描述运行特征（resource_class/residency/meter_units），
  platform 内不得出现 YOLO/SAM/Qwen/FMCG 专有命名；
- adapter 缺失必须 fail-closed；
- 旧式 CapabilitySpec（仅 capability_id/kind）保持默认值兼容。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.composition.build import build_production_bundle
from src.modules.fmcg.cascade.manifest import (
    CAP_DETECT,
    CAP_FAST_SKU,
    CAP_HUMAN,
    CAP_QUALITY,
    CAP_QWEN,
    CAP_RETRIEVE,
    CAP_SAM,
    CAP_SCENE,
    build_fmcg_manifest,
    register_fmcg_cascade,
)
from src.platform.registry import (
    CapabilityRegistry,
    CapabilitySpec,
    RegistryError,
)

EXPECTED_IDS = {
    "vision.quality.assess.v2",
    "vision.scene.classify.v1",
    "vision.detect.product.v1",
    "vision.classify.sku.fast.v1",
    "vision.segment.refine.sam.v1",
    "vision.retrieve.sku.v1",
    "vision.vlm.qwen3vl4b.rerank.v1",
    "vision.human.review.v1",
}


def _fake_adapters() -> dict[str, object]:
    return {cap_id: object() for cap_id in EXPECTED_IDS}


# ---------- manifest 冻结 ----------

def test_fmcg_manifest_declares_all_eight_capabilities() -> None:
    manifest = build_fmcg_manifest()
    assert manifest.module_id == "fmcg.vision.cascade"
    assert manifest.version == "1.0.0"
    ids = {c.capability_id for c in manifest.capabilities}
    assert ids == EXPECTED_IDS


def test_capability_constants_match_frozen_ids() -> None:
    constants = {
        CAP_QUALITY, CAP_SCENE, CAP_DETECT, CAP_FAST_SKU,
        CAP_SAM, CAP_RETRIEVE, CAP_QWEN, CAP_HUMAN,
    }
    assert constants == EXPECTED_IDS


def test_residency_plan_matches_design() -> None:
    """驻留规划：YOLO/ResNet=hot，SAM/OCR/检索=warm，qwen3-vl:4b=cold。"""
    spec_by_id = {c.capability_id: c for c in build_fmcg_manifest().capabilities}
    assert spec_by_id[CAP_QUALITY].residency == "hot"
    assert spec_by_id[CAP_DETECT].residency == "hot"
    assert spec_by_id[CAP_FAST_SKU].residency == "hot"
    assert spec_by_id[CAP_HUMAN].residency == "hot"
    assert spec_by_id[CAP_SCENE].residency == "warm"
    assert spec_by_id[CAP_SAM].residency == "warm"
    assert spec_by_id[CAP_RETRIEVE].residency == "warm"
    assert spec_by_id[CAP_QWEN].residency == "cold"
    # Qwen 按 token + request 计量
    qwen = spec_by_id[CAP_QWEN]
    assert qwen.resource_class == "mlx_vlm"
    assert set(qwen.meter_units) == {"request", "input_token", "output_token"}


# ---------- 注册行为 ----------

def test_register_all_fmcg_capabilities_with_fake_adapters() -> None:
    reg = CapabilityRegistry()
    register_fmcg_cascade(reg, _fake_adapters())
    by_id = {c["capability_id"]: c for c in reg.capabilities()}
    assert EXPECTED_IDS <= set(by_id)
    qwen = by_id[CAP_QWEN]
    assert qwen["residency"] == "cold"
    assert qwen["resource_class"] == "mlx_vlm"
    assert qwen["module_id"] == "fmcg.vision.cascade"
    # capabilities() 必须返回新字段
    assert "meter_units" in qwen


def test_missing_adapter_rejected_fail_closed() -> None:
    reg = CapabilityRegistry()
    adapters = _fake_adapters()
    del adapters[CAP_QWEN]
    with pytest.raises(RegistryError):
        register_fmcg_cascade(reg, adapters)


def test_duplicate_manifest_rejected() -> None:
    reg = CapabilityRegistry()
    register_fmcg_cascade(reg, _fake_adapters())
    with pytest.raises(RegistryError):
        register_fmcg_cascade(reg, _fake_adapters())


# ---------- 通用字段默认值（旧 manifest 兼容） ----------

def test_legacy_capability_spec_keeps_defaults() -> None:
    spec = CapabilitySpec(capability_id="legacy.x", kind="k")
    assert spec.resource_class == "cpu"
    assert spec.residency == "hot"
    assert spec.meter_units == ("call",)


def test_legacy_registry_capabilities_include_default_fields(tmp_path) -> None:
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas"
    )
    for info in bundle.capabilities.capabilities():
        assert info["resource_class"] == "cpu"
        assert info["residency"] == "hot"
        assert info["meter_units"] == ("call",)


def test_bundle_registers_fmcg_manifest_when_adapters_injected(tmp_path) -> None:
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite",
        cas_root=tmp_path / "cas",
        cascade_adapters=_fake_adapters(),
    )
    ids = {c["capability_id"] for c in bundle.capabilities.capabilities()}
    assert EXPECTED_IDS <= ids
    # legacy 能力保持不变
    assert {"legacy.recognition.v2", "legacy.training.monitor",
            "legacy.label_studio"} <= ids


def test_bundle_without_cascade_adapters_keeps_legacy_only(tmp_path) -> None:
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas"
    )
    ids = {c["capability_id"] for c in bundle.capabilities.capabilities()}
    # ABOS T3：基线 = 三个 legacy 能力 + reference.echo 参考模块；
    # 未注入 cascade adapter 时不得出现级联能力。
    assert ids == {"legacy.recognition.v2", "legacy.training.monitor",
                   "legacy.label_studio", "reference.echo"}


# ---------- 依赖方向守卫 ----------

def test_manifest_module_does_not_import_platform_internals() -> None:
    """manifest 只允许依赖 src.platform.registry 的公开契约类型。"""
    path = (
        Path(__file__).resolve().parents[2]
        / "src/modules/fmcg/cascade/manifest.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed = {"src.platform.registry"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "manifest 不得使用相对 import 绕过边界"
            names = [node.module or ""]
        else:
            continue
        for n in names:
            if n.startswith("src.platform"):
                assert n in allowed, f"manifest 越界 import: {n}"


def test_tests_do_not_import_domain_packs() -> None:
    """守卫测试自身只检查 src/platform 源码，不得 import 领域包。"""
    guard = (
        Path(__file__).resolve().parents[1]
        / "platform/test_m2_registry.py"
    )
    text = guard.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            modules = [node.module or ""]
        for m in modules:
            assert not m.startswith("src.modules"), (
                f"守卫测试 import 了领域包: {m}"
            )
