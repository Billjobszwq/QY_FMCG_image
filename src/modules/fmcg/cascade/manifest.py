"""VLM-002：FMCG Vision Cascade 能力清单（Manifest）。

红线：
- 本模块只返回 ModuleManifest 与注册帮助函数；平台组合根负责注入 adapter。
- src/platform 不得 import 本模块；依赖方向只能由组合根（src/composition）装配。
- 8 项能力 ID 为冻结值，不得随意增删改名（规格 2026-08-06 设计文档）。
"""

from __future__ import annotations

from typing import Any, Mapping

from src.platform.registry import (
    CapabilityRegistry,
    CapabilitySpec,
    ModuleManifest,
    RegistryError,
)

CAP_QUALITY = "vision.quality.assess.v2"
CAP_SCENE = "vision.scene.classify.v1"
CAP_DETECT = "vision.detect.product.v1"
CAP_FAST_SKU = "vision.classify.sku.fast.v1"
CAP_SAM = "vision.segment.refine.sam.v1"
CAP_RETRIEVE = "vision.retrieve.sku.v1"
CAP_QWEN = "vision.vlm.qwen3vl4b.rerank.v1"
CAP_HUMAN = "vision.human.review.v1"

FMCG_CASCADE_MODULE_ID = "fmcg.vision.cascade"
FMCG_CASCADE_MODULE_VERSION = "1.0.0"


def build_fmcg_manifest() -> ModuleManifest:
    return ModuleManifest(
        module_id=FMCG_CASCADE_MODULE_ID,
        name="FMCG Vision Cascade",
        version=FMCG_CASCADE_MODULE_VERSION,
        capabilities=[
            CapabilitySpec(
                capability_id=CAP_QUALITY,
                kind="quality_assessment",
                description="Versioned quality and evidence assessment",
                resource_class="cpu",
                residency="hot",
                meter_units=("photo",),
            ),
            CapabilitySpec(
                capability_id=CAP_SCENE,
                kind="scene_classification",
                description="Scene and price-tag presence classification",
                resource_class="mps_light",
                residency="warm",
                meter_units=("photo",),
            ),
            CapabilitySpec(
                capability_id=CAP_DETECT,
                kind="product_detection",
                description="YOLO product localization",
                resource_class="mps_medium",
                residency="hot",
                meter_units=("photo", "region"),
            ),
            CapabilitySpec(
                capability_id=CAP_FAST_SKU,
                kind="sku_classification",
                description="Fast closed-set SKU classification",
                resource_class="mps_light",
                residency="hot",
                meter_units=("region",),
            ),
            CapabilitySpec(
                capability_id=CAP_SAM,
                kind="mask_refinement",
                description="SAM mask and crop refinement",
                resource_class="mps_medium",
                residency="warm",
                meter_units=("region", "mask"),
            ),
            CapabilitySpec(
                capability_id=CAP_RETRIEVE,
                kind="sku_retrieval",
                description="OCR, attributes and vector candidate retrieval",
                resource_class="mixed",
                residency="warm",
                meter_units=("region", "candidate"),
            ),
            CapabilitySpec(
                capability_id=CAP_QWEN,
                kind="vlm_rerank",
                description="Qwen3-VL 4B closed-set SKU reranker",
                resource_class="mlx_vlm",
                residency="cold",
                meter_units=("request", "input_token", "output_token"),
            ),
            CapabilitySpec(
                capability_id=CAP_HUMAN,
                kind="human_review",
                description="Auditable human review handoff",
                resource_class="human",
                residency="hot",
                meter_units=("task",),
            ),
        ],
    )


def register_fmcg_cascade(
    registry: CapabilityRegistry, adapters: Mapping[str, Any]
) -> None:
    """由组合根调用：注册 FMCG 清单；任一 adapter 缺失时 fail-closed。"""
    manifest = build_fmcg_manifest()
    missing = [
        cap.capability_id
        for cap in manifest.capabilities
        if cap.capability_id not in adapters
    ]
    if missing:
        raise RegistryError(
            "FMCG 级联 adapter 缺失（fail-closed）: " + ", ".join(sorted(missing))
        )
    registry.register(manifest, adapters)
