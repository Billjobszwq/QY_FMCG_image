"""SAM 提示构造（手册§六）：坐标点=正提示，最近相邻 SKU 点=负提示，
固定比例框仅生成粗 ROI（coarse_only=True），不得作为真实框。"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional

from .contracts import InstanceInput

# 未注册 SKU / 新包装的通用商品比例（与 importer 的启发式一致，仅作粗 ROI）
GENERAL_PRODUCT_FRAC = (0.07, 0.18)

PROMPT_CONFIG_VERSION = "pc_v1"


@dataclass(frozen=True)
class PromptConfig:
    """提示参数（扩张比例必须通过配置管理，手册§六.3）。"""
    neg_radius_px: float = 160.0     # 负提示取点半径
    max_negatives: int = 4           # 负提示上限（最近优先）
    roi_expand: float = 1.2          # 粗 ROI 相对比例盒的扩张系数
    version: str = PROMPT_CONFIG_VERSION

    @property
    def config_version(self) -> str:
        payload = f"{self.version}|r={self.neg_radius_px}|n={self.max_negatives}|e={self.roi_expand}"
        return self.version + ":" + hashlib.sha256(payload.encode()).hexdigest()[:8]


@dataclass(frozen=True)
class PromptSet:
    positive_point: tuple            # (x, y)
    positive_label: int              # 恒为 1
    negative_points: tuple           # ((x,y), ...) 最近优先
    negative_labels: tuple           # 全 0
    coarse_box: tuple                # (x1, y1, x2, y2) 像素
    coarse_only: bool                # 恒为 True：粗 ROI 不是真实框
    config_version: str


def build_prompts(instance: InstanceInput,
                  all_instances: list,
                  box_frac_fn: Callable[[str], Optional[tuple]],
                  cfg: PromptConfig) -> PromptSet:
    """构造单个实例的 SAM 提示集。

    box_frac_fn: 注册 SKU 的比例查询（sku_box_frac 语义），返回 None 表示未注册。
    """
    pos = (float(instance.x), float(instance.y))

    # 负提示：同图其他实例（instance_id 不同），半径内最近优先
    negs = []
    for other in all_instances:
        if other.instance_id == instance.instance_id:
            continue
        if (other.x, other.y) == (instance.x, instance.y):
            continue
        d = math.hypot(other.x - instance.x, other.y - instance.y)
        if d <= cfg.neg_radius_px:
            negs.append((d, (float(other.x), float(other.y))))
    negs.sort(key=lambda t: t[0])
    neg_pts = tuple(p for _, p in negs[: cfg.max_negatives])

    # 粗 ROI：注册 SKU 用比例盒，未注册/新包装用通用比例，均不丢弃
    frac = box_frac_fn(instance.sku_raw_name) or GENERAL_PRODUCT_FRAC
    bw = frac[0] * instance.width * cfg.roi_expand
    bh = frac[1] * instance.height * cfg.roi_expand
    x1 = max(0.0, instance.x - bw / 2)
    y1 = max(0.0, instance.y - bh / 2)
    x2 = min(float(instance.width), instance.x + bw / 2)
    y2 = min(float(instance.height), instance.y + bh / 2)

    return PromptSet(
        positive_point=pos,
        positive_label=1,
        negative_points=neg_pts,
        negative_labels=tuple(0 for _ in neg_pts),
        coarse_box=(x1, y1, x2, y2),
        coarse_only=True,
        config_version=cfg.config_version,
    )
