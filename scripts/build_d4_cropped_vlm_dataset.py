"""用户切分照片 → VLM 闭集裁决训练数据（mlx-vlm messages 格式）。

每条：crop 图 + 8 候选 SKU（真实检索占位：同类 + 同品牌随机）→ 编号答案。
mapped 类候选含 canonical 名；new 类候选含其 display 名（答案不猜，
候选列表必含正确项，保证闭集可学）。分层采样限量。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MAPPING = ROOT / "reports/nextgen_v2/cropped_sku_mapping.json"
REG = ROOT / "data/sku_registry.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".datasets_nextgen"
                                         / "d4_cropped_vlm_v1"))
    ap.add_argument("--n", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        print(f"目录已存在，拒绝覆盖: {out}")
        return 1
    out.mkdir(parents=True)
    (out / "images").mkdir()

    mp = json.loads(MAPPING.read_text(encoding="utf-8"))
    reg = json.loads(REG.read_text(encoding="utf-8"))
    rng = random.Random(a.seed)

    # 候选池：registry 全部 display 名 + new 类 display 名
    reg_names = list(reg.keys())
    new_displays = [e["display"] for e in mp["entries"].values()
                    if e["kind"] != "mapped"]

    records = []
    per_class_cap = max(20, a.n // len(mp["entries"]))
    counts: dict = {}
    for d, e in mp["entries"].items():
        if counts.get(e["class_id"], 0) >= per_class_cap:
            continue
        src = ROOT / "cropped_images" / d
        files = sorted(p for p in src.iterdir()
                       if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
        take = files[:per_class_cap]
        for f in take:
            # 候选：正确项 + 7 个干扰（同品牌前缀优先，其余随机）
            pool = [n for n in reg_names if n != e["display"]]
            rng.shuffle(pool)
            distractors = pool[:7]
            cands = [e["display"]] + distractors
            rng.shuffle(cands)
            ans = cands.index(e["display"]) + 1
            fname = f"{e['class_id']}__{f.name}"
            # symlink 到 out/images
            dst = out / "images" / fname
            if not dst.exists():
                dst.symlink_to(f)
            cand_txt = "\n".join(f"{i+1}. {c}" for i, c in enumerate(cands))
            records.append({
                "messages": [
                    {"role": "user", "content": [
                        {"type": "image", "image": f"images/{fname}"},
                        {"type": "text",
                         "text": "这是货架商品切图。候选 SKU：\n" + cand_txt
                                 + "\n请只回答最匹配的编号。"}]},
                    {"role": "assistant", "content": [
                        {"type": "text", "text": str(ans)}]}],
                "images": [f"images/{fname}"],
                "meta": {"class_id": e["class_id"],
                         "kind": e["kind"],
                         "target_display": e["display"]}})
            counts[e["class_id"]] = counts.get(e["class_id"], 0) + 1
        if len(records) >= a.n:
            break
    rng.shuffle(records)
    (out / "train.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records),
        encoding="utf-8")
    manifest = {"schema_version": "vlm-snapshot.v2-cropped",
                "format": "mlx_vlm.lora jsonl(images/messages)",
                "n_samples": len(records),
                "label_source": "user_provided_cropped",
                "manifest_hash": hashlib.sha256(
                    json.dumps([r["meta"] for r in records],
                               sort_keys=True,
                               ensure_ascii=False).encode()).hexdigest()}
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps({"samples": len(records),
                      "hash": manifest["manifest_hash"][:16]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
