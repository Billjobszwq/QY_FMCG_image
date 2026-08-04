"""SAM 辅助标注输入与候选契约（手册§六）。

InstanceInput 是坐标点实例的最小输入契约；SamCandidate 是 SAM multimask
输出候选的统一结构。所有字段显式声明，禁止隐式默认。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class InstanceInput:
    """单个商品实例的输入（手册§六第一段）。"""
    asset_id: str
    photo_id: str
    image_sha256: str
    width: int
    height: int
    instance_id: str
    x: float
    y: float
    sku_raw_name: str = ""
    sku_canonical: Optional[str] = None
    quality_version: str = ""


@dataclass
class SamCandidate:
    """SAM multimask 输出的单个候选（手册§六.5）。

    reject_reasons 由 candidates.filter_candidates 填写；非空即降级人工。"""
    candidate_id: str
    mask: np.ndarray                     # HxW uint8，0/1
    iou_score: float
    stability_score: float
    area_px: float = 0.0
    bbox: Optional[tuple] = None         # (x1, y1, x2, y2) 像素
    centroid: Optional[tuple] = None
    reject_reasons: list = field(default_factory=list)
    downgraded: bool = False
