"""分类器增量微调（低温微调）：冻结骨干网络，仅训练分类头。

可持续闭环的关键：YOLO 画框器永不变；分类器在发现新的易混淆 SKU 时，
只需把困难 SKU 抠图补充到 crop_dataset 对应文件夹，然后执行本脚本快速微调。

策略：
  - 加载已训练的 classifier best.pt（学到的骨干权重）
  - 冻结骨干，仅训练分类头
  - lr=1e-4（低温），15-20 轮
  - 每次仅需 10-20 分钟算力

用法：python -m src.cascade.finetune [--epochs 20] [--lr 1e-4] [--init-from best.pt]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import WeightedRandomSampler
from torchvision import datasets, transforms

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT
from .classifier import build_model, get_datasets, build_sampler, freeze_backbone, _plot_curves

CROP_DIR = PROJECT_ROOT / "crop_dataset"
OUT_DIR = PROJECT_ROOT / ".models" / "classifier"


def finetune(init_from: str = None, epochs: int = 20, lr: float = 1e-4,
             batch: int = 64, size: int = 224, patience: int = 8, run_tag: str = "_ft",
             data_dir: str = None, full: bool = False):
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    init_path = Path(init_from) if init_from else OUT_DIR / "best.pt"
    if not init_path.exists():
        raise FileNotFoundError(f"未找到初始权重 {init_path}，请先完成分类器基础训练")

    train_ds, val_ds = get_datasets(size, data_dir)
    # 加载已训练权重
    ckpt = torch.load(str(init_path), map_location=device, weights_only=False)
    backbone = ckpt.get("backbone", "resnet18")
    classes = ckpt["classes"]
    n_classes = ckpt["n_classes"]
    # RA-012：续训前强制校验 ordered class mapping 与 checkpoint 完全一致，
    # 否则索引→类别映射错位会静默产生错误模型。
    ds_classes = list(train_ds.classes)
    if ds_classes != list(classes):
        raise ValueError(
            "类别映射不一致，拒绝续训（RA-012）：\n"
            f"  数据集 {len(ds_classes)} 类 vs checkpoint {len(classes)} 类\n"
            f"  首个差异: " + next(
                (f"位置{i}: 数据={a!r} ckpt={b!r}" for i, (a, b) in
                 enumerate(zip(ds_classes, classes)) if a != b),
                "数量不同"))
    model = build_model(backbone, n_classes).to(device)
    model.load_state_dict(ckpt["model"])
    # 冻结骨干仅训分类头；--full 则全量微调（用于修复抠图域偏移）
    if not full:
        freeze_backbone(model, backbone)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"=== 分类器{'全量' if full else '增量'}微调（低温）===")
    print(f"  初始化自: {init_path}")
    print(f"  数据: {data_dir}")
    print(f"  骨干: {backbone} | 设备: {device}")
    print(f"  可训练参数: {trainable:,} / {total:,} ({'全部' if full else '仅分类头'})")
    print(f"  lr={lr}, epochs={epochs}, batch={batch}")

    sampler = build_sampler(train_ds)
    train_loader = torch.utils.data.DataLoader(train_ds, batch_size=batch, sampler=sampler, num_workers=4, pin_memory=True)
    val_loader = torch.utils.data.DataLoader(val_ds, batch_size=batch, shuffle=False, num_workers=4, pin_memory=True)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(filter(lambda p: p.requires_grad, model.parameters()), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    def _eval_val() -> tuple[float, float]:
        model.eval()
        vc, vt, vl = 0, 0, 0.0
        with torch.no_grad():
            for imgs, labels in val_loader:
                imgs, labels = imgs.to(device), labels.to(device)
                out = model(imgs)
                vl += criterion(out, labels).item() * imgs.size(0)
                vc += (out.argmax(1) == labels).sum().item()
                vt += imgs.size(0)
        return (vc / vt if vt else 0.0), (vl / vt if vt else 0.0)

    history = []
    # RA-012：以旧模型在新验证集上的实测作为 best 基准（而非历史 val_acc 或 0），
    # 避免第一轮就“提升”并覆盖真正的旧最佳权重。
    if data_dir:
        baseline_acc, _ = _eval_val()
        print(f"  旧模型在新验证集基线: val_acc={baseline_acc:.4f}（RA-012 基准）")
    else:
        baseline_acc = float(ckpt.get("val_acc", 0.0))
    best_acc = baseline_acc
    best_epoch = 0
    no_improve = 0
    t0 = time.time()
    for epoch in range(1, epochs + 1):
        model.train()
        run_loss, run_correct, run_total = 0.0, 0, 0
        for imgs, labels in train_loader:
            imgs, labels = imgs.to(device), labels.to(device)
            optimizer.zero_grad()
            out = model(imgs)
            loss = criterion(out, labels)
            loss.backward()
            optimizer.step()
            run_loss += loss.item() * imgs.size(0)
            run_correct += (out.argmax(1) == labels).sum().item()
            run_total += imgs.size(0)
        scheduler.step()
        train_acc = run_correct / run_total
        train_loss = run_loss / run_total if run_total else 0.0

        val_acc, val_loss = _eval_val()
        history.append({"epoch": epoch, "train_loss": round(train_loss, 4),
                        "train_acc": round(train_acc, 4), "val_acc": round(val_acc, 4),
                        "val_loss": round(val_loss, 4)})
        print(f"  ep{epoch}: train_acc={train_acc:.4f} val_acc={val_acc:.4f} val_loss={val_loss:.4f}", flush=True)
        if val_acc > best_acc:
            best_acc = val_acc
            best_epoch = epoch
            no_improve = 0
            # RA-012：永远先写新版本文件，再原子替换 best.pt；被替换的旧权重保留备份，
            # 绝不出现“第一轮就覆盖旧最佳”的丢失。
            ts = time.strftime("%Y%m%d_%H%M%S")
            versioned = OUT_DIR / f"best_ft_{ts}.pt"
            torch.save({"model": model.state_dict(), "backbone": backbone, "n_classes": n_classes,
                        "classes": classes, "val_acc": val_acc, "epoch": epoch, "finetuned": True,
                        "init_from": str(init_path), "baseline_acc": baseline_acc},
                       versioned)
            target = OUT_DIR / "best.pt"
            if target.exists():
                shutil.copy2(target, OUT_DIR / f"best_replaced_{ts}.pt")
            os.replace(versioned, target)
            print(f"    ★ 刷新最佳 val_acc={val_acc:.4f}，已保存（旧权重已备份）")
        else:
            no_improve += 1
        if no_improve >= patience:
            print(f"  ⏹ 早停（连续 {patience} 轮未提升）")
            break

    (OUT_DIR / f"finetune_history{run_tag}.json").write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    _plot_curves(history, run_tag)
    elapsed = time.time() - t0
    print(f"\n=== 微调完成 ({elapsed:.0f}s ≈ {elapsed/60:.1f} 分钟) ===")
    print(f"  最佳 val_acc: {best_acc:.4f} (epoch {best_epoch})")
    return {"best_acc": best_acc, "best_epoch": best_epoch, "elapsed": elapsed}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--init-from", default=None)
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--size", type=int, default=224)
    ap.add_argument("--patience", type=int, default=8)
    ap.add_argument("--run-tag", default="_ft")
    ap.add_argument("--data-dir", default=None, help="裁剪数据集目录（必填，G6：禁止默认读旧 crop_dataset）")
    ap.add_argument("--full", action="store_true", help="全量微调（解冻骨干，修复抠图域偏移）")
    a = ap.parse_args()
    finetune(a.init_from, a.epochs, a.lr, a.batch, a.size, a.patience, a.run_tag, a.data_dir, a.full)
