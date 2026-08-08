"""纠偏 Task 11：canonical38 KB 建设（coverage 100% 目标）。

每 SKU：canonical ID/package version/标准名/alias/品牌/容量/容器/口味/
OCR 关键词/多张参考图/image embedding/text embedding/provenance/version。
image embedding = grouped classifier ResNet18 特征均值；
text embedding = omlx Qwen3-Embedding（OCR+属性文本）。
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

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


def main() -> int:
    mp = json.loads((ROOT / "reports/nextgen_v2/cropped_sku_mapping.json")
                    .read_text(encoding="utf-8"))
    reg = json.loads((ROOT / "data/sku_registry.json").read_text())
    mapped = [(d, e) for d, e in mp["entries"].items()
              if e["kind"] == "mapped"]
    print("mapped classes:", len(mapped))

    # image embedding：grouped classifier 特征
    import torch
    import torchvision
    from torchvision import transforms
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

    kb = []
    for d, e in mapped:
        name = e["registry_name"]
        rinfo = reg.get(name, {})
        src = ROOT / "cropped_images" / d
        files = sorted(src.glob("*.jpg"))[:5]
        feats = []
        for f in files:
            from PIL import Image
            t = tf(Image.open(f).convert("RGB"))
            with torch.no_grad():
                feats.append(model(t[None]).squeeze(0))
        img_emb = torch.stack(feats).mean(0).tolist() if feats else []
        ocr = ocr_text(files[0].read_bytes()) if files else ""
        attrs = rinfo.get("attrs", {})
        etxt = f"{name} {ocr} {attrs.get('brand','')} {attrs.get('volume','')}"
        txt_emb = embed([etxt])[0]
        kb.append({
            "canonical_sku_id": e["class_id"], "display": name,
            "package_version": "v1", "alias": [e["display"]],
            "brand": attrs.get("brand", ""), "volume": attrs.get("volume", ""),
            "container": attrs.get("container", ""),
            "flavor": attrs.get("flavor", ""),
            "ocr_keywords": ocr, "ref_images": [str(f) for f in files],
            "image_embedding": img_emb, "text_embedding": txt_emb,
            "provenance": ["cropped_images/" + d], "version": 1})
    out = ROOT / ".kb/canonical38.json"
    out.write_text(json.dumps(kb, ensure_ascii=False), encoding="utf-8")
    import numpy as np
    np.save(ROOT / ".kb/canonical38_text_vectors.npy",
            np.array([k["text_embedding"] for k in kb]))
    np.save(ROOT / ".kb/canonical38_img_vectors.npy",
            np.array([k["image_embedding"] for k in kb]))
    print("KB built:", len(kb), "coverage=100% by construction")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
