"""VLM-008：Canonical VLM Sample 冻结契约（规格 §10.2）。

每条 sample 必须保留：原图 SHA、原图像素 bbox、图像宽高、Qwen3-VL 0–1000
bbox、sku_id、package_version_id、label source、审核状态证据、split group。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TARGET_TYPES = ("closed_set", "unknown", "new_package", "hard_negative")
LABEL_SOURCES = ("human_final", "gold_verified", "sam_geometry_verified",
                 "model_provisional")
# 只有人工裁决后的金标准可进入正式 train（SAM 几何通过 ≠ human_final）
TRAIN_ELIGIBLE_SOURCES = frozenset({"human_final", "gold_verified"})
REVIEW_STATES = ("train", "reject", "frozen", "manual_pending")
SAMPLE_KINDS = ("region_crop", "full_image", "hard_negative", "unknown",
                "new_package")
SPLITS = ("train", "val", "holdout")


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SplitGroup(_Frozen):
    """防泄漏隔离维度（fail-closed）。"""

    customer: str = Field(min_length=1)
    store: str = Field(min_length=1)
    session: str = Field(min_length=1)
    near_dup_group: str = Field(min_length=1)
    package_version: str = Field(min_length=1)


class VlmSample(_Frozen):
    """Canonical VLM Sample（不可变审计清单条目）。"""

    sample_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    photo_sha256: str = Field(min_length=1)
    image_uri: str = Field(min_length=1)
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    box_px: tuple[float, float, float, float]
    bbox_1000: tuple[int, int, int, int]
    sku_id: str | None = None
    package_version_id: str | None = None
    target_type: Literal["closed_set", "unknown", "new_package", "hard_negative"]
    label_source: Literal["human_final", "gold_verified",
                          "sam_geometry_verified", "model_provisional"]
    sample_weight: float = Field(ge=0.0, default=1.0)
    registry_version: str = Field(min_length=1)
    split: Literal["train", "val", "holdout"]
    split_group: SplitGroup
    sample_kind: Literal["region_crop", "full_image", "hard_negative",
                         "unknown", "new_package"] = "region_crop"
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def closed_set_requires_sku(self) -> "VlmSample":
        if self.target_type in ("closed_set", "hard_negative") and not self.sku_id:
            raise ValueError("closed_set/hard_negative requires sku_id")
        return self

    @model_validator(mode="after")
    def bbox_1000_in_range(self) -> "VlmSample":
        if any(v < 0 or v > 1000 for v in self.bbox_1000):
            raise ValueError("bbox_1000 must be within 0-1000")
        return self
