"""状态收口 T8：M1/M2 数据缺口统计（不训练，只统计）。"""
import json
from collections import Counter
from pathlib import Path

lab = Path(".datasets_nextgen/detector_snapshot_v3/labels")
sizes, density = [], Counter()
for f in sorted(lab.glob("train/*.txt")):
    lines = [l.split() for l in f.read_text().splitlines() if l.strip()]
    density[len(lines)] += 1
    for l in lines:
        w, h = float(l[3]), float(l[4])
        sizes.append("small" if w * h < 0.005 else
                     "mid" if w * h < 0.02 else "large")
n_imgs = len(list(lab.glob("train/*.txt"))) + \
    len(list(lab.glob("val/*.txt")))
gap = {"n_scene_images": n_imgs, "n_regions": sum(density.values()),
       "size_dist": dict(Counter(sizes)),
       "density_dist": {
           "1-5": sum(v for k, v in density.items() if k <= 5),
           "6-10": sum(v for k, v in density.items() if 6 <= k <= 10),
           ">10": sum(v for k, v in density.items() if k > 10)},
       "gap_analysis": {
           "small_targets_pct": round(
               100 * Counter(sizes)["small"] / max(len(sizes), 1), 1),
           "need_more_scene_images": "≥3,000 张全场景（当前 894）",
           "need_types": ["冰柜密集小目标", "反光/遮挡货架", "多角度拍摄",
                          "低光照", "截断目标"],
           "collection_priority": ["冰柜场景（小目标密集）",
                                   "反光包装货架", "遮挡/截断",
                                   "新门店分布"]},
       "m1_m2_status": "PILOT_NOT_CANDIDATE（不强行标 candidate）"}
Path("reports/nextgen_v2/m1_m2_data_gap.json").write_text(
    json.dumps(gap, ensure_ascii=False, indent=1))
print(json.dumps(gap["size_dist"], ensure_ascii=False), n_imgs)
