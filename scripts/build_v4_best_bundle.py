#!/usr/bin/env python3
"""ABOSV3 T8：构建 prod_v4_best_r1 bundle（不覆盖任何旧 bundle）。

- detector = best/sku_v4_best.pt（用户授权的 V4 best 制品）；
- classifier/registry/classes/thresholds 与 prod_20260805_v5_r1 完全一致
  （同一 SHA），保证除 detector 外零变量；
- 生成 MANIFEST.json（文件 hash/大小/来源/原因），供切换与回滚审计。

用法：python scripts/build_v4_best_bundle.py [--check-only]
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DETECTOR = ROOT / "best" / "sku_v4_best.pt"
SRC_CLASSIFIER = ROOT / ".models" / "classifier" / "best.pt"
REF_BUNDLE = ROOT / ".models" / "bundles" / "prod_20260805_v5_r1"
OUT = ROOT / ".models" / "bundles" / "prod_v4_best_r1"
BUNDLE_ID = "prod_v4_best_r1"


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(check_only: bool = False) -> int:
    if not SRC_DETECTOR.exists():
        print(f"[ERROR] V4 best 制品不存在: {SRC_DETECTOR}")
        return 1
    if not REF_BUNDLE.exists():
        print(f"[ERROR] 参照 bundle 不存在: {REF_BUNDLE}")
        return 1
    det_sha = sha(SRC_DETECTOR)
    clf_sha = sha(SRC_CLASSIFIER)
    manifest = {
        "bundle_id": BUNDLE_ID,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "production_combo": {"detector": "detector.pt",
                             "classifier": "classifier.pt"},
        "metrics": {
            "note": "sku_v4 best（批1 val 口径，历史记录）；与 v5 bundle"
                    " 非同一评估集，数字不可直接比较；本次切换以 shadow"
                    " 对比 + 回滚验证为准"},
        "reason": "用户授权（ABOSV3 T8）：本机默认 standard profile 切换"
                  "为 sku_v4 best；先 shadow、回归、性能与回滚验证，"
                  "classifier/registry/thresholds 与 v5 bundle 同 SHA 零变量",
        "files": [
            {"file": f"{BUNDLE_ID}/detector.pt",
             "source": str(SRC_DETECTOR.relative_to(ROOT)),
             "size": SRC_DETECTOR.stat().st_size, "sha256": det_sha},
            {"file": f"{BUNDLE_ID}/classifier.pt",
             "source": str(SRC_CLASSIFIER.relative_to(ROOT)),
             "size": SRC_CLASSIFIER.stat().st_size, "sha256": clf_sha},
        ],
    }
    for name in ("sku_registry.json", "classifier_classes.json",
                 "thresholds.json"):
        src = REF_BUNDLE / name
        manifest["files"].append(
            {"file": f"{BUNDLE_ID}/{name}",
             "source": str(src.relative_to(ROOT)),
             "size": src.stat().st_size, "sha256": sha(src)})
    if check_only:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    pairs = [(SRC_DETECTOR, OUT / "detector.pt"),
             (SRC_CLASSIFIER, OUT / "classifier.pt")]
    for name in ("sku_registry.json", "classifier_classes.json",
                 "thresholds.json"):
        pairs.append((REF_BUNDLE / name, OUT / name))
    for src, dst in pairs:
        shutil.copy2(src, dst)
        got = sha(dst)
        want = next(f["sha256"] for f in manifest["files"]
                    if f["file"].endswith(dst.name))
        if got != want:
            print(f"[ERROR] 复制后 hash 不一致: {dst.name}")
            return 1
    (OUT / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"[OK] bundle 构建完成: {OUT}")
    print(f"  detector sha256 = {det_sha}")
    print(f"  classifier sha256 = {clf_sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main("--check-only" in sys.argv))
