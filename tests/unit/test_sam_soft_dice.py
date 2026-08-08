"""SLTF P0-1：SAM Dice 必须可导（soft Dice），二值 Dice 仅作 metric。"""
from __future__ import annotations

import torch

from src.modules.nextgen_data.sam_losses import (
    binary_dice_metric,
    sam_mask_loss,
    soft_dice_loss,
)


def test_soft_dice_zero_when_perfect():
    gt = torch.zeros(1, 64, 64)
    gt[:, :, 16:48] = 1.0
    logits = torch.where(gt > 0, torch.tensor(10.0), torch.tensor(-10.0))
    assert soft_dice_loss(logits, gt).item() < 1e-3


def test_soft_dice_one_when_disjoint():
    gt = torch.zeros(1, 64, 64)
    gt[:, :, :16] = 1.0
    logits = torch.where(gt > 0, torch.tensor(-10.0), torch.tensor(10.0))
    assert soft_dice_loss(logits, gt).item() > 0.95


def test_loss_non_negative():
    rng = torch.Generator().manual_seed(0)
    gt = (torch.rand(4, 32, 32, generator=rng) > 0.5).float()
    logits = torch.randn(4, 32, 32, generator=rng)
    assert (soft_dice_loss(logits, gt) >= 0).all()
    total = sam_mask_loss(logits, gt)
    assert total.item() >= 0


def test_gradient_flows_to_logits():
    gt = torch.zeros(1, 32, 32)
    gt[:, :, 8:24] = 1.0
    logits = torch.randn(1, 32, 32, requires_grad=True)
    loss = soft_dice_loss(logits, gt)
    loss.backward()
    assert logits.grad is not None
    assert logits.grad.abs().sum() > 0, "阈值二值化会切断梯度（P0-1）"


def test_empty_mask_numerically_stable():
    gt = torch.zeros(1, 32, 32)
    logits = torch.full((1, 32, 32), -5.0, requires_grad=True)
    loss = soft_dice_loss(logits, gt)
    assert torch.isfinite(loss)
    loss.backward()
    assert torch.isfinite(logits.grad).all()


def test_loss_weights_in_manifest():
    m = sam_mask_loss.manifest_defaults()
    assert m["bce_weight"] == 1.0 and m["dice_weight"] == 1.0


def test_binary_dice_only_as_metric():
    gt = torch.zeros(1, 32, 32)
    gt[:, :, 8:24] = 1.0
    pred = gt.clone()
    assert binary_dice_metric(pred, gt) == 0.0
    assert binary_dice_metric(1 - gt, gt) == 1.0
