"""全照片池质量筛选：反光 / 货架倾斜 / 模糊（SAM 精修前置门禁）。

口径（用户指令：全照片集不抽样，可适当提高门槛）：
- 池 = batch2_v4(6510) ∪ sku_v6(9976)，208 类对齐；内容 SHA 去重；
- 三维分数（src.training.quality_gate）任一超阈 → reject；
- 证据落盘 .eval/sam_refine/quality_screen_<ts>.json（分数+阈值+决策）。

用法：
  /Users/zhangweiqi/miniconda3/bin/python3 -m scripts.run_quality_screen
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
    THRESHOLDS, blur_score, gate_decision, reflection_score, tilt_score,
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
            gray = np.asarray(Image.open(p).convert("L"), dtype=np.float64)
            scores = {"blur": round(blur_score(gray), 6),
                      "reflection": round(reflection_score(gray), 6),
                      "tilt": round(tilt_score(gray), 6)}
            ok, reasons = gate_decision(scores)
            records.append({"file": p.name, "source": src, "sha256": sha,
                            "scores": scores,
                            "decision": "accept" if ok else "reject",
                            "reasons": reasons})
        except Exception as e:  # 解码失败等：fail-closed
            records.append({"file": p.name, "source": src, "sha256": sha,
                            "decision": "reject", "reasons": [f"error:{e}"]})
        if (i + 1) % 500 == 0:
            elapsed = time.time() - t0
            eta = elapsed / (i + 1) * (len(files) - i - 1)
            print(f"[{i+1}/{len(files)}] {elapsed:.0f}s 已用, ETA {eta:.0f}s",
                  flush=True)

    accept = sum(1 for r in records if r["decision"] == "accept")
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
        "thresholds": THRESHOLDS,
        "total_files": len(files),
        "unique_sha": len(seen_sha),
        "duplicates": dup,
        "accepted": accept,
        "rejected": reject,
        "reason_histogram": reason_hist,
        "wall_sec": round(time.time() - t0, 1),
        "records": records,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"total": len(files), "unique": len(seen_sha),
                      "duplicate": dup, "accepted": accept, "rejected": reject,
                      "reasons": reason_hist, "evidence": str(ev_path)},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
