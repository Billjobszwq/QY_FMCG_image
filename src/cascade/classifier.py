"""级联分类器训练：轻量骨干（ResNet18/EfficientNet-B0/MobileNetV3）+ 208 类细粒度分类。

策略（按任务要求）：
  - 骨干：ResNet18（默认，轻量快速）/ EfficientNet-B0 / MobileNetV3，预训练初始化
  - MPS 加速，224x224 输入，batch 64/128
  - 优化器 AdamW，lr0=1e-3，余弦退火（CosineAnnealingLR）
  - 数据增强：RandomResizedCrop + RandomRotation(±15) + RandomErasing + ColorJitter
  - 过采样：少数类（<50 样本）通过 WeightedRandomSampler 平衡
  - 早停：patience=10（连续 10 轮 val acc 不提升终止）
  - 过拟合预警：epoch 15-20 时若 val acc <75% 或 val loss 先降后升，自动降 lr 至 3e-4 重启
  - 趋势判定：Top-1 Accuracy 稳步上升即正确（目标 94-98%）

用法：python -m src.cascade.classifier [--backbone resnet18] [--epochs 80] [--batch 64]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import WeightedRandomSampler
from torchvision import datasets, models, transforms

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT

CROP_DIR = PROJECT_ROOT / "crop_dataset"
OUT_DIR = PROJECT_ROOT / ".models" / "classifier"
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


def build_model(backbone: str, n_classes: int) -> nn.Module:
    if backbone == "resnet18":
        m = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
        m.fc = nn.Linear(m.fc.in_features, n_classes)
    elif backbone == "efficientnet_b0":
        m = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.DEFAULT)
        m.classifier[1] = nn.Linear(m.classifier[1].in_features, n_classes)
    elif backbone == "mobilenet_v3":
        m = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.DEFAULT)
        m.classifier[3] = nn.Linear(m.classifier[3].in_features, n_classes)
    else:
        raise ValueError(f"未知骨干: {backbone}")
    return m


def get_datasets(size: int = 224, data_dir=None):
    train_tf = transforms.Compose([
        transforms.RandomResizedCrop(size, scale=(0.7, 1.0)),
        transforms.RandomRotation(15),
        transforms.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.3, hue=0.1),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        transforms.RandomErasing(p=0.25),
    ])
    val_tf = transforms.Compose([
        transforms.Resize(int(size * 1.14)),
        transforms.CenterCrop(size),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])
    base = Path(data_dir) if data_dir else CROP_DIR
    train_ds = datasets.ImageFolder(str(base / "train"), transform=train_tf, allow_empty=True)
    val_ds = datasets.ImageFolder(str(base / "val"), transform=val_tf, allow_empty=True)
    return train_ds, val_ds


def build_sampler(train_ds) -> WeightedRandomSampler:
    """过采样：按类别频率倒数加权，平衡少数类。"""
    targets = torch.tensor(train_ds.targets)
    class_counts = torch.bincount(targets).float()
    class_counts = torch.clamp(class_counts, min=1)
    class_weights = 1.0 / class_counts
    sample_weights = class_weights[targets]
    return WeightedRandomSampler(sample_weights, num_samples=len(sample_weights), replacement=True)


def freeze_backbone(model: nn.Module, backbone: str):
    """冻结骨干，仅训练分类头（增量微调用）。"""
    for p in model.parameters():
        p.requires_grad = False
    if backbone == "resnet18":
        for p in model.fc.parameters():
            p.requires_grad = True
    elif backbone == "efficientnet_b0":
        for p in model.classifier.parameters():
            p.requires_grad = True
    elif backbone == "mobilenet_v3":
        for p in model.classifier.parameters():
            p.requires_grad = True


def train(backbone: str = "resnet18", epochs: int = 80, batch: int = 64,
          lr0: float = 1e-3, patience: int = 10, size: int = 224,
          freeze: bool = False, run_tag: str = "", promote: bool = False):
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # 复核修订（RA-012）：禁止可变 best.pt 被静默覆盖。每个 run 写入独立实验目录
    # run_<tag>，run_tag 已存在则 fail-closed；生产 best.pt 仅在显式 --promote
    # 时更新，且先归档旧版本。
    if not run_tag:
        run_tag = time.strftime("%Y%m%d_%H%M%S")
    exp_dir = OUT_DIR / f"run_{run_tag}"
    if exp_dir.exists():
        raise RuntimeError(f"实验目录已存在，拒绝覆盖: {exp_dir}（换一个 --run-tag）")
    exp_dir.mkdir(parents=True)
    run_tag = "_" + run_tag  # 历史/曲线文件名后缀兼容

    train_ds, val_ds = get_datasets(size)
    n_classes = len(train_ds.classes)
    print(f"=== 分类器训练 ({backbone}) ===")
    print(f"  设备: {device} | 类别: {n_classes} | 训练 {len(train_ds)} / 验证 {len(val_ds)}")
    print(f"  batch={batch}, lr0={lr0}, epochs={epochs}, patience={patience}, freeze={freeze}")

    # 保存类别列表（推理用，ImageFolder 按文件夹名排序）
    (OUT_DIR / "classes.json").write_text(json.dumps(train_ds.classes, ensure_ascii=False, indent=2), encoding="utf-8")

    sampler = build_sampler(train_ds)
    train_loader = torch.utils.data.DataLoader(train_ds, batch_size=batch, sampler=sampler, num_workers=4, pin_memory=True)
    val_loader = torch.utils.data.DataLoader(val_ds, batch_size=batch, shuffle=False, num_workers=4, pin_memory=True)

    model = build_model(backbone, n_classes).to(device)
    if freeze:
        freeze_backbone(model, backbone)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(filter(lambda p: p.requires_grad, model.parameters()), lr=lr0, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    history = []
    best_acc = 0.0
    best_epoch = 0
    no_improve = 0
    val_loss_history = []
    lr_cut_done = False
    t0 = time.time()

    for epoch in range(1, epochs + 1):
        # 训练
        model.train()
        run_loss, run_correct, run_total = 0.0, 0, 0
        total_batches = len(train_loader)
        ep_start = time.time()
        for batch_idx, (imgs, labels) in enumerate(train_loader):
            imgs, labels = imgs.to(device), labels.to(device)
            optimizer.zero_grad()
            out = model(imgs)
            loss = criterion(out, labels)
            loss.backward()
            optimizer.step()
            run_loss += loss.item() * imgs.size(0)
            run_correct += (out.argmax(1) == labels).sum().item()
            run_total += imgs.size(0)
            # 每 20 batch 写入轮内实时进度（供监控实时展示）
            if batch_idx % 20 == 0 or batch_idx == total_batches - 1:
                elapsed_ep = time.time() - ep_start
                per_batch = elapsed_ep / (batch_idx + 1)
                eta_epoch = per_batch * (total_batches - batch_idx - 1)
                _live = {
                    "name": "级联分类器", "backbone": backbone,
                    "epoch": epoch, "total_epochs": epochs,
                    "batch": batch_idx + 1, "total_batches": total_batches,
                    "epoch_progress": round((batch_idx + 1) / total_batches, 4),
                    "running_loss": round(run_loss / run_total, 4),
                    "running_acc": round(run_correct / run_total, 4),
                    "lr": optimizer.param_groups[0]["lr"],
                    "eta_epoch_sec": round(eta_epoch),
                    "best_acc": best_acc, "best_epoch": best_epoch,
                    "phase": "train", "updated_at": time.time(),
                }
                (OUT_DIR / "live_progress.json").write_text(
                    json.dumps(_live, ensure_ascii=False, indent=2), encoding="utf-8")
        scheduler.step()
        train_loss = run_loss / run_total
        train_acc = run_correct / run_total

        # 验证
        model.eval()
        val_loss, val_correct, val_total = 0.0, 0, 0
        with torch.no_grad():
            for imgs, labels in val_loader:
                imgs, labels = imgs.to(device), labels.to(device)
                out = model(imgs)
                loss = criterion(out, labels)
                val_loss += loss.item() * imgs.size(0)
                val_correct += (out.argmax(1) == labels).sum().item()
                val_total += imgs.size(0)
        val_loss /= val_total
        val_acc = val_correct / val_total
        val_loss_history.append(val_loss)
        cur_lr = optimizer.param_groups[0]["lr"]

        history.append({"epoch": epoch, "train_loss": round(train_loss, 4), "train_acc": round(train_acc, 4),
                        "val_loss": round(val_loss, 4), "val_acc": round(val_acc, 4), "lr": cur_lr})
        # 逐轮写入 history（供实时监控）
        (OUT_DIR / f"training_history{run_tag}.json").write_text(
            json.dumps({"backbone": backbone, "n_classes": n_classes, "running": True, "epochs": history},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  ep{epoch}: train_acc={train_acc:.4f} val_acc={val_acc:.4f} val_loss={val_loss:.4f} lr={cur_lr:.2e}", flush=True)

        # 保存最佳（复核修订：写入实验目录，不再直接覆盖生产 best.pt）
        if val_acc > best_acc:
            best_acc = val_acc
            best_epoch = epoch
            no_improve = 0
            torch.save({"model": model.state_dict(), "backbone": backbone, "n_classes": n_classes,
                        "classes": train_ds.classes, "val_acc": val_acc, "epoch": epoch,
                        "run_tag": run_tag.lstrip("_")},
                       exp_dir / "best.pt")
        else:
            no_improve += 1

        # 过拟合预警：epoch 15-20 时 val acc <75% 或 val loss 先降后升 → 降 lr 至 3e-4
        if not lr_cut_done and 15 <= epoch <= 20:
            down_then_up = len(val_loss_history) >= 5 and min(val_loss_history[:-1]) < val_loss_history[-1] > val_loss_history[-2]
            if val_acc < 0.75 or down_then_up:
                print(f"  ⚠ 过拟合/停滞预警（ep{epoch}: val_acc={val_acc:.3f}），降 lr 至 3e-4")
                for pg in optimizer.param_groups:
                    pg["lr"] = 3e-4
                scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, epochs - epoch))
                lr_cut_done = True

        # 早停
        if no_improve >= patience:
            print(f"  ⏹ 早停：连续 {patience} 轮 val acc 未提升（最佳 ep{best_epoch}={best_acc:.4f}）")
            break

    # 保存训练历史 + 曲线（标记训练结束）
    (OUT_DIR / f"training_history{run_tag}.json").write_text(
        json.dumps({"backbone": backbone, "n_classes": n_classes, "running": False,
                    "best_acc": best_acc, "best_epoch": best_epoch, "epochs": history},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    _plot_curves(history, run_tag)
    elapsed = time.time() - t0
    print(f"\n=== 训练完成 ({elapsed:.0f}s) ===")
    print(f"  最佳 val_acc: {best_acc:.4f} (epoch {best_epoch})")
    print(f"  权重: {exp_dir/'best.pt'}")
    # 复核修订：生产 best.pt 只在显式 promote 时更新，且先归档旧权重
    if promote:
        prod = OUT_DIR / "best.pt"
        if prod.exists():
            bak = OUT_DIR / f"best_prev_{time.strftime('%Y%m%d%H%M%S')}.pt"
            shutil.copy2(prod, bak)
            print(f"  旧生产权重已归档: {bak.name}")
        shutil.copy2(exp_dir / "best.pt", prod)
        print(f"  已 promote 为生产 best.pt: {prod}")
    else:
        print("  未 --promote：生产 best.pt 保持不变，发布需经 bundle 流程")
    return {"best_acc": best_acc, "best_epoch": best_epoch, "elapsed": elapsed,
            "exp_dir": str(exp_dir)}


def _plot_curves(history, run_tag=""):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        eps = [h["epoch"] for h in history]
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
        ax1.plot(eps, [h["train_acc"] for h in history], label="train_acc")
        ax1.plot(eps, [h["val_acc"] for h in history], label="val_acc")
        ax1.set_title("Top-1 Accuracy"); ax1.set_xlabel("epoch"); ax1.legend(); ax1.grid(alpha=0.3)
        ax2.plot(eps, [h["train_loss"] for h in history], label="train_loss")
        ax2.plot(eps, [h["val_loss"] for h in history], label="val_loss")
        ax2.set_title("Loss"); ax2.set_xlabel("epoch"); ax2.legend(); ax2.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(OUT_DIR / f"curves{run_tag}.png", dpi=100)
        print(f"  曲线图: {OUT_DIR / f'curves{run_tag}.png'}")
    except Exception as e:
        print(f"  曲线图生成失败: {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backbone", default="resnet18", choices=["resnet18", "efficientnet_b0", "mobilenet_v3"])
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr0", type=float, default=1e-3)
    ap.add_argument("--patience", type=int, default=10)
    ap.add_argument("--size", type=int, default=224)
    ap.add_argument("--freeze", action="store_true", help="冻结骨干仅训分类头（增量微调）")
    ap.add_argument("--run-tag", default="")
    ap.add_argument("--promote", action="store_true",
                    help="显式将本 run 最佳权重提升为生产 best.pt（旧版先归档）")
    a = ap.parse_args()
    train(a.backbone, a.epochs, a.batch, a.lr0, a.patience, a.size, a.freeze,
          a.run_tag, promote=a.promote)
