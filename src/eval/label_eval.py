"""标注质量评测（不用 YOLO）：Mode B 自动提案 vs 它模金标。

Mode B 的框由种子点外扩而来，故"覆盖"近 100%（构造所致）；真正有意义的是：
- label_accuracy_on_covered：自动 SKU 与金标一致率；
- disagree_bigmodel_vs_itmod：大模型与它模不一致数（=人工复核队列 + 它模错标挖掘）。
用法：python -m src.eval.label_eval [--max-photos N]"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.catalog.alias_registry import build_registry
from src.common import paths
from src.common.config import PROJECT_ROOT

REF = PROJECT_ROOT / "搭建初期P1"
FIELD = PROJECT_ROOT / ".field"
LABEL = PROJECT_ROOT / ".labels"


def _in(pt, box):
    x, y = pt
    x1, y1, x2, y2 = box
    return x1 <= x <= x2 and y1 <= y <= y2


def evaluate(max_photos=None):
    m = json.load(open(FIELD / "manifest.json", encoding="utf-8"))
    reg = build_registry(sorted(p.name for p in REF.iterdir() if p.is_dir()), PROJECT_ROOT / "data" / "sku_aliases.json")
    tot_gold = tot_covered = tot_correct = tot_disagree = tot_extra = 0
    disagree = []
    photos = m["photos"] if max_photos is None else m["photos"][:max_photos]
    done = 0
    for p in photos:
        pid = p["id"]
        sp = LABEL / "proposals" / f"{pid}.json"
        if not sp.exists():
            continue
        done += 1
        props = json.load(open(sp, encoding="utf-8"))
        for an in p["annotations"]:
            gold = an.get("canonical")
            pt = (an["x"], an["y"])
            tot_gold += 1
            cov = [pr for pr in props if _in(pt, pr["box"])]
            if cov:
                tot_covered += 1
                dec = cov[0]["decision"]
                if dec == gold:
                    tot_correct += 1
                elif dec in reg.canonicals:
                    tot_disagree += 1
                    disagree.append({"asset": pid, "gold": gold, "auto": dec, "seed": an.get("name")})
        for pr in props:
            if not any(_in((a["x"], a["y"]), pr["box"]) for a in p["annotations"]):
                tot_extra += 1
    rep = {
        "photos": done, "gold": tot_gold, "covered": tot_covered, "label_correct": tot_correct,
        "disagree_bigmodel_vs_itmod": tot_disagree, "extra_boxes": tot_extra,
        "coverage": round(tot_covered / tot_gold, 4) if tot_gold else 0.0,
        "label_accuracy_on_covered": round(tot_correct / tot_covered, 4) if tot_covered else 0.0,
        "disagree_cases": disagree[:50],
    }
    paths.safe_write_text(LABEL / "label_eval.json", json.dumps(rep, ensure_ascii=False, indent=2))
    print("LABEL_EVAL", json.dumps({k: rep[k] for k in ["photos", "gold", "covered", "label_correct", "disagree_bigmodel_vs_itmod", "coverage", "label_accuracy_on_covered"]}, ensure_ascii=False))
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-photos", type=int, default=None)
    evaluate(ap.parse_args().max_photos)
