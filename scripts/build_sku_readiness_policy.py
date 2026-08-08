"""SLTF §5：sku_data_readiness_policy_v1（83 类长尾分层）。

每类统计：raw crops / unique source photos(leakage groups) / unique stores /
unique sessions / scenes / package-registry 状态。Tier 以有效独立组数为主：
A≥300 / B100-299 / C30-99 / D<30 或身份未裁决。
输出建议：加强/保留观察/专家头/合并候选/舍弃候选 + 最差十类 + 采集优先级。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MAPPING = ROOT / "reports/nextgen_v2/cropped_sku_mapping.json"
GROUP_RE = re.compile(r"^[0-9a-f]{8}__(.+?)_29_")
# 文件名结构: crop__<src>-<item>_<store>_<scene>_<ts>_hc..._29_<sku>_i.jpg_...
PART_RE = re.compile(r"^[0-9a-f]{8}__(?P<src>[0-9a-f]{8})-(?P<rest>.+?)_29_")


def parse_meta(filename: str) -> dict:
    m = PART_RE.match(filename)
    if not m:
        return {}
    rest = m.group("rest")
    parts = rest.split("_")
    # rest = <item>_<store>_<scene>_<ts>_hc<id> 近似：store=parts[1]
    store = parts[1] if len(parts) > 1 else ""
    scene = parts[2] if len(parts) > 2 else ""
    ts = parts[3] if len(parts) > 3 else ""
    session = f"{store}@{ts[:8] if ts else ''}"
    return {"group": m.group("src") + "|" + rest, "store": store,
            "scene": scene, "session": session}


def main() -> int:
    mp = json.loads(MAPPING.read_text(encoding="utf-8"))
    stats = {}
    for d, e in mp["entries"].items():
        src = ROOT / "cropped_images" / d
        files = [f.name for f in src.iterdir()
                 if f.suffix.lower() in (".jpg", ".jpeg", ".png")]
        metas = [parse_meta(f) for f in files]
        groups = {m["group"] for m in metas if m}
        stores = {m["store"] for m in metas if m}
        sessions = {m["session"] for m in metas if m}
        scenes = {m["scene"] for m in metas if m}
        n_groups = len(groups) or 1
        tier = ("A" if n_groups >= 300 else "B" if n_groups >= 100
                else "C" if n_groups >= 30 else "D")
        if e["kind"] != "mapped":
            tier = "D"  # 身份未裁决
        stats[e["class_id"]] = {
            "display": e["display"], "kind": e["kind"],
            "registry_name": e["registry_name"],
            "raw_crops": len(files), "unique_source_groups": n_groups,
            "unique_stores": len(stores), "unique_sessions": len(sessions),
            "scenes": sorted(scenes), "tier": tier}
    tiers = defaultdict(list)
    for cid, s in stats.items():
        tiers[s["tier"]].append(cid)
    # 建议
    for cid, s in stats.items():
        if s["tier"] == "A":
            s["advice"] = "闭集分类+上限采样+hard negative 挖掘"
        elif s["tier"] == "B":
            s["advice"] = "过采样+增强+混淆矩阵补 hard negative；建议补数到 A"
        elif s["tier"] == "C":
            s["advice"] = "metric/prototype/retrieval 优先；禁高置信自动接受"
        else:
            s["advice"] = ("新包装/未知工作流；few-shot prototype；"
                           "需业务决定补数/合并/保留/舍弃"
                           if s["kind"] != "mapped"
                           else "补数优先；暂不承诺闭集自动识别")
    worst = sorted(stats.items(),
                   key=lambda kv: kv[1]["unique_source_groups"])[:10]
    rep = {"policy_version": "sku_data_readiness_policy_v1",
           "n_classes": len(stats),
           "tier_counts": {t: len(v) for t, v in sorted(tiers.items())},
           "classes": stats,
           "worst_ten": [{"class_id": c, **s} for c, s in worst],
           "head_tail_gap": max(s["unique_source_groups"]
                                for s in stats.values())
           - min(s["unique_source_groups"] for s in stats.values()),
           "collection_priority": [c for c, s in worst
                                   if s["kind"] == "mapped"]}
    rep["policy_hash"] = hashlib.sha256(
        json.dumps(stats, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    out = ROOT / "reports/nextgen_v2/sku_data_readiness_policy_v1.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(json.dumps({"tiers": rep["tier_counts"],
                      "head_tail_gap": rep["head_tail_gap"],
                      "worst": [w["display"] for w in rep["worst_ten"]][:5]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
