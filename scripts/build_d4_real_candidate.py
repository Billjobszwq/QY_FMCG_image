"""纠偏 Task 11：真实 CandidateSet 的 M4 训练数据（禁 GT 入参）。

候选来自真实链（OCR→text emb + image emb 融合 rerank top-8）。
GT 在候选中 → 答案编号；不在 → abstain（"none"）。
"""
from __future__ import annotations

import base64
import json
import os
import random
import sys
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

OMLX = os.environ.get("OMLX_BASE_URL", "http://127.0.0.1:8455/v1")
API_KEY = os.environ.get("OMLX_API_KEY", "1234")


def _post(path, body):
    req = urllib.request.Request(
        f"{OMLX}/{path}", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {API_KEY}",
                 "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def ocr_text(b):
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
    out = ROOT / ".datasets_nextgen/d4_real_candidate_v2"
    if out.exists():
        print("exists skip")
        return 1
    out.mkdir(parents=True)
    (out / "images").mkdir()
    kb = json.loads((ROOT / ".kb/canonical38.json").read_text())
    txt_v = np.load(ROOT / ".kb/canonical38_text_vectors.npy")
    img_v = np.load(ROOT / ".kb/canonical38_img_vectors.npy")
    mp = json.loads((ROOT / "reports/nextgen_v2/cropped_sku_mapping.json")
                    .read_text())
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

    rng = random.Random(31)
    records = []
    n_abstain = 0
    ocr_cache: dict = {}
    for d, e in mp["entries"].items():
        if e["kind"] != "mapped":
            continue
        src = ROOT / "cropped_images" / d
        files = sorted(src.glob("*.jpg"))
        if e["class_id"] not in ocr_cache and files:
            ocr_cache[e["class_id"]] = ocr_text(files[0].read_bytes())
        cls_ocr = ocr_cache.get(e["class_id"], "")
        for f in files[:30]:
            txt = cls_ocr
            qte = embed([txt or ""])[0]
            with torch.no_grad():
                qie = model(tf(Image.open(f).convert("RGB"))[None]
                            ).squeeze(0).tolist()
            qt = np.array(qte)
            qi = np.array(qie)
            st = txt_v / (np.linalg.norm(txt_v, axis=1, keepdims=True) + 1e-9)
            si = img_v / (np.linalg.norm(img_v, axis=1, keepdims=True) + 1e-9)
            score = 0.6 * (st @ qt / (np.linalg.norm(qt) + 1e-9)) + \
                0.4 * (si @ qi / (np.linalg.norm(qi) + 1e-9))
            order = np.argsort(-score)[:8]
            cands = [kb[i]["display"] for i in order]
            gt = e["registry_name"]
            if gt in cands:
                ans = str(cands.index(gt) + 1)
            else:
                ans = "none"
                n_abstain += 1
            fname = f"{e['class_id']}__{f.name}"
            dst = out / "images" / fname
            if not dst.exists():
                dst.symlink_to(f)
            cand_txt = "\n".join(f"{i+1}. {c}" for i, c in enumerate(cands))
            records.append({
                "messages": [
                    {"role": "user", "content": [
                        {"type": "image", "image": f"images/{fname}"},
                        {"type": "text",
                         "text": "货架商品切图。候选 SKU：\n" + cand_txt +
                                 "\n最匹配编号？都不匹配回答 none。"}]},
                    {"role": "assistant", "content": [
                        {"type": "text", "text": ans}]}],
                "images": [str(out / "images" / fname)],
                "meta": {"class_id": e["class_id"], "answer": ans}})
    rng.shuffle(records)
    (out / "train.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records),
        encoding="utf-8")
    import hashlib
    (out / "manifest.json").write_text(json.dumps({
        "schema_version": "vlm-snapshot.v3-real-candidate",
        "n_samples": len(records), "n_abstain": n_abstain,
        "candidate_builder": "real_retrieval_no_gt",
        "manifest_hash": hashlib.sha256(json.dumps(
            [r["meta"] for r in records], sort_keys=True).encode()
        ).hexdigest()}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"samples": len(records), "abstain": n_abstain}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
