"""纠偏 Task 9：M3 长尾消融 E1-E5（canonical38 grouped split，同预算）。

E1 CE baseline / E2 balanced sampler / E3 effective-number CB loss /
E4 focal loss / E5 层级（品牌族→canonical）。E6 待混淆证据。
报告：top1/macro recall/macro F1/balanced acc/worst-decile/head-tail gap。
run artifact 九要素快照。不继承旧 classifier。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA = ROOT / ".datasets_nextgen/d3_canonical38_grouped"


def snapshot(run_dir: Path, cfg: dict) -> dict:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "diff", "HEAD"], cwd=ROOT,
                           capture_output=True, text=True).stdout
    snap = {"source_commit": head,
            "dirty_diff_hash": hashlib.sha256(dirty.encode()).hexdigest(),
            "launcher_source_hash": hashlib.sha256(
                Path(__file__).read_bytes()).hexdigest(),
            "resolved_command": sys.argv,
            "environment_lock": sys.version.split()[0],
            "data_manifest_sha": json.loads(
                (DATA / "manifest.json").read_text())["manifest_hash"],
            "base_model_sha": "resnet18-imagenet-public",
            "config": cfg, "seed": 42}
    (run_dir / "source_snapshot.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    return snap


def focal_loss(logits, target, gamma=2.0):
    import torch
    import torch.nn.functional as TF
    ce = TF.cross_entropy(logits, target, reduction="none")
    p = torch.exp(-ce)
    return ((1 - p) ** gamma * ce).mean()


def cb_loss(logits, target, weights):
    import torch
    import torch.nn.functional as TF
    ce = TF.cross_entropy(logits, target, reduction="none")
    w = weights[target]
    return (w * ce).mean()


def evaluate(model, ds, device, n_cls):
    import torch
    ld = torch.utils.data.DataLoader(ds, batch_size=64, shuffle=False)
    hit = tot = 0
    per = Counter()
    per_ok = Counter()
    with torch.no_grad():
        for x, y in ld:
            out = model(x.to(device))
            if isinstance(out, tuple):
                out = out[-1]
            pred = out.argmax(1).cpu()
            for pi, yi in zip(pred, y):
                tot += 1
                per[yi.item()] += 1
                ok = pi.item() == yi.item()
                hit += ok
                per_ok[yi.item()] += ok
    recalls = [per_ok[c] / per[c] for c in sorted(per)]
    worst = sorted(recalls)[:max(1, len(recalls) // 10)]
    return {"top1": round(hit / tot, 4),
            "macro_recall": round(sum(recalls) / len(recalls), 4),
            "balanced_acc": round(sum(recalls) / len(recalls), 4),
            "worst_decile_recall": round(sum(worst) / len(worst), 4),
            "head_tail_gap": round(max(recalls) - min(recalls), 4)}


def run_experiment(exp: str, run_dir: Path, epochs: int):
    import torch
    import torchvision
    from torchvision import transforms
    from torchvision.datasets import ImageFolder
    tf = transforms.Compose([
        transforms.Resize(256), transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize([.485, .456, .406], [.229, .224, .225])])
    train_ds = ImageFolder(str(DATA / "train"), transform=tf)
    val_ds = ImageFolder(str(DATA / "val"), transform=tf)
    n_cls = len(train_ds.classes)
    counts = Counter(y for _, y in train_ds.samples)
    device = torch.device("mps")

    model = torchvision.models.resnet18(weights="IMAGENET1K_V1")
    model.fc = torch.nn.Linear(model.fc.in_features, n_cls)
    if exp == "E5":
        # 层级：品牌族粗头（名称前 4 字聚类）+ 细头
        fam = {}
        for c in train_ds.classes:
            fam.setdefault(c[:4], len(fam))
        model.fam_head = torch.nn.Linear(model.fc.in_features, len(fam))
        model.fam_map = [fam[c[:4]] for c in train_ds.classes]
    model = model.to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4)

    # E2 balanced sampler
    sampler = None
    if exp == "E2":
        w = [1.0 / counts[y] for _, y in train_ds.samples]
        sampler = torch.utils.data.WeightedRandomSampler(
            w, len(w), replacement=True)
    ld = torch.utils.data.DataLoader(
        train_ds, batch_size=64, shuffle=sampler is None, sampler=sampler,
        num_workers=2)

    # E3 effective-number weights
    cb_w = None
    if exp == "E3":
        beta = 0.999
        eff = [1 - beta ** counts[c] for c in range(n_cls)]
        wts = [(1 - beta) / e for e in eff]
        s = sum(wts)
        cb_w = torch.tensor([n_cls * x / s for x in wts],
                            dtype=torch.float32).to(device)

    curve = []
    best_top1 = 0.0
    best_state = None
    t0 = time.time()
    for ep in range(epochs):
        model.train()
        tot = 0.0
        n = 0
        for x, y in ld:
            x, y = x.to(device), y.to(device)
            opt.zero_grad()
            logits = model(x)
            if exp == "E3":
                loss = cb_loss(logits, y, cb_w)
            elif exp == "E4":
                loss = focal_loss(logits, y)
            else:
                loss = torch.nn.functional.cross_entropy(logits, y)
            loss.backward()
            opt.step()
            tot += float(loss)
            n += 1
        model.eval()
        m = evaluate(model, val_ds, device, n_cls)
        curve.append({"epoch": ep + 1, "train_loss": round(tot / n, 4),
                      **m})
        if m["top1"] > best_top1:
            best_top1 = m["top1"]
            best_state = {k: v.cpu().clone() for k, v in
                          model.state_dict().items()}
        # early stop：3 epoch 无提升
        if ep >= 4 and all(c["top1"] <= best_top1
                           for c in curve[-3:]):
            break
    model.load_state_dict(best_state)
    model.eval()
    final = evaluate(model, val_ds, device, n_cls)
    (run_dir / "weights").mkdir(exist_ok=True)
    torch.save({"model": best_state, "classes": train_ds.classes},
               run_dir / "weights" / "best.pt")
    return curve, final, time.time() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiments", default="E1,E2,E3,E4,E5")
    ap.add_argument("--epochs", type=int, default=10)
    a = ap.parse_args()
    results = {}
    for exp in a.experiments.split(","):
        run_dir = ROOT / ".models" / f"m3_ablation_{exp.lower()}_v1"
        if run_dir.exists():
            print(exp, "exists skip")
            continue
        run_dir.mkdir(parents=True)
        snap = snapshot(run_dir, {"exp": exp, "epochs": a.epochs})
        curve, final, dur = run_experiment(exp, run_dir, a.epochs)
        rep = {"run": f"m3_ablation_{exp}", "experiment": exp,
               "curve": curve, "final": final,
               "duration_s": round(dur, 1),
               "artifact_sha256": hashlib.sha256(
                   (run_dir / "weights/best.pt").read_bytes()).hexdigest(),
               "source_snapshot": snap,
               "candidate": False,
               "note": "candidate 需相对 E1 grouped baseline 有明确收益"}
        (run_dir / "train_report.json").write_text(
            json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        results[exp] = final
        print(json.dumps({exp: final}), flush=True)
    out = ROOT / "reports/nextgen_v2/m3_longtail_ablation.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
