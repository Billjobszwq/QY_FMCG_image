"""状态收口 T6：M3 E1/E5 在 canonical38_train_val_test_v2 重训+独立测试。

early stop 只看 val；test 训练完成后仅跑一次；九要素快照。
报告：top1/macro P/R/F1/balanced/worst-decile/head-tail/per-class/
confusion/ECE/coverage@accepted/latency/error ledger。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA = ROOT / ".datasets_nextgen/canonical38_train_val_test_v2"


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


def ece(probs, labels, n_bins=10):
    import numpy as np
    conf = probs.max(1)
    pred = probs.argmax(1)
    acc = (pred == labels).astype(float)
    bins = np.linspace(0, 1, n_bins + 1)
    e = 0.0
    for i in range(n_bins):
        m = (conf > bins[i]) & (conf <= bins[i + 1])
        if m.sum():
            e += m.sum() / len(labels) * abs(conf[m].mean() - acc[m].mean())
    return float(e)


def full_eval(model, ds, device):
    import torch
    import numpy as np
    ld = torch.utils.data.DataLoader(ds, batch_size=64, shuffle=False)
    per_p = Counter()
    per_r = Counter()
    per_ok = Counter()
    hit = tot = 0
    all_probs, all_y = [], []
    errors = []
    lat = []
    with torch.no_grad():
        for x, y in ld:
            t0 = time.time()
            out = model(x.to(device))
            if isinstance(out, tuple):
                out = out[-1]
            lat.append(time.time() - t0)
            probs = torch.softmax(out, 1).cpu().numpy()
            pred = out.argmax(1).cpu().numpy()
            yv = y.numpy()
            all_probs.append(probs)
            all_y.append(yv)
            for pi, yi, xi in zip(pred, yv, x):
                tot += 1
                per_r[yi] += 1
                per_p[pi] += 1
                if pi == yi:
                    hit += 1
                    per_ok[yi] += 1
                else:
                    errors.append({"true": ds.classes[yi],
                                   "pred": ds.classes[pi]})
    probs = np.concatenate(all_probs)
    ys = np.concatenate(all_y)
    recalls = [per_ok[c] / per_r[c] for c in sorted(per_r)]
    precs = [per_ok[c] / per_p[c] for c in sorted(per_p) if per_p[c]]
    f1s = []
    for c in sorted(per_r):
        p_ = per_ok[c] / per_p[c] if per_p[c] else 0
        r_ = per_ok[c] / per_r[c]
        f1s.append(2 * p_ * r_ / (p_ + r_) if p_ + r_ else 0)
    worst = sorted(recalls)[:max(1, len(recalls) // 10)]
    # coverage@accepted precision 0.9
    thr_mask = probs.max(1) >= 0.9
    acc90 = (probs.argmax(1)[thr_mask] == ys[thr_mask]).mean() \
        if thr_mask.sum() else 0.0
    return {"top1": round(hit / tot, 4),
            "macro_precision": round(sum(precs) / len(precs), 4),
            "macro_recall": round(sum(recalls) / len(recalls), 4),
            "macro_f1": round(sum(f1s) / len(f1s), 4),
            "balanced_acc": round(sum(recalls) / len(recalls), 4),
            "worst_decile_recall": round(sum(worst) / len(worst), 4),
            "head_tail_gap": round(max(recalls) - min(recalls), 4),
            "ece": round(ece(probs, ys), 4),
            "coverage_at_p90": round(float(thr_mask.mean()), 4),
            "accepted_precision_p90": round(float(acc90), 4),
            "p50_latency_ms": round(float(np.percentile(lat, 50)) * 1000, 1),
            "p95_latency_ms": round(float(np.percentile(lat, 95)) * 1000, 1),
            "per_class": {ds.classes[c]: {"p": round(per_ok[c] / per_p[c], 3)
                                          if per_p[c] else 0,
                                          "r": round(per_ok[c] / per_r[c], 3)}
                          for c in sorted(per_r)},
            "confusion_top": sorted(Counter(
                (e["true"], e["pred"]) for e in errors).items(),
                key=lambda kv: -kv[1])[:10],
            "n_errors": len(errors),
            "error_ledger": errors[:50]}


def run(exp: str, run_dir: Path, epochs: int):
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
    test_ds = ImageFolder(str(DATA / "test"), transform=tf)
    n_cls = len(train_ds.classes)
    device = torch.device("mps")
    model = torchvision.models.resnet18(weights="IMAGENET1K_V1")
    model.fc = torch.nn.Linear(model.fc.in_features, n_cls)
    if exp == "E5":
        fam = {}
        for c in train_ds.classes:
            fam.setdefault(c[:4], len(fam))
        model.fam_head = torch.nn.Linear(model.fc.in_features, len(fam))
    model = model.to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4)
    ld = torch.utils.data.DataLoader(train_ds, batch_size=64, shuffle=True,
                                     num_workers=2)
    curve = []
    best, best_state = 0.0, None
    t0 = time.time()
    for ep in range(epochs):
        model.train()
        tot = n = 0
        for x, y in ld:
            opt.zero_grad()
            out = model(x.to(device))
            loss = torch.nn.functional.cross_entropy(
                out, y.to(device))
            loss.backward()
            opt.step()
            tot += float(loss)
            n += 1
        model.eval()
        with torch.no_grad():
            h = t = 0
            for x, y in torch.utils.data.DataLoader(val_ds, 64):
                o = model(x.to(device))
                if isinstance(o, tuple):
                    o = o[-1]
                h += (o.argmax(1).cpu() == y).sum().item()
                t += len(y)
        vtop1 = h / t
        curve.append({"epoch": ep + 1, "train_loss": round(tot / n, 4),
                      "val_top1": round(vtop1, 4)})
        if vtop1 > best:
            best = vtop1
            best_state = {k: v.cpu().clone() for k, v in
                          model.state_dict().items()}
        if ep >= 4 and all(c["val_top1"] <= best for c in curve[-3:]):
            break
    model.load_state_dict(best_state)
    model.eval()
    test_metrics = full_eval(model, test_ds, device)  # 仅一次
    (run_dir / "weights").mkdir(exist_ok=True)
    torch.save({"model": best_state, "classes": train_ds.classes},
               run_dir / "weights" / "best.pt")
    return curve, test_metrics, time.time() - t0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", required=True, choices=["E1", "E5"])
    ap.add_argument("--epochs", type=int, default=12)
    a = ap.parse_args()
    run_dir = ROOT / ".models" / f"m3_tvt_{a.exp.lower()}_v2"
    if run_dir.exists():
        print("exists refuse")
        return 1
    run_dir.mkdir(parents=True)
    snap = snapshot(run_dir, {"exp": a.exp, "epochs": a.epochs,
                              "data": "canonical38_train_val_test_v2"})
    curve, test_m, dur = run(a.exp, run_dir, a.epochs)
    rep = {"run": f"m3_tvt_{a.exp}_v2", "experiment": a.exp,
           "split": "canonical38_train_val_test_v2",
           "curve": curve, "independent_test": test_m,
           "duration_s": round(dur, 1),
           "artifact_sha256": hashlib.sha256(
               (run_dir / "weights/best.pt").read_bytes()).hexdigest(),
           "source_snapshot": snap,
           "candidate_status": "PILOT_PENDING_EVALUATION",
           "note": "test 仅训练后跑一次；选择按综合优先级不唯 top1"}
    (run_dir / "train_report.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({a.exp: {k: test_m[k] for k in (
        "top1", "macro_f1", "worst_decile_recall", "ece",
        "accepted_precision_p90")}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
