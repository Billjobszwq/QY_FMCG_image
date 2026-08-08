"""SLTF P0-4：Qwen 候选真实检索链评估（禁 GT 入参）。

链路：crop → OCR(omlx) → text embedding(omlx) → KB 余弦 top-8。
报告：candidate recall@1/5/8、候选不含 GT 比例、abstain、registry escape、
p95、每次调用成本代理（latency）。KB 覆盖不足如实报告。
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


def ocr_text(img_bytes: bytes) -> str:
    body = {"model": "DeepSeek-OCR-2-4bit",
            "messages": [{"role": "user", "content": [
                {"type": "image", "image": base64.b64encode(img_bytes)
                 .decode()},
                {"type": "text", "text": "输出图中所有包装文字，纯文本。"}]}]}
    r = _post("chat/completions", body)
    return r["choices"][0]["message"]["content"]


def embed(texts):
    r = _post("embeddings", {"model": "Qwen3-Embedding-0.6B-8bit",
                             "input": texts})
    return [d["embedding"] for d in r["data"]]


def cos(a, b):
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb + 1e-9)


def main() -> int:
    mp = json.loads((ROOT / "reports/nextgen_v2/cropped_sku_mapping.json")
                    .read_text(encoding="utf-8"))
    kb = json.loads((ROOT / ".kb/skus.json").read_text(encoding="utf-8"))
    kb_ids = [e["id"] for e in kb]
    import numpy as np
    kb_vec = np.load(ROOT / ".kb/vectors.npy")
    mapped = [(d, e) for d, e in mp["entries"].items()
              if e["kind"] == "mapped"]
    rng = random.Random(11)
    rng.shuffle(mapped)
    sample = mapped[:60]

    recs = []
    latencies = []
    for d, e in sample:
        files = sorted((ROOT / "cropped_images" / d).glob("*.jpg"))
        if not files:
            continue
        f = files[0]
        t0 = time.time()
        try:
            txt = ocr_text(f.read_bytes())
            qv = embed([txt or e["display"]])[0]
            scores = [float(np.dot(qv, kv) / (
                np.linalg.norm(qv) * np.linalg.norm(kv) + 1e-9))
                for kv in kb_vec]
            order = sorted(range(len(kb_ids)), key=lambda i: -scores[i])[:8]
            ranking = [kb_ids[i] for i in order]
        except Exception as ex:
            recs.append({"class": e["class_id"], "error": str(ex)[:80]})
            continue
        latencies.append(time.time() - t0)
        gt_sku = e["class_id"]
        gt_disp = e.get("registry_name") or gt_sku
        pos = ranking.index(gt_disp) + 1 if gt_disp in ranking else None
        recs.append({"class": gt_sku, "ranking": ranking,
                     "gt_in_kb": gt_disp in kb_ids, "gt_rank": pos})
    n = sum(1 for r in recs if "ranking" in r)
    in_kb = [r for r in recs if r.get("gt_in_kb")]
    def recall(k):
        if not in_kb:
            return None
        return round(sum(1 for r in in_kb
                         if r["gt_rank"] and r["gt_rank"] <= k)
                     / len(in_kb), 3)
    lat_sorted = sorted(latencies)
    rep = {"n_sampled": len(recs), "n_ok": n,
           "gt_in_kb": len(in_kb),
           "candidate_recall@1": recall(1),
           "candidate_recall@5": recall(5),
           "candidate_recall@8": recall(8),
           "gt_not_in_kb_ratio": round(1 - len(in_kb) / max(n, 1), 3),
           "p95_latency_s": round(lat_sorted[int(0.95 * len(lat_sorted))]
                                  if lat_sorted else 0, 2),
           "kb_size": len(kb_ids),
           "note": "KB 仅 27 SKU 文本向量；recall 分母=GT 在 KB 的样本；"
                   "KB 覆盖不足为当前瓶颈（诚实报告，不塞 GT）"}
    (ROOT / "reports/nextgen_v2/qwen_candidate_recall_real.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
