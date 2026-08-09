"""状态收口 T6：canonical38_train_val_test_v2（70/15/15 grouped）。

group = 来源照片描述（source+store+scene+session+burst）。
零交叉：group / exact SHA / symlink target 三重校验。
test 冻结：manifest hash + builder hash；不复制不增强补 test。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MAPPING = ROOT / "reports/nextgen_v2/cropped_sku_mapping.json"
GROUP_RE = re.compile(r"^[0-9a-f]{8}__(.+?)_29_")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(
        ROOT / ".datasets_nextgen/canonical38_train_val_test_v2"))
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        print("exists refuse")
        return 1

    mp = json.loads(MAPPING.read_text(encoding="utf-8"))
    rng = random.Random(a.seed)
    groups: dict[str, list] = defaultdict(list)
    sha_of: dict[str, str] = {}
    for d, e in mp["entries"].items():
        if e["kind"] != "mapped":
            continue
        for f in sorted((ROOT / "cropped_images" / d).glob("*.jpg")):
            m = GROUP_RE.match(f.name)
            g = m.group(1) if m else f"nosrc:{f.name}"
            groups[g].append((d, e["class_id"], f))
            sha_of[str(f)] = hashlib.sha256(f.read_bytes()).hexdigest()

    # union-find：共享 exact SHA 的组合并（同内容必同 split）
    sha_groups: dict[str, str] = {}
    parent = {g: g for g in groups}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for g, items in groups.items():
        for _, _, f in items:
            sh = sha_of[str(f)]
            if sh in sha_groups:
                a, b = find(g), find(sha_groups[sh])
                if a != b:
                    parent[a] = b
            else:
                sha_groups[sh] = g
    merged: dict[str, list] = defaultdict(list)
    for g in groups:
        merged[find(g)].extend(groups[g])
    groups = dict(merged)
    gkeys = sorted(groups)
    rng.shuffle(gkeys)
    n_test = max(1, int(len(gkeys) * 0.15))
    n_val = max(1, int(len(gkeys) * 0.15))
    test_g, val_g = set(gkeys[len(gkeys) - n_test:]), \
        set(gkeys[len(gkeys) - n_test - n_val:len(gkeys) - n_test])

    split_of = {}
    for g in gkeys:
        split_of[g] = ("test" if g in test_g else
                       "val" if g in val_g else "train")

    # symlink + 零交叉校验
    seen_sha: dict[str, str] = {}
    seen_target: dict[str, str] = {}
    per_class_test: dict[str, int] = defaultdict(int)
    counts = {"train": 0, "val": 0, "test": 0}
    for g in gkeys:
        sp = split_of[g]
        for d, cid, f in groups[g]:
            dst = out / sp / cid
            dst.mkdir(parents=True, exist_ok=True)
            link = dst / f.name
            if not link.exists():
                link.symlink_to(f)
            sh = sha_of[str(f)]
            if sh in seen_sha and seen_sha[sh] != sp:
                raise SystemExit(f"SHA 跨 split: {sh[:8]}")
            seen_sha[sh] = sp
            tg = str(f.resolve())
            if tg in seen_target and seen_target[tg] != sp:
                raise SystemExit(f"symlink target 跨 split: {tg}")
            seen_target[tg] = sp
            counts[sp] += 1
            if sp == "test":
                per_class_test[cid] += 1

    manifest = {"schema_version": "canonical38-tvt-v2",
                "split_policy": "grouped(source+store+scene+session+burst)",
                "ratios": {"train": 0.7, "val": 0.15, "test": 0.15},
                "counts": counts, "n_groups": len(gkeys),
                "per_class_test": dict(per_class_test),
                "zero_cross": ["group", "exact_sha", "symlink_target"],
                "builder_hash": hashlib.sha256(
                    Path(__file__).read_bytes()).hexdigest()[:16]}
    manifest["manifest_hash"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    audit = {"groups": len(gkeys), "counts": counts,
             "classes_with_test": len(per_class_test),
             "min_test_per_class": min(per_class_test.values())
             if per_class_test else 0}
    (out / "split_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
