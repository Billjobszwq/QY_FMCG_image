"""阶段零自检（Gate 1）：验证级联流水线三大基础模块可加载并跑通单图推理。

检查项：
  1. YOLO 冻结底座：./best/sku_v4_best.pt 可加载 + 推理
  2. 分类器底座：ResNet18（val_acc=92.95%）可加载
  3. 级联流水线：大图 → YOLO画框 → 裁剪224 → 分类器，单图跑通

用法：python -m src.cascade.selfcheck [--image <path>]"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT
from .classifier import build_model

BEST_DIR = PROJECT_ROOT / "best"
YOLO_W = BEST_DIR / "sku_v4_best.pt"
CLF_W = BEST_DIR / "classifier_base_9295.pth"
REGISTRY = PROJECT_ROOT / "data" / "sku_registry.json"
MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]

_results = []


def _report(item, ok, detail):
    _results.append({"item": item, "ok": ok, "detail": detail})
    mark = "✅" if ok else "❌"
    print(f"  {mark} {item}: {detail}")


def check_yolo(device):
    print("\n[1/3] YOLO 冻结底座")
    if not YOLO_W.exists():
        return _report("YOLO 权重存在", False, f"缺失 {YOLO_W}"), None
    try:
        from ultralytics import YOLO
        t0 = time.time()
        m = YOLO(str(YOLO_W))
        # 小图推理验证
        dummy = np.zeros((640, 640, 3), dtype=np.uint8)
        m.predict(dummy, conf=0.25, imgsz=640, verbose=False, device=device)
        nc = len(m.names)
        _report("YOLO 加载+推理", True, f"{YOLO_W.name} 加载 {time.time()-t0:.1f}s, {nc} 类")
        return True, m
    except Exception as e:
        return _report("YOLO 加载+推理", False, f"{type(e).__name__}: {e}"), None


def check_classifier(device):
    print("\n[2/3] 分类器底座 (ResNet18, 92.95%)")
    if not CLF_W.exists():
        return _report("分类器权重存在", False, f"缺失 {CLF_W}"), None
    try:
        t0 = time.time()
        ck = torch.load(str(CLF_W), map_location=device, weights_only=False)
        backbone = ck.get("backbone", "resnet18")
        n_classes = ck["n_classes"]
        model = build_model(backbone, n_classes).to(device)
        model.load_state_dict(ck["model"])
        model.eval()
        # 前向验证
        with torch.no_grad():
            x = torch.randn(1, 3, 224, 224).to(device)
            out = model(x)
        va = ck.get("val_acc", 0)
        _report("分类器加载+前向", True,
                f"{backbone} {n_classes}类, val_acc={va*100:.2f}%, 加载{time.time()-t0:.1f}s, 输出shape={tuple(out.shape)}")
        return True, (model, ck)
    except Exception as e:
        return _report("分类器加载+前向", False, f"{type(e).__name__}: {e}"), None


def _crop_resize(img, box, size=224):
    W, H = img.size
    x1, y1 = max(0, int(box[0])), max(0, int(box[1]))
    x2, y2 = min(W, int(box[2])), min(H, int(box[3]))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    crop = img.crop((x1, y1, x2, y2))
    w, h = crop.size
    s = size / max(w, h)
    nw, nh = max(1, int(w * s)), max(1, int(h * s))
    crop = crop.resize((nw, nh), Image.BILINEAR)
    canvas = Image.new("RGB", (size, size), (114, 114, 114))
    canvas.paste(crop, ((size - nw) // 2, (size - nh) // 2))
    return canvas


def _pick_test_image():
    """选一张 batch2 真实照片作测试。"""
    blobs = PROJECT_ROOT / ".training_data" / "blobs"
    manifest_p = PROJECT_ROOT / ".eval" / "batch2" / "manifest.json"
    if manifest_p.exists():
        try:
            mf = json.loads(manifest_p.read_text(encoding="utf-8"))
            for pid, p in mf["photos"].items():
                sha = (p.get("image") or {}).get("sha256")
                if sha:
                    bp = blobs / sha[:2] / sha
                    if bp.exists():
                        return bp.read_bytes(), f"batch2 photo {pid}"
        except Exception:
            pass
    # 兜底：合成图
    return (np.random.randint(0, 255, (960, 720, 3), dtype=np.uint8)).tobytes(), "合成兜底图"


def check_cascade(device, yolo_ok, yolo_model, clf_ok, clf_tuple):
    print("\n[3/3] 级联流水线单图推理")
    if not (yolo_ok and clf_ok):
        return _report("级联单图推理", False, "前置模块未通过，跳过")
    model, ck = clf_tuple
    classes = ck["classes"]
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    id_to_name = {v["sku_id"]: k for k, v in reg.items()}
    clsid_to_name = {v["class_id"]: k for k, v in reg.items()}
    try:
        img_bytes, src = _pick_test_image()
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        arr = np.array(img)
        t0 = time.time()
        rs = yolo_model.predict(arr, conf=0.15, imgsz=960, verbose=False, device=device)
        n_boxes = 0
        n_clf = 0
        samples = []
        tf = lambda c: (torch.tensor(np.array(c)).permute(2, 0, 1).float() / 255.0)
        from torchvision import transforms as T
        norm = T.Normalize(MEAN, STD)
        for r in rs:
            if r.boxes is None:
                continue
            for box, cls, sc in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist()):
                n_boxes += 1
                crop = _crop_resize(img, box)
                if crop is None:
                    continue
                inp = norm(tf(crop)).unsqueeze(0).to(device)
                with torch.no_grad():
                    probs = torch.softmax(model(inp), dim=1)[0]
                conf, idx = probs.max(0)
                sku_id = classes[idx.item()]
                n_clf += 1
                if len(samples) < 3:
                    samples.append(f"{id_to_name.get(sku_id, sku_id)}({float(conf):.2f})")
        elapsed = time.time() - t0
        _report("级联单图推理", True,
                f"[{src}] {img.size[0]}x{img.size[1]} → YOLO框{n_boxes}个 → 分类{n_clf}个, {elapsed:.2f}s. 示例: {', '.join(samples) if samples else '无检出'}")
        return True
    except Exception as e:
        return _report("级联单图推理", False, f"{type(e).__name__}: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=None)
    a = ap.parse_args()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print("=" * 58)
    print("阶段零自检 (Gate 1) — 级联流水线基础模块完整性")
    print(f"设备: {device}")
    print("=" * 58)
    yolo_ok, yolo_model = check_yolo(device)
    clf_ok, clf_tuple = check_classifier(device)
    check_cascade(device, bool(yolo_ok), yolo_model, bool(clf_ok), clf_tuple)

    all_ok = all(r["ok"] for r in _results)
    print("\n" + "=" * 58)
    print(f"Gate 1 结论: {'✅ 全部通过，可进入阶段一' if all_ok else '❌ 存在失败项，需修复'}")
    print("=" * 58)
    return all_ok


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
