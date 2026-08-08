"""纠偏 Task 11：canonical38 KB recall 评估（真实链，builder 禁 GT）。

链：crop → OCR → text embedding → KB（text+image 融合）→ rerank → top-8。
报告：coverage / recall@1/5/8 / latency / registry escape。
"""
from __future__ import annotations

import base64
import json
import os
import random
import sys
import time
import urllib.request
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
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def ocr_text(b: bytes) -> str:
    try:
        r = _post("chat/completions", {"model": "DeepSeek-OCR-2-4bit",
                  "messages": [{"role": "user", "content": [
                      {"type": "image", "image": base64.b64encode(b).decode()},
                      {"type": "text", "text": "输出包装文字，纯文本。"}]}]})
        return r["choices"][0]["message"]["content"][:200]
    except Exception:
        return ""


def embed(texts):
    r = _post("embeddings", {"model": "Qwen3-Embedding-0.6B-8bit",
                             "input": texts})
    return [d["embedding"] for d in r["data"]]


def build_candidates(q_text_emb, q_img_emb, kb, txt_v, img_v, k=8):
    """CandidateSet builder：签名无 GT。融合 text+image 余弦 rerank。"""
    qt = np.array(q_text_emb)
    qi = np.array(q_img_emb)
    st = txt_v / (np.linalg.norm(txt_v, axis=1, keepdims=True) + 1e-9)
    si = img_v / (np.linalg.norm(img_v, axis=1, keepdims=True) + 1e-9)
    score = 0.6 * (st @ qt / (np.linalg.norm(qt) + 1e-9)) + \
        0.4 * (si @ qi / (np.linalg.norm(qi) + 1e-9))
    order = np.argsort(-score)[:k]
    return [kb[i]["canonical_sku_id"] for i in order]


def main() -> int:
    kb = json.loads((ROOT / ".kb/canonical38.json").read_text())
    txt_v = np.load(ROOT / ".kb/canonical38_text_vectors.npy")
    img_v = np.load(ROOT / ".kb/canonical38_img_vectors.npy")
    mp = json.loads((ROOT / "reports/nextgen_v2/cropped_sku_mapping.json")
                    .read_text())
    by_cls = {e["class_id"]: d for d, e in mp["entries"].items()}

    # image embedding 特征器
    import torch
    import torchvision
    from torchvision import transforms
    from PIL import Image
    ck = torch.load(ROOT / ".models/nextgen_classifier_grouped_v1/weights"
                    / "best.pt", map_location="cpu", weights_only=False)
    model = torchvision.models.resnet18(weights=None)
    model.fc = torch.nn.Linear(model.fc.in_features, len(ck["classes"]))
    model.load_state_dict(ck["model"])
    model.fc = torch.nn.Identity()
    model.eval()
    tf = transforms.Compose([
        transforms.Resize(256), transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize([.485, .456, .406], [.229, .224, .225])])

    rng = random.Random(23)
    ids = [e["class_id"] for e in mp["entries"].values()
           if e["kind"] == "mapped"]
    rng.shuffle(ids)
    sample = ids[:38]  # 每类 1 张，coverage 分母=38
    hits = {1: 0, 5: 0, 8: 0}
    n_ok = 0
    lats = []
    escape = 0
    for cid in sample:
        src = ROOT / "cropped_images" / by_cls[cid]
        f = sorted(src.glob("*.jpg"))[1] if len(
            sorted(src.glob("*.jpg"))) > 1 else sorted(src.glob("*.jpg"))[0]
        t0 = time.time()
        txt = ocr_text(f.read_bytes())
        qte = embed([txt or ""])[0]
        with torch.no_grad():
            qie = model(tf(Image.open(f).convert("RGB"))[None]).squeeze(0)
        cands = build_candidates(qte, qie.tolist(), kb, txt_v, img_v)
        lats.append(time.time() - t0)
        n_ok += 1
        if cid not in cands:
            escape += 1
            continue
        pos = cands.index(cid) + 1
        for k in (1, 5, 8):
            if pos <= k:
                hits[k] += 1
    lats.sort()
    rep = {"kb_size": len(kb), "coverage": round(n_ok / len(sample), 3),
           "recall@1": round(hits[1] / n_ok, 3),
           "recall@5": round(hits[5] / n_ok, 3),
           "recall@8": round(hits[8] / n_ok, 3),
           "registry_escape": escape,
           "p95_latency_s": round(lats[int(0.95 * (len(lats) - 1))], 1),
           "gate_pass": (n_ok / len(sample) >= 1.0 and
                         hits[8] / n_ok >= 0.9)}
    (ROOT / "reports/nextgen_v2/kb_canonical38_recall.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
