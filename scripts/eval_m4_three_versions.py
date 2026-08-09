"""状态收口 T7：M4 三版本独立裁决评估（禁重训）。

版本：base / 旧 cropped adapter / 新 real-candidate adapter。
holdout：每类 files[30:33]（QLoRA 训练未用）+ pending 类 abstain 样本。
CandidateSet 真实链（签名无 GT）。报告全指标+错误账本。
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]

OMLX = os.environ.get("OMLX_BASE_URL", "http://127.0.0.1:8455/v1")
API_KEY = os.environ.get("OMLX_API_KEY", "1234")

import urllib.request


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


def build_candidates(qte, qie, txt_v, img_v, kb, k=8):
    qt, qi = np.array(qte), np.array(qie)
    st = txt_v / (np.linalg.norm(txt_v, axis=1, keepdims=True) + 1e-9)
    si = img_v / (np.linalg.norm(img_v, axis=1, keepdims=True) + 1e-9)
    score = 0.6 * (st @ qt / (np.linalg.norm(qt) + 1e-9)) + \
        0.4 * (si @ qi / (np.linalg.norm(qi) + 1e-9))
    return [kb[i]["display"] for i in np.argsort(-score)[:k]]


def main() -> int:
    from mlx_vlm import generate, load
    import torch
    import torchvision
    from torchvision import transforms
    from PIL import Image

    kb = json.loads((ROOT / ".kb/canonical38.json").read_text())
    txt_v = np.load(ROOT / ".kb/canonical38_text_vectors.npy")
    img_v = np.load(ROOT / ".kb/canonical38_img_vectors.npy")
    mp = json.loads((ROOT / "reports/nextgen_v2/cropped_sku_mapping.json")
                    .read_text())

    ck = torch.load(ROOT / ".models/nextgen_classifier_grouped_v1/weights"
                    / "best.pt", map_location="cpu", weights_only=False)
    feat = torchvision.models.resnet18(weights=None)
    feat.fc = torch.nn.Linear(feat.fc.in_features, len(ck["classes"]))
    feat.load_state_dict(ck["model"])
    feat.fc = torch.nn.Identity()
    feat.eval()
    tf = transforms.Compose([
        transforms.Resize(256), transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize([.485, .456, .406], [.229, .224, .225])])

    # holdout：训练用 files[:30]，取 files[30:33]
    samples = []
    ocr_cache = {}
    for d, e in mp["entries"].items():
        if e["kind"] != "mapped":
            continue
        files = sorted((ROOT / "cropped_images" / d).glob("*.jpg"))
        if e["class_id"] not in ocr_cache and files:
            ocr_cache[e["class_id"]] = ocr_text(files[0].read_bytes())
        for f in files[30:33]:
            samples.append({"file": f, "gt": e["registry_name"],
                            "class_id": e["class_id"],
                            "is_canonical": True,
                            "ocr": ocr_cache[e["class_id"]]})
    # abstain 样本：pending 类（不在 KB）
    pend = [(d, e) for d, e in mp["entries"].items()
            if e["kind"] != "mapped"]
    for d, e in pend[:8]:
        files = sorted((ROOT / "cropped_images" / d).glob("*.jpg"))
        if files:
            samples.append({"file": files[0], "gt": None,
                            "class_id": e["class_id"],
                            "is_canonical": False, "ocr": ""})
    print("holdout samples:", len(samples))

    # 预计算候选
    for s in samples:
        qte = embed([s["ocr"] or ""])[0]
        with torch.no_grad():
            qie = feat(tf(Image.open(s["file"]).convert("RGB"))[None]
                       ).squeeze(0).tolist()
        s["cands"] = build_candidates(qte, qie, txt_v, img_v, kb)

    versions = [
        ("base", None),
        ("old_cropped_adapter",
         str(ROOT / ".models/nextgen_vlm_cropped_v1/adapters")),
        ("new_real_adapter",
         str(ROOT / ".models/nextgen_vlm_real_candidate_v1/adapters"))]

    results = {}
    for vname, adapter in versions:
        model, processor = load(
            "mlx-community/Qwen3-VL-4B-Instruct-4bit",
            adapter_path=adapter)
        hit = tot = 0
        accepted = acc_ok = 0
        abstain_n = abstain_ok = 0
        false_accept = false_reject = 0
        lats, toks = [], []
        errors = []
        for s in samples:
            cand_txt = "\n".join(f"{i+1}. {c}" for i, c in
                                 enumerate(s["cands"]))
            prompt = f"货架商品切图。候选 SKU：\n{cand_txt}\n最匹配编号？都不匹配回答 none。"
            t0 = time.time()
            out = generate(model, processor, prompt,
                           image=str(s["file"]), max_tokens=8,
                           verbose=False)
            dt = time.time() - t0
            txt = out["text"].strip()
            lats.append(dt)
            toks.append(out.get("token_count", 0))
            gt_pos = (s["cands"].index(s["gt"]) + 1
                      if s["gt"] in s["cands"] else None)
            tot += 1
            if txt == "none":
                abstain_n += 1
                if not s["is_canonical"]:
                    abstain_ok += 1
                else:
                    false_reject += 1
                    errors.append({"file": s["file"].name,
                                   "gt": s["gt"], "pred": "none"})
            elif txt.isdigit():
                accepted += 1
                if s["is_canonical"] and int(txt) == gt_pos:
                    hit += 1
                    acc_ok += 1
                elif s["is_canonical"]:
                    errors.append({"file": s["file"].name,
                                   "gt": s["gt"], "pred": txt})
                else:
                    false_accept += 1
                    errors.append({"file": s["file"].name,
                                   "gt": None, "pred": txt})
            else:
                errors.append({"file": s["file"].name, "gt": s["gt"],
                               "pred": txt})
        lats.sort()
        results[vname] = {
            "vlm_top1": round(hit / max(tot, 1), 3),
            "accepted_precision": round(acc_ok / max(accepted, 1), 3),
            "coverage": round(accepted / max(tot, 1), 3),
            "abstain_n": abstain_n,
            "abstain_precision": round(abstain_ok / max(abstain_n, 1), 3),
            "false_accept": false_accept,
            "false_reject": false_reject,
            "p50_s": round(lats[len(lats) // 2], 1),
            "p95_s": round(lats[int(0.95 * (len(lats) - 1))], 1),
            "tokens_per_region": round(sum(toks) / max(tot, 1), 1),
            "errors": errors[:20]}
        del model, processor
        print(vname, json.dumps({k: results[vname][k] for k in (
            "vlm_top1", "accepted_precision", "abstain_precision")}))

    # 候选 recall（链共享）
    rec = {1: 0, 5: 0, 8: 0}
    n_can = 0
    for s in samples:
        if not s["is_canonical"]:
            continue
        n_can += 1
        if s["gt"] in s["cands"]:
            pos = s["cands"].index(s["gt"]) + 1
            for k in rec:
                if pos <= k:
                    rec[k] += 1
    rep = {"candidate_recall": {f"@{k}": round(v / max(n_can, 1), 3)
                                for k, v in rec.items()},
           "versions": results,
           "holdout": len(samples),
           "note": "holdout 独立于 QLoRA 训练样本；abstain 样本来自 pending 类"}
    (ROOT / "reports/nextgen_v2/m4_three_version_eval.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1))
    print(json.dumps(rep["candidate_recall"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
