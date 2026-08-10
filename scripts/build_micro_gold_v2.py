"""Micro-Gold V2 builder（独立 raw 照片 + SAM mask + 可追踪 provisional）。

provisional 证据链：SAM mask（sha+score）+ classifier 版本+conf（仅审计侧）。
hard 需真实质量证据；negative 与全部 mask 零交集；每照片至多 1 region；
跨 stratum 零 photo 重叠；forbidden index fail-closed；不足诚实报告。
"""
from __future__ import annotations

import hashlib
import json
import random
import subprocess
from collections import Counter
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

QPOL = "qpol_n2_v1"


def quality_metrics(crop: np.ndarray, area_ratio: float) -> dict[str, Any]:
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    bright = float(gray.mean())
    refl = float((gray > 240).mean())
    reasons = []
    if area_ratio < 0.01:
        reasons.append("tiny_object")
    if refl > 0.08:
        reasons.append("reflection")
    if blur < 60:
        reasons.append("blur")
    if bright < 70:
        reasons.append("low_light")
    if bright > 200:
        reasons.append("over_exposure")
    return {"blur": round(blur, 1), "brightness": round(bright, 1),
            "reflection": round(refl, 3), "area_ratio": area_ratio,
            "reasons": reasons, "policy": QPOL}


def sample_strata(candidates: list[dict], targets: dict[str, int],
                  seed: int = 7) -> dict[str, list]:
    """candidates: 每 photo 至多 1 条；跨 stratum photo 互斥；
    canonical 每类 ≥3 groups 目标按类均衡。返回 {stratum: [cand]}。"""
    rng = random.Random(seed)
    out: dict[str, list] = {k: [] for k in targets}
    used_photos: set = set()

    def take(stratum, pool, n, per_class=None):
        rng.shuffle(pool)
        for c in pool:
            if len(out[stratum]) >= n:
                break
            if c["photo"] in used_photos:
                continue
            if per_class is not None:
                cls = c["provisional_sku"]
                if sum(1 for x in out[stratum]
                       if x["provisional_sku"] == cls) >= per_class:
                    continue
            out[stratum].append(c)
            used_photos.add(c["photo"])

    canon = [c for c in candidates if c["stratum"] == "canonical"]
    # 每类先保 3，再补到 target
    take("canonical", canon, targets["canonical"], per_class=3)
    take("canonical", [c for c in canon if c["photo"] not in used_photos],
         targets["canonical"])
    take("pending", [c for c in candidates if c["stratum"] == "pending"],
         targets["pending"])
    take("hard", [c for c in candidates if c["stratum"] == "hard"],
         targets["hard"])
    take("negative", [c for c in candidates if c["stratum"] == "negative"],
         targets["negative"])
    return out


