#!/usr/bin/env python3
"""ABOSV3 T8：shadow 对比（prod v5 bundle vs prod_v4_best_r1）。

同一批样本分别经两个 bundle 真实推理（MPS），比较输出/延迟/错误；
报告写入 .eval/shadow_v4_best_report.json。不修改任何权重与 CURRENT。

用法：python scripts/recognition_shadow_compare.py [--images N]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BUNDLES = ROOT / ".models" / "bundles"
PROD = BUNDLES / "prod_20260805_v5_r1"
V4BEST = BUNDLES / "prod_v4_best_r1"
REPORT = ROOT / ".eval" / "shadow_v4_best_report.json"


def collect_images(limit: int) -> list[Path]:
    imgs: list[Path] = []
    bad = ROOT / "bad_samples"
    if bad.exists():
        imgs += sorted(p for p in bad.iterdir()
                       if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    for sub in sorted((ROOT / ".field" / "blobs").iterdir())[:3]:
        if sub.is_dir():
            imgs += sorted(p for p in sub.iterdir()
                           if p.suffix.lower() in (".jpg", ".jpeg",
                                                   ".png"))[:1]
    return imgs[:limit]


def load_recognizer(bundle_dir: Path):
    from src.cascade.cascade_inference import CascadeRecognizer
    manifest = json.loads((bundle_dir / "MANIFEST.json").read_text(
        encoding="utf-8"))
    registry = json.loads((bundle_dir / "sku_registry.json").read_text(
        encoding="utf-8"))
    thresholds = json.loads((bundle_dir / "thresholds.json").read_text(
        encoding="utf-8"))
    kwargs = {}
    if isinstance(thresholds.get("conf"), (int, float)):
        kwargs["conf_thr"] = float(thresholds["conf"])
    if isinstance(thresholds.get("margin"), (int, float)):
        kwargs["margin_thr"] = float(thresholds["margin"])
    t0 = time.time()
    rec = CascadeRecognizer(
        yolo_weight=str(bundle_dir / "detector.pt"),
        clf_weight=str(bundle_dir / "classifier.pt"),
        registry=registry, **kwargs)
    return rec, manifest["bundle_id"], round(time.time() - t0, 2)


def run(rec, img: Path) -> dict:
    data = img.read_bytes()
    t0 = time.time()
    try:
        out = rec.recognize(data, conf=getattr(rec, "conf_thr", 0.25))
        return {"ok": True,
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
                "count": len(out),
                "products": sorted(r.get("name", "?") for r in out)[:8]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200],
                "elapsed_ms": round((time.time() - t0) * 1000, 1)}


def main() -> int:
    limit = 6
    if "--images" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--images") + 1])
    imgs = collect_images(limit)
    if not imgs:
        print("[ERROR] 无样本图片")
        return 1
    print(f"样本数：{len(imgs)}")
    print("加载 production bundle …")
    rec_p, pid_p, load_p = load_recognizer(PROD)
    print("加载 v4_best bundle …")
    rec_v, pid_v, load_v = load_recognizer(V4BEST)
    rows = []
    agg = {"prod": {"ok": 0, "errors": 0, "ms": []},
           "v4_best": {"ok": 0, "errors": 0, "ms": []}}
    for img in imgs:
        rp = run(rec_p, img)
        rv = run(rec_v, img)
        for key, r in (("prod", rp), ("v4_best", rv)):
            if r["ok"]:
                agg[key]["ok"] += 1
                agg[key]["ms"].append(r["elapsed_ms"])
            else:
                agg[key]["errors"] += 1
        rows.append({"image": str(img.relative_to(ROOT)),
                     "prod": rp, "v4_best": rv,
                     "same_count": rp.get("count") == rv.get("count"),
                     "same_products": rp.get("products")
                     == rv.get("products")})
        print(f"  {img.name}: prod={rp.get('count')} "
              f"({rp['elapsed_ms']}ms) vs v4={rv.get('count')} "
              f"({rv['elapsed_ms']}ms)")
    for key in agg:
        ms = agg[key].pop("ms")
        agg[key]["p50_ms"] = round(sorted(ms)[len(ms) // 2], 1) if ms \
            else None
        agg[key]["mean_ms"] = round(sum(ms) / len(ms), 1) if ms else None
    report = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "bundles": {"prod": pid_p, "v4_best": pid_v},
              "load_seconds": {"prod": load_p, "v4_best": load_v},
              "images": len(imgs), "aggregate": agg, "rows": rows,
              "note": "shadow 仅对比，不修改 CURRENT；切换与回滚经"
                      " 平台 API 审计执行"}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"[OK] 报告已写入 {REPORT}")
    print(json.dumps({"aggregate": agg, "load_seconds":
                      report["load_seconds"]}, ensure_ascii=False,
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
