"""SLTF P0-3：旧分类器在 随机切分 val vs grouped val 的对比评估。

输出：旧随机 val top1 / grouped val top1 / macro-F1 / 差值 / 泄漏组数量。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def evaluate(model, classes, data_dir, device):
    from torchvision import transforms
    from torchvision.datasets import ImageFolder
    tf = transforms.Compose([
        transforms.Resize(256), transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406],
                             [0.229, 0.224, 0.225])])
    ds = ImageFolder(str(data_dir), transform=tf)
    if not ds.samples:
        return None
    import torch
    ld = torch.utils.data.DataLoader(ds, batch_size=64, shuffle=False,
                                     num_workers=2)
    cls2idx = {c: i for i, c in enumerate(classes)}
    hit = tot = 0
    per_cls = {}
    with torch.no_grad():
        for x, y in ld:
            out = model(x.to(device))
            pred = out.argmax(1).cpu()
            for pi, yi in zip(pred, y):
                tot += 1
                cname = ds.classes[yi]
                st = per_cls.setdefault(cname, [0, 0])
                st[1] += 1
                ok = int(pi.item() == yi.item())
                hit += ok
                st[0] += ok
    top1 = hit / tot
    recalls = [v[0] / v[1] for v in per_cls.values()]
    macro = sum(recalls) / len(recalls)
    return {"top1": round(top1, 4), "macro_recall": round(macro, 4),
            "n": tot, "classes": len(per_cls)}


def main() -> int:
    import torch
    import torchvision
    ck = torch.load(ROOT / ".models/nextgen_classifier_cropped_v1/weights"
                    / "best.pt", map_location="cpu", weights_only=False)
    classes = ck["classes"]
    model = torchvision.models.resnet18(weights=None)
    model.fc = torch.nn.Linear(model.fc.in_features, len(classes))
    model.load_state_dict(ck["model"])
    device = torch.device("mps" if torch.backends.mps.is_available()
                          else "cpu")
    model = model.to(device).eval()

    v1_val = ROOT / ".datasets_nextgen/d3_cropped_classifier_v1/val"
    v2_val = ROOT / ".datasets_nextgen/d3_cropped_classifier_v2_grouped/val"
    r1 = evaluate(model, classes, v1_val, device)
    r2 = evaluate(model, classes, v2_val, device)
    rep = {"model": "nextgen_classifier_cropped_v1",
           "random_split_val": r1, "grouped_split_val": r2,
           "delta_top1": round(r1["top1"] - r2["top1"], 4),
           "note": "差值≈随机切分泄漏带来的乐观偏差"}
    out = ROOT / "reports/nextgen_v2/classifier_split_compare.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
