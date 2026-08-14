"""全照片池质量筛选：反光 / 货架倾斜 / 模糊（SAM 精修前置门禁）。

口径（用户指令：全照片集不抽样，可适当提高门槛）：
- 池 = batch2_v4(6510) ∪ sku_v6(9976)，208 类对齐；内容 SHA 去重；
- V2 处置（VLM-008）：缺水平线→manual_review（tilt_unobservable），
  单一弱启发式→warn，≥2 维 fail 才自动 reject；
- 每条判定保留原图 SHA、规则版本、分数、阈值与证据；
- 旧 tilt reject 历史 JSON 不改写；本脚本只新建带时间戳证据文件。

用法：
  python3 -m scripts.run_quality_screen
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.insert(0, str(ROOT))

from src.training.quality_gate import (  # noqa: E402
    QUALITY_GATE_VERSION, THRESHOLDS, assess_quality,
)

SOURCES = [".datasets/batch2_v4", ".datasets/sku_v6"]


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()

    files: list[tuple[str, Path]] = []
    for src in SOURCES:
        for split in ("train", "val"):
            d = ROOT / src / "images" / split
            files += [(f"{src}:{split}", p) for p in sorted(d.glob("*.jpg"))]
    files.sort(key=lambda t: t[1].name)
    if a.limit:
        files = files[:a.limit]

    seen_sha: dict[str, str] = {}   # sha -> 首个文件名
    records = []
    dup = 0
    t0 = time.time()
    for i, (src, p) in enumerate(files):
        sha = sha256_file(p)
        if sha in seen_sha:
            dup += 1
            records.append({"file": p.name, "source": src, "sha256": sha,
                            "decision": "duplicate",
                            "duplicate_of": seen_sha[sha]})
            continue
        seen_sha[sha] = p.name
        try:
            gray = np.asarray(Image.open(p).convert("L"))
            verdict = assess_quality(gray)
            decision = {"pass": "accept", "warn": "accept_warn",
                        "manual_review": "manual_review",
                        "reject": "reject"}[verdict.disposition]
            records.append({"file": p.name, "source": src, "sha256": sha,
                            "scores": verdict.scores,
                            "thresholds": verdict.thresholds,
                            "policy_version": verdict.policy_version,
                            "decision": decision,
                            "reasons": list(verdict.reason_codes)})
        except Exception as e:  # 解码失败等：fail-closed 进人工复核
            records.append({"file": p.name, "source": src, "sha256": sha,
                            "decision": "manual_review",
                            "reasons": [f"error:{e}"]})
        if (i + 1) % 500 == 0:
            elapsed = time.time() - t0
            eta = elapsed / (i + 1) * (len(files) - i - 1)
            print(f"[{i+1}/{len(files)}] {elapsed:.0f}s 已用, ETA {eta:.0f}s",
                  flush=True)

    accept = sum(1 for r in records if r["decision"] == "accept")
    accept_warn = sum(1 for r in records if r["decision"] == "accept_warn")
    review = sum(1 for r in records if r["decision"] == "manual_review")
    reject = sum(1 for r in records if r["decision"] == "reject")
    reason_hist: dict[str, int] = {}
    for r in records:
        for reason in r.get("reasons", []):
            reason_hist[reason] = reason_hist.get(reason, 0) + 1
    ev_dir = ROOT / ".eval" / "sam_refine"
    ev_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ev_path = ev_dir / f"quality_screen_{ts}.json"
    ev_path.write_text(json.dumps({
        "created_at": datetime.now().isoformat(),
        "sources": SOURCES,
        "policy_version": QUALITY_GATE_VERSION,
        "thresholds": THRESHOLDS,
        "total_files": len(files),
        "unique_sha": len(seen_sha),
        "duplicates": dup,
        "accepted": accept,
        "accepted_warn": accept_warn,
        "manual_review": review,
        "rejected": reject,
        "reason_histogram": reason_hist,
        "wall_sec": round(time.time() - t0, 1),
        "records": records,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"total": len(files), "unique": len(seen_sha),
                      "duplicate": dup, "accepted": accept,
                      "accept_warn": accept_warn, "manual_review": review,
                      "rejected": reject,
                      "reasons": reason_hist, "evidence": str(ev_path)},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
