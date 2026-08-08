"""SLTF P0-1：SAM mask loss 可导实现。

soft Dice 基于概率（sigmoid 后）计算，梯度可回传到 logits；
二值 Dice 只作为评估 metric，不参与训练。
loss = bce_weight * BCE + dice_weight * soft_dice；权重进 run manifest。
"""
from __future__ import annotations

import torch
import torch.nn.functional as TF

BCE_WEIGHT = 1.0
DICE_WEIGHT = 1.0
EPS = 1e-6


def soft_dice_loss(logits: torch.Tensor, gt: torch.Tensor,
                   eps: float = EPS) -> torch.Tensor:
    """可导 soft Dice loss ∈ [0,1]。

    用 sigmoid(logits) 的概率值计算交集/并集期望，避免阈值切断梯度。
    """
    p = torch.sigmoid(logits)
    dims = tuple(range(1, p.ndim))
    inter = (p * gt).sum(dims)
    card = p.sum(dims) + gt.sum(dims)
    dice = (2 * inter + eps) / (card + eps)
    return (1 - dice).mean()


def sam_mask_loss(logits: torch.Tensor, gt: torch.Tensor,
                  bce_weight: float = BCE_WEIGHT,
                  dice_weight: float = DICE_WEIGHT) -> torch.Tensor:
    p = torch.sigmoid(logits)
    bce = TF.binary_cross_entropy(p, gt, reduction="mean")
    return bce_weight * bce + dice_weight * soft_dice_loss(logits, gt)


def _manifest_defaults() -> dict:
    return {"bce_weight": BCE_WEIGHT, "dice_weight": DICE_WEIGHT,
            "dice_kind": "soft", "binary_dice_role": "metric_only"}


sam_mask_loss.manifest_defaults = _manifest_defaults  # type: ignore[attr-defined]


def binary_dice_metric(pred: torch.Tensor, gt: torch.Tensor,
                       eps: float = EPS) -> float:
    """二值 Dice **distance**（仅 metric，禁入训练图）。0=完全一致，1=不相交。"""
    pb = (pred > 0.5).float()
    inter = (pb * gt).sum()
    card = pb.sum() + gt.sum()
    return float(1 - (2 * inter + eps) / (card + eps))
