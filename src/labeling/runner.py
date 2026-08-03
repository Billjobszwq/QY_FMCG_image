"""标注管线编排（双模式）。自动产出=提案/预标注，绝不直接进训练；每张照片入人工复核队列。

模式 B（默认，带它模种子）：解析+画框+打标签+复核/纠错，提案给人工确认。
模式 A：大模型从零定位+识别。approved/ 只由人工 approved 生成（见 emit.apply_review_to_approved）。
用法：python -m src.labeling.runner --mode B --max-photos 1"""
from __future__ import annotations

import argparse
import json

from PIL import Image

from ..catalog.alias_registry import build_registry
from ..catalog.store import LocalStore
from ..common import paths
from ..common.config import PROJECT_ROOT
from . import assign as A
from . import emit as E
from . import localize as L

REF = PROJECT_ROOT / "搭建初期P1"
FIELD = PROJECT_ROOT / ".field"
KB = PROJECT_ROOT / ".kb"


def _blob(sha):
    return FIELD / "blobs" / sha[:2] / sha


def _priority(sidecar):
    p = 0
    for s in sidecar:
        if s.get("needs_review"):
            p += 2
        if s.get("confidence") == "low":
            p += 1
        if s.get("decision") in ("unknown", "conflict"):
            p += 2
    return p


def run(mode="B", max_photos=1, topk=10):
    m = json.load(open(FIELD / "manifest.json", encoding="utf-8"))
    reg = build_registry(sorted(p.name for p in REF.iterdir() if p.is_dir()), PROJECT_ROOT / "data" / "sku_aliases.json")
    store = LocalStore(KB)
    ids, vec = store.load_vectors()
    classmap, class_ids = E.build_classmap(reg)
    E.write_classmap(class_ids)

    queue, summary = [], {"mode": mode, "photos": 0, "seeds": 0, "proposals": 0, "queued": 0, "agree": 0, "disagree_or_unconf": 0}
    for p in m["photos"][:max_photos]:
        sha = p["image"].get("sha256") or p["image"].get("sha")
        if not sha:
            continue
        img = Image.open(_blob(sha)).convert("RGB")
        W, H = img.size
        seeds = p["annotations"] if mode.upper() == "B" else None
        regions = [(b, None) for b in L.discover_regions(_blob(sha).read_bytes(), W, H)] if mode.upper() == "A" else [(L.seed_to_box(s, W, H), s) for s in (seeds or [])]

        draft, sidecar = [], []
        for box, seed in regions:
            x1, y1, x2, y2 = (int(v) for v in box)
            crop = img.crop((max(0, x1), max(0, y1), min(W, x2), min(H, y2)))
            if crop.width < 8 or crop.height < 8:
                continue
            prior = seed.get("name") if seed else None
            r = A.assign(crop, store, ids, vec, reg, prior_name=prior, topk=topk)
            cls = classmap.get(r["decision"])
            if cls is not None:
                draft.append((cls, box))
            sidecar.append({"box": box, "seed_name": prior, **r})
            if mode.upper() == "B":
                summary["seeds"] += 1
                summary["agree" if r.get("agree") else "disagree_or_unconf"] += 1
        E.write_proposal(p["id"], draft, W, H)
        E.write_proposal_sidecar(p["id"], sidecar)
        queue.append({"asset_id": p["id"], "sname": p["meta"].get("sname"), "typename": p["meta"].get("typename"), "n_proposals": len(draft), "priority": _priority(sidecar), "status": "pending"})
        summary["photos"] += 1
        summary["proposals"] += len(draft)
        summary["queued"] += 1

    queue.sort(key=lambda q: -q["priority"])  # 最不确定的优先审
    E.write_review_queue(queue)
    summary["agree_rate"] = round(summary["agree"] / summary["seeds"], 4) if summary["seeds"] else 0.0
    summary["class_count"] = len(class_ids)
    summary["note"] = "auto=proposal only; training reads .labels/approved after human approval"
    print("LABEL_RUN", json.dumps(summary, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="B", choices=["A", "B"])
    ap.add_argument("--max-photos", type=int, default=1)
    ap.add_argument("--topk", type=int, default=10)
    a = ap.parse_args()
    run(a.mode, a.max_photos, a.topk)