def main() -> int:
    ap = __import__("argparse").ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".micro_gold_v2"))
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        print("exists refuse")
        return 1
    staging = out.with_name(".staging-micro_gold_v2")
    if staging.exists():
        import shutil
        shutil.rmtree(staging)
    (staging / "images").mkdir(parents=True)

    # forbidden index
    fa = json.loads((ROOT / "reports/nextgen_v2/forbidden_index_v2"
                     / "forbidden_identity_index_v2.audit.json").read_text())
    forbidden_shas = set()
    with open(ROOT / "reports/nextgen_v2/forbidden_index_v2"
              / "forbidden_identity_index_v2.jsonl") as f:
        for line in f:
            r = json.loads(line)
            if r.get("sha"):
                forbidden_shas.add(r["sha"])

    # classifier models
    import torch
    import torchvision
    from torchvision import transforms
    tf = transforms.Compose([
        transforms.Resize(256), transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize([.485, .456, .406], [.229, .224, .225])])

    def load_m(path, n_cls):
        ck = torch.load(path, map_location="cpu", weights_only=False)
        m = torchvision.models.resnet18(weights=None)
        m.fc = torch.nn.Linear(m.fc.in_features, n_cls)
        m.load_state_dict(ck["model"])
        m.eval()
        return m, ck["classes"]

    m38, cls38 = load_m(ROOT / ".models/m3_tvt_e1_v2/weights/best.pt", 38)
    m83, cls83 = load_m(ROOT / ".models/nextgen_classifier_grouped_v1"
                        / "weights/best.pt", 83)
    mp = json.loads((ROOT / "reports/nextgen_v2/cropped_sku_mapping.json")
                    .read_text())
    mapped38 = {e["class_id"]: e["registry_name"]
                for e in mp["entries"].values() if e["kind"] == "mapped"}
    pending45 = {e["class_id"] for e in mp["entries"].values()
                 if e["kind"] != "mapped"}

    candidates = []
    unresolved = 0
    leak_blocked = 0
    with open(ROOT / "reports/nextgen_v2/sam_raw_photo_masks.jsonl") as f:
        photos = [json.loads(l) for l in f]
    for ph in photos:
        img = cv2.imread(ph["photo"])
        if img is None:
            continue
        psha = hashlib.sha256(img.tobytes()).hexdigest()
        if psha in forbidden_shas:
            leak_blocked += 1
            continue
        h, w = img.shape[:2]
        best_per_stratum: dict[str, dict] = {}
        for mi, mk in enumerate(ph["masks"]):
            x0, y0, x1, y1 = mk["bbox"]
            crop = img[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            q = quality_metrics(crop, mk["area_ratio"])
            from PIL import Image as _Image
            with torch.no_grad():
                pil = _Image.fromarray(
                    cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
                o38 = torch.softmax(m38(tf(pil)[None]), 1)[0]
                o83 = torch.softmax(m83(tf(pil)[None]), 1)[0]
            c38, p38 = int(o38.argmax()), float(o38.max())
            c83, p83 = int(o83.argmax()), float(o83.max())
            base = {"photo": ph["photo"], "photo_sha": psha,
                    "mask_idx": mi, "bbox": mk["bbox"],
                    "quality": q, "crop": crop,
                    "mask_score": mk["score"],
                    "sam_evidence": f"sam2.1_hiera_small@"
                                    f"{mk['score']:.2f}"}
            if q["reasons"]:
                cand = {**base, "stratum": "hard",
                        "provisional_sku": cls38[c38],
                        "provisional_source": "sam_mask+m3_tvt_e1_v2",
                        "hard_reasons": q["reasons"]}
                if (best_per_stratum.get("hard", {}).get(
                        "quality", {}).get("reasons") is None):
                    best_per_stratum["hard"] = cand
            if p38 >= 0.5 and not q["reasons"]:
                cand = {**base, "stratum": "canonical",
                        "provisional_sku": cls38[c38],
                        "provisional_source": "sam_mask+m3_tvt_e1_v2",
                        "conf": p38}
                prev = best_per_stratum.get("canonical")
                if prev is None or p38 > prev["conf"]:
                    best_per_stratum["canonical"] = cand
            elif cls83[c83] in pending45 and p83 >= 0.4:
                cand = {**base, "stratum": "pending",
                        "provisional_sku": cls83[c83],
                        "provisional_source": "sam_mask+grouped_v1",
                        "conf": p83}
                best_per_stratum.setdefault("pending", cand)
        # negative：与全部 mask 零交集的背景
        allmask = np.zeros((h, w), bool)
        for mk in ph["masks"]:
            allmask[y0:y1, x0:x1] |= True if False else allmask[y0:y1, x0:x1]
        # 重建每 mask
        for mk in ph["masks"]:
            bx0, by0, bx1, by1 = mk["bbox"]
            mm = np.zeros((h, w), bool)
            for seg in mk["rle"].split(","):
                s, ln = seg.split(":")
                mm.ravel(order="F")[int(s):int(s) + int(ln)] = True
            allmask |= mm
        rngn = random.Random(a.seed + hash(ph["photo"]) % 1000)
        for _ in range(3):
            ny = rngn.randint(0, max(h - 80, 1))
            nx = rngn.randint(0, max(w - 80, 1))
            box = allmask[ny:ny + 80, nx:nx + 80]
            if box.size and not box.any():
                best_per_stratum["negative"] = {
                    "photo": ph["photo"], "photo_sha": psha,
                    "bbox": [nx, ny, nx + 80, ny + 80],
                    "stratum": "negative",
                    "quality": quality_metrics(
                        img[ny:ny + 80, nx:nx + 80], 0.0),
                    "negative_verified": "zero_overlap_with_all_sam_masks",
                    "provisional_sku": None,
                    "provisional_source": None}
                break
        for st, cand in best_per_stratum.items():
            candidates.append(cand)

    sampled = sample_strata(candidates, {"canonical": 120, "pending": 40,
                                         "hard": 20, "negative": 20},
                            seed=a.seed)
    tasks = []
    n = 0
    for st, lst in sampled.items():
        for c in lst:
            x0, y0, x1, y1 = c["bbox"]
            crop = c.get("crop")
            if crop is None:
                img = cv2.imread(c["photo"])
                crop = img[y0:y1, x0:x1]
            fname = f"mgv2_{n:04d}.jpg"
            cv2.imwrite(str(staging / "images" / fname), crop)
            tasks.append({"micro_gold_task_id": f"mgv2_{n:04d}",
                          "anonymous_image_name": fname,
                          "image_sha": hashlib.sha256(
                              cv2.imencode(".jpg", crop)[1].tobytes()
                          ).hexdigest(),
                          "original_photo_sha": c["photo_sha"],
                          "original_photo_id": Path(c["photo"]).name,
                          "source_batch": "raw_photos_1106_1107_pepsi",
                          "leakage_group_id": c["photo_sha"][:16],
                          "stratum": st,
                          "provisional_sku": c.get("provisional_sku"),
                          "provisional_source": c.get("provisional_source"),
                          "quality": c.get("quality"),
                          "hard_reasons": c.get("hard_reasons"),
                          "negative_verified": c.get("negative_verified"),
                          "source_box": c["bbox"],
                          "crop_builder_version": "mgv2-builder-v1",
                          "forbidden_index_result": "pass",
                          "sampling_seed": a.seed})
            n += 1
    manifest = {"schema_version": "micro-gold-v2",
                "dataset": "demo_micro_gold_v2",
                "builder_hash": hashlib.sha256(
                    Path(__file__).read_bytes()).hexdigest()[:16],
                "source_commit": subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT,
                    capture_output=True, text=True).stdout.strip(),
                "forbidden_index_hash": fa["index_hash"],
                "seed": a.seed,
                "target_counts": {"canonical": 120, "pending": 40,
                                  "hard": 20, "negative": 20},
                "actual_counts": {k: len(v) for k, v in sampled.items()},
                "unique_photos": len({t["original_photo_id"]
                                      for t in tasks}),
                "unresolved_identity": unresolved,
                "leak_blocked": leak_blocked,
                "class_distribution": dict(sorted(
                    Counter(t["provisional_sku"] for t in
                            sampled["canonical"]).items())),
                "hard_reason_distribution": dict(sorted(
                    Counter(r for t in sampled["hard"]
                            for r in (t.get("hard_reasons") or [])
                            ).items())) if sampled["hard"] else {},
                "tasks": tasks}
    manifest["manifest_hash"] = hashlib.sha256(
        json.dumps({k: v for k, v in manifest.items() if k != "manifest_hash"},
                   sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    (staging / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    import shutil
    shutil.move(str(staging), str(out))
    print(json.dumps({"actual": manifest["actual_counts"],
                      "unique_photos": manifest["unique_photos"],
                      "leak_blocked": leak_blocked}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
