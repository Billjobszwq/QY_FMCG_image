"""SLTF P0-3：grouped split 版 classifier 数据集（leakage_group_id）。

leakage_group = 裁剪文件名中 `__` 与 `_29_` 之间的来源照片描述
（源照片 hash + 门店 + 场景 + 时间戳 + 连拍组）。同一 group 必同 split。
无法解析来源的文件名 → fail-closed：仅训练，不进 val。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MAPPING = ROOT / "reports/nextgen_v2/cropped_sku_mapping.json"
GROUP_RE = re.compile(r"^[0-9a-f]{8}__(.+?)_29_")


def leakage_group(filename: str) -> str | None:
    m = GROUP_RE.match(filename)
    return m.group(1) if m else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".datasets_nextgen"
                                         / "d3_cropped_classifier_v2_grouped"))
    ap.add_argument("--val-ratio", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--scope", choices=["all", "canonical38"],
                        default="all")
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        print(f"目录已存在，拒绝覆盖: {out}")
        return 1

    mp = json.loads(MAPPING.read_text(encoding="utf-8"))
    rng = random.Random(a.seed)

    # group -> files
    groups: dict[str, list] = {}
    no_source: list = []
    for d, e in mp["entries"].items():
        if a.scope == "canonical38" and e["kind"] != "mapped":
            continue
        src = ROOT / "cropped_images" / d
        for f in sorted(src.iterdir()):
            if f.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                continue
            g = leakage_group(f.name)
            if g is None:
                no_source.append((d, e, f))
            else:
                groups.setdefault(g, []).append((d, e, f))

    gkeys = sorted(groups)
    rng.shuffle(gkeys)
    n_val = max(1, int(len(gkeys) * a.val_ratio))
    val_groups = set(gkeys[len(gkeys) - n_val:])

    manifest = {"schema_version": "classifier-snapshot.v2-cropped-grouped",
                "split_policy": "leakage_group（source photo+store+scene+"
                                "session+burst）同组同 split",
                "label_source": "user_provided_cropped",
                "classes": {}, "n_images": 0, "split_report": {},
                "n_leakage_groups": len(gkeys),
                "n_no_source_train_only": len(no_source)}
    for g in gkeys:
        split = "val" if g in val_groups else "train"
        for d, e, f in groups[g]:
            dst_dir = out / split / e["class_id"]
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / f.name
            if not dst.exists():
                dst.symlink_to(f)
            manifest["classes"].setdefault(e["class_id"], {
                "display": e["display"], "kind": e["kind"],
                "train": 0, "val": 0})
            manifest["classes"][e["class_id"]][split] += 1
            manifest["n_images"] += 1
            manifest["split_report"][split] = \
                manifest["split_report"].get(split, 0) + 1
    # 无来源：仅训练（fail-closed 出验证集）
    for d, e, f in no_source:
        dst_dir = out / "train" / e["class_id"]
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / f.name
        if not dst.exists():
            dst.symlink_to(f)
        manifest["n_images"] += 1
        manifest["split_report"]["train"] = \
            manifest["split_report"].get("train", 0) + 1
    manifest["n_classes"] = len(manifest["classes"])
    manifest["manifest_hash"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True,
                   ensure_ascii=False).encode()).hexdigest()
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps({"groups": len(gkeys), "val_groups": len(val_groups),
                      "images": manifest["n_images"],
                      "split": manifest["split_report"],
                      "no_source_train_only": len(no_source),
                      "hash": manifest["manifest_hash"][:16]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
