"""N2 Task 12：M3 classifier nextgen smoke（ResNet18 ImageNet public base）。

红线：base 为 torchvision ImageNet 公开权重（本地缓存），不继承旧业务
checkpoint；输出目录已存在拒绝；1 epoch smoke 只验管线，非 candidate。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--run-name", required=True)
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    a = ap.parse_args()

    out_dir = ROOT / ".models" / a.run_name
    if out_dir.exists():
        raise SystemExit(f"run 目录已存在，拒绝覆盖: {out_dir}")
    out_dir.mkdir(parents=True)

    import torch
    import torchvision
    from torchvision import transforms
    from torchvision.datasets import ImageFolder

    device = torch.device("mps" if torch.backends.mps.is_available()
                          else "cpu")
    tf = transforms.Compose([
        transforms.RandomResizedCrop(224, scale=(0.7, 1.0)),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406],
                             [0.229, 0.224, 0.225])])
    tfv = transforms.Compose([
        transforms.Resize(256), transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406],
                             [0.229, 0.224, 0.225])])
    ds_tr = ImageFolder(str(Path(a.data_dir) / "train"), transform=tf)
    ds_va = ImageFolder(str(Path(a.data_dir) / "val"), transform=tfv)
    n_classes = len(ds_tr.classes)
    print(f"classes={n_classes} train={len(ds_tr)} val={len(ds_va)} "
          f"device={device}", flush=True)

    model = torchvision.models.resnet18(
        weights=torchvision.models.ResNet18_Weights.IMAGENET1K_V1)
    model.fc = torch.nn.Linear(model.fc.in_features, n_classes)
    model = model.to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr)
    crit = torch.nn.CrossEntropyLoss()
    ld_tr = torch.utils.data.DataLoader(ds_tr, batch_size=a.batch,
                                        shuffle=True, num_workers=2)
    ld_va = torch.utils.data.DataLoader(ds_va, batch_size=a.batch,
                                        shuffle=False, num_workers=2)

    t0 = time.time()
    curve = []
    for ep in range(a.epochs):
        model.train()
        tot, loss_sum = 0, 0.0
        for x, y in ld_tr:
            x, y = x.to(device), y.to(device)
            opt.zero_grad()
            out = model(x)
            loss = crit(out, y)
            loss.backward()
            opt.step()
            loss_sum += loss.item() * len(x)
            tot += len(x)
        model.eval()
        hit = totv = 0
        with torch.no_grad():
            for x, y in ld_va:
                x, y = x.to(device), y.to(device)
                hit += (model(x).argmax(1) == y).sum().item()
                totv += len(y)
        curve.append({"epoch": ep + 1,
                      "train_loss": round(loss_sum / tot, 4),
                      "val_top1": round(hit / max(totv, 1), 4)})
        print(json.dumps(curve[-1]), flush=True)

    best = out_dir / "weights"
    best.mkdir()
    torch.save({"model": model.state_dict(),
                "classes": ds_tr.classes,
                "base": "resnet18-imagenet(public)",
                "lineage_family": "fmcg_nextgen_v1"},
               best / "best.pt")
    sha = hashlib.sha256((best / "best.pt").read_bytes()).hexdigest()
    rep = {"run": a.run_name, "lane": "classifier",
           "kind": "one_epoch_smoke",
           "base": "resnet18-imagenet(public)",
           "lineage_family": "fmcg_nextgen_v1",
           "n_classes": n_classes, "epochs": a.epochs,
           "duration_s": round(time.time() - t0, 1),
           "curve": curve, "artifact_sha256": sha, "candidate": False,
           "evidence_level": "smoke_pseudo_interim"}
    (out_dir / "smoke_report.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"done": True, "sha": sha[:16],
                      "val_top1": curve[-1]["val_top1"],
                      "duration_s": rep["duration_s"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
