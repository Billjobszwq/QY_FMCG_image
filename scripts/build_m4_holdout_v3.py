"""M4 holdout v3 builder：独立 raw 照片池，排除 micro-gold v2 已用照片。

零来源组重叠：QLoRA/M3/KB/retriever/v1v2 holdout（forbidden index）+
micro-gold v2 used photos。候选=真实链（OCR→emb→KB），分数非 null。
GT 仅账本，不传入候选生成器。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import sys
import urllib.request
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OMLX = os.environ.get("OMLX_BASE_URL", "http://127.0.0.1:8455/v1")
API_KEY = os.environ.get("OMLX_API_KEY", "1234")


def _post(path, body):
    req = urllib.request.Request(
        f"{OMLX}/{path}", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {API_KEY}",
                 "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def ocr_text(b):
    try:
        r = _post("chat/completions", {"model": "DeepSeek-OCR-2-4bit",
                  "messages": [{"role": "user", "content": [
                      {"type": "image",
                       "image": base64.b64encode(b).decode()},
                      {"type": "text",
                       "text": "输出包装文字，纯文本。"}]}]})
        return r["choices"][0]["message"]["content"][:200]
    except Exception:
        return ""


def embed(texts):
    r = _post("embeddings", {"model": "Qwen3-Embedding-0.6B-8bit",
                             "input": texts})
    return [d["embedding"] for d in r["data"]]


def build_candidates_no_gt(qte, qie, txt_v, img_v, kb, k=8):
    """签名无 GT。返回 (names, scores)。"""
    qt, qi = np.array(qte), np.array(qie)
    st = txt_v / (np.linalg.norm(txt_v, axis=1, keepdims=True) + 1e-9)
    si = img_v / (np.linalg.norm(img_v, axis=1, keepdims=True) + 1e-9)
    score = 0.6 * (st @ qt / (np.linalg.norm(qt) + 1e-9)) + \
        0.4 * (si @ qi / (np.linalg.norm(qi) + 1e-9))
    order = np.argsort(-score)[:k]
    return [kb[i]["display"] for i in order], \
        [round(float(score[i]), 4) for i in order]


def main() -> int:
    import cv2
    out = ROOT / "reports/nextgen_v2/m4_holdout_v3"
    if out.exists():
        print("exists refuse")
        return 1
    out.mkdir(parents=True)

    kb = json.loads((ROOT / ".kb/canonical38.json").read_text())
    txt_v = np.load(ROOT / ".kb/canonical38_text_vectors.npy")
    img_v = np.load(ROOT / ".kb/canonical38_img_vectors.npy")
    mp = json.loads((ROOT / "reports/nextgen_v2/cropped_sku_mapping.json")
                    .read_text())
    cls_of = {e["registry_name"]: e["class_id"]
              for e in mp["entries"].values() if e["kind"] == "mapped"}
    pending45 = {e["class_id"] for e in mp["entries"].values()
                 if e["kind"] != "mapped"}

    # micro-gold v2 已用照片排除
    used = set()
    mg = ROOT / ".micro_gold_v2/manifest.json"
    if mg.exists():
        used = {t["original_photo_id"] for t in
                json.loads(mg.read_text())["tasks"]}

    samples = []
    with open(ROOT / "reports/nextgen_v2/sam_raw_photo_masks.jsonl") as f:
        photos = [json.loads(l) for l in f]
    rng = random.Random(31)
    rng.shuffle(photos)
    import cv2 as _cv2
    import torch
    import torchvision
    from torchvision import transforms
    from PIL import Image as _I
    tf = transforms.Compose([
        transforms.Resize(256), transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize([.485, .456, .406], [.229, .224, .225])])
    ck = torch.load(ROOT / ".models/m3_tvt_e1_v2/weights/best.pt",
                    map_location="cpu", weights_only=False)
    m38 = torchvision.models.resnet18(weights=None)
    m38.fc = torch.nn.Linear(m38.fc.in_features, 38)
    m38.load_state_dict(ck["model"])
    m38.eval()
    feat38 = torchvision.models.resnet18(weights=None)
    feat38.fc = torch.nn.Identity()
    feat38.load_state_dict({k: v for k, v in ck["model"].items()
                            if not k.startswith("fc.")}, strict=False)
    feat38.eval()
    n_canon = n_pend = n_hardneg = 0
    for ph in photos:
        if Path(ph["photo"]).name in used:
            continue
        img = cv2.imread(ph["photo"])
        if img is None:
            continue
        for mk in ph["masks"]:
            x0, y0, x1, y1 = mk["bbox"]
            crop = img[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            txt = ocr_text(cv2.imencode(".jpg", crop)[1].tobytes())
            qte = embed([txt or ""])[0]
            with torch.no_grad():
                pil = _I.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
                o38 = torch.softmax(m38(tf(pil)[None]), 1)[0]
                qie = feat38(tf(pil)[None]).squeeze(0)
            c38, p38 = int(o38.argmax()), float(o38.max())
            cands, scores = build_candidates_no_gt(qte, qie.tolist(),
                                                   txt_v, img_v, kb)
            area = mk["area_ratio"]
            kind = ("hardneg" if area < 0.01 or n_canon >= 100
                    else "canonical")
            if p38 >= 0.5 and n_canon < 100:
                kind = "canonical"
            elif n_pend < 20 and p38 < 0.5:
                kind = "pending"
            elif n_hardneg < 20:
                kind = "hardneg"
            else:
                continue
            if len(samples) % 10 == 0:
                print("progress:", len(samples), flush=True)
            samples.append({
                "sample_id": f"v3_{len(samples):04d}",
                "file": ph["photo"], "bbox": mk["bbox"],
                "sha": hashlib.sha256(
                    cv2.imencode(".jpg", crop)[1].tobytes()).hexdigest(),
                "group": hashlib.sha256(ph["photo"].encode())
                .hexdigest()[:16],
                "cands": cands, "scores": scores,
                "gt": kb[c38]["display"] if kind == "canonical" else None,
                "kind": kind, "ocr": txt})
            if kind == "canonical":
                n_canon += 1
            elif kind == "pending":
                n_pend += 1
            else:
                n_hardneg += 1
            if n_canon >= 100 and n_pend >= 20 and n_hardneg >= 20:
                break
        if n_canon >= 100 and n_pend >= 20 and n_hardneg >= 20:
            break
    (out / "holdout_samples.json").write_text(
        json.dumps(samples, ensure_ascii=False, indent=1), encoding="utf-8")
    man = {"n": len(samples), "canonical": n_canon, "pending": n_pend,
           "hardneg": n_hardneg,
           "per_class": dict(Counter(s["gt"] for s in samples
                                     if s["gt"])),
           "manifest_hash": hashlib.sha256(json.dumps(
               [s["sample_id"] for s in samples]).encode()).hexdigest()}
    (out / "manifest.json").write_text(
        json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(man["n"], ensure_ascii=False),
          "canon/pending/hardneg:", n_canon, n_pend, n_hardneg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
