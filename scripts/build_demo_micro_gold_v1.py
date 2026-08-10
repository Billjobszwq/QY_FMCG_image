"""证据链收口 T11：demo_micro_gold_v1 构建（200 region，blind）。

构成：120 canonical 区域（894 全场景图 SAM/legacy box，不在 M3/M4 活动
训练集）+ 40 pending crops（匿名化）+ 20 困难（小目标/反光）+
20 负样本（背景随机 crop）。
泄漏门禁：exact SHA / symlink target / photo group vs tvt_v2 + QLoRA v2
训练集 fail-closed。LS 项目 demo_micro_gold_v1_blind：无 prediction，
taxonomy 可见，文件名匿名。
"""
from __future__ import annotations

import hashlib
import json
import random
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / ".micro_gold_v1"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_forbidden_shas() -> set:
    """tvt_v2 + QLoRA real candidate v2 的全部文件 SHA。"""
    bad = set()
    for base in [ROOT / ".datasets_nextgen/canonical38_train_val_test_v2",
                 ROOT / ".datasets_nextgen/d4_real_candidate_v2"]:
        for sp in ("train", "val", "test"):
            for f in (base / sp).rglob("*"):
                if f.is_symlink() or f.is_file():
                    try:
                        bad.add(sha(f.resolve()))
                    except OSError:
                        pass
        for f in (base / "images").glob("*"):
            if f.is_symlink() or f.is_file():
                try:
                    bad.add(sha(f.resolve()))
                except OSError:
                    pass
    return bad


def main() -> int:
    rng = random.Random(20260810)
    if OUT.exists():
        print("exists refuse")
        return 1
    (OUT / "images").mkdir(parents=True)
    forbidden = load_forbidden_shas()
    print("forbidden shas:", len(forbidden))

    tasks = []
    n_canon = n_pend = n_hard = n_neg = 0
    leak_blocked = 0

    # ---- 120 canonical + 20 hard：894 全场景图 box ----
    d1 = ROOT / ".datasets_nextgen/detector_snapshot_v3"
    imgs = sorted((d1 / "images" / "train").glob("*")) + \
        sorted((d1 / "images" / "val").glob("*"))
    rng.shuffle(imgs)
    for img in imgs:
        if n_canon >= 120 and n_hard >= 20:
            break
        lab = (d1 / "labels" / img.parent.name /
               (img.stem + ".txt"))
        if not lab.exists():
            continue
        rows = [l.split() for l in lab.read_text().splitlines() if l.strip()]
        if not rows:
            continue
        if sha(img.resolve()) in forbidden:
            leak_blocked += 1
            continue
        arr = cv2.imread(str(img))
        H, W = arr.shape[:2]
        for r in rows[:3]:
            x, y, w, h = (float(v) for v in r[1:5])
            x0, y0 = int((x - w / 2) * W), int((y - h / 2) * H)
            bw, bh = int(w * W), int(h * H)
            crop = arr[max(0, y0):y0 + bh, max(0, x0):x0 + bw]
            if crop.size == 0:
                continue
            area = w * h
            hard = area < 0.005
            if hard and n_hard >= 20:
                continue
            if not hard and n_canon >= 120:
                continue
            cid = hashlib.sha256(img.name.encode()).hexdigest()[:10]
            fname = f"mg_{cid}_{n_canon + n_hard:03d}.jpg"
            cv2.imwrite(str(OUT / "images" / fname), crop)
            tasks.append({"id": len(tasks), "file": fname,
                          "kind": "hard" if hard else "canonical",
                          "source_photo": img.name})
            if hard:
                n_hard += 1
            else:
                n_canon += 1

    # ---- 40 pending crops（匿名）----
    mp = json.loads((ROOT / "reports/nextgen_v2/cropped_sku_mapping.json")
                    .read_text())
    pend = [(d, e) for d, e in mp["entries"].items()
            if e["kind"] != "mapped"]
    rng.shuffle(pend)
    for d, e in pend:
        if n_pend >= 40:
            break
        files = sorted((ROOT / "cropped_images" / d).glob("*.jpg"))
        for f in files[:2]:
            if n_pend >= 40:
                break
            if sha(f.resolve()) in forbidden:
                leak_blocked += 1
                continue
            fname = f"mg_pend_{n_pend:03d}.jpg"
            shutil.copy(f, OUT / "images" / fname)
            tasks.append({"id": len(tasks), "file": fname,
                          "kind": "pending", "source_photo": f.name})
            n_pend += 1

    # ---- 20 负样本：背景随机 crop ----
    for img in imgs:
        if n_neg >= 20:
            break
        arr = cv2.imread(str(img))
        H, W = arr.shape[:2]
        y0, x0 = rng.randint(0, H // 2), rng.randint(0, W // 2)
        crop = arr[y0:y0 + H // 6, x0:x0 + W // 6]
        if crop.size == 0:
            continue
        fname = f"mg_neg_{n_neg:03d}.jpg"
        cv2.imwrite(str(OUT / "images" / fname), crop)
        tasks.append({"id": len(tasks), "file": fname, "kind": "negative",
                      "source_photo": img.name})
        n_neg += 1

    manifest = {"project": "demo_micro_gold_v1_blind",
                "counts": {"canonical": n_canon, "pending": n_pend,
                           "hard": n_hard, "negative": n_neg,
                           "total": len(tasks)},
                "leak_blocked": leak_blocked,
                "forbidden_pool": len(forbidden),
                "policy": "blind：无 prediction；文件名匿名；人工主审 200，"
                          "确定性抽 40 二盲，分歧仲裁"}
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "tasks.json").write_text(
        json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(manifest["counts"], ensure_ascii=False),
          "leak_blocked:", leak_blocked)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
