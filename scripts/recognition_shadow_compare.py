#!/usr/bin/env python3
"""UATCC T5：V4 shadow 证据纠偏（prod v5 bundle vs prod_v4_best_r1）。

纠偏（相对旧版 .eval/shadow_v4_best_report.json）：
- 读 sku_name（旧版误读 name → 全 '?'）；输出 sku_id/sku_name/status/
  confidence/margin/box；
- 记录 detector/classifier/registry/threshold 的 sha256；
- 明确区分证据口径：load_smoke / detection_comparison /
  latency_regression / negative_sample；无人工 GT 时不得输出准确率
  结论（本批为 selected-failure smoke，不写"准确率提高"）；
- V4 状态口径：USER_SELECTED_UAT_MODEL（非 PRODUCTION_APPROVED）；
- 延迟 p50/p95；负样本误检测试；
- 新报告写 .eval/shadow_v4_best_report_v2.json；旧报告原文件保留。

不修改任何权重与 CURRENT；不启动训练。
用法：python scripts/recognition_shadow_compare.py [--images N]
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BUNDLES = ROOT / ".models" / "bundles"
PROD = BUNDLES / "prod_20260805_v5_r1"
V4BEST = BUNDLES / "prod_v4_best_r1"
REPORT = ROOT / ".eval" / "shadow_v4_best_report_v2.json"
OLD_REPORT = ROOT / ".eval" / "shadow_v4_best_report.json"

V4_STATUS = "USER_SELECTED_UAT_MODEL"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_products(up) -> list[str]:
    """从识别输出提取 sku_name 列表（契约：读 sku_name，不得 '?'）。

    兼容两种形态：list[dict] 与 {"count","products":[...]}。"""
    if isinstance(up, dict):
        items = up.get("products") or []
    else:
        items = list(up or [])
    return [str(r.get("sku_name") or "?") for r in items]


def detail_products(up) -> list[dict]:
    """完整字段契约：sku_id/sku_name/status/confidence/margin/box。"""
    if isinstance(up, dict):
        items = up.get("products") or []
    else:
        items = list(up or [])
    out = []
    for r in items:
        out.append({"sku_id": r.get("sku_id", ""),
                    "sku_name": r.get("sku_name", ""),
                    "status": r.get("status", ""),
                    "confidence": r.get("classifier_conf",
                                        r.get("confidence")),
                    "margin": r.get("margin"),
                    "box": r.get("box")})
    return out


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


def make_negative_sample() -> Path:
    """负样本：纯色图（无商品）——期望 0 accepted 检出。"""
    out = ROOT / ".eval" / "v3_uat_v2" / "negative_blank.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        try:
            from PIL import Image
            Image.new("RGB", (640, 480), (210, 210, 210)).save(out)
        except Exception:
            out.write_bytes(b"")  # 无 Pillow 时跳过负样本
    return out


def bundle_hashes(bundle_dir: Path) -> dict:
    hh = {}
    for name in ("detector.pt", "classifier.pt", "sku_registry.json",
                 "thresholds.json", "MANIFEST.json"):
        p = bundle_dir / name
        hh[name] = sha256_file(p)[:16] + "…" if p.exists() else "missing"
    return hh


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
                "products": extract_products(out)[:8],
                "detail": detail_products(out)[:8]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200],
                "elapsed_ms": round((time.time() - t0) * 1000, 1)}


def percentile(ms: list[float], pct: float) -> float | None:
    if not ms:
        return None
    s = sorted(ms)
    k = min(len(s) - 1, max(0, int(round(pct / 100 * (len(s) - 1)))))
    return round(s[k], 1)


def current_bundle_id() -> str:
    try:
        cur = json.loads((BUNDLES / "CURRENT.json").read_text(
            encoding="utf-8"))
        return cur.get("bundle_id", "")
    except Exception:
        return ""


def main() -> int:
    limit = 6
    if "--images" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--images") + 1])
    imgs = collect_images(limit)
    if not imgs:
        print("[ERROR] 无样本图片")
        return 1
    neg = make_negative_sample()
    print(f"样本数：{len(imgs)}（+1 负样本）")
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
                     "evidence_kind": "detection_comparison",
                     "prod": rp, "v4_best": rv,
                     "same_count": rp.get("count") == rv.get("count"),
                     "same_products": rp.get("products")
                     == rv.get("products")})
        print(f"  {img.name}: prod={rp.get('count')} "
              f"({rp['elapsed_ms']}ms) vs v4={rv.get('count')} "
              f"({rv['elapsed_ms']}ms)")
    # 负样本：期望 accepted 检出为 0（误检测试，只读）
    neg_row = {"image": str(neg.relative_to(ROOT)),
               "evidence_kind": "negative_sample",
               "prod": run(rec_p, neg), "v4_best": run(rec_v, neg)}
    rows.append(neg_row)
    for key in agg:
        ms = agg[key].pop("ms")
        agg[key]["p50_ms"] = percentile(ms, 50)
        agg[key]["p95_ms"] = percentile(ms, 95)
        agg[key]["mean_ms"] = round(sum(ms) / len(ms), 1) if ms else None
    cur = current_bundle_id()
    report = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "bundles": {"prod": pid_p, "v4_best": pid_v},
        "hashes": {"prod": bundle_hashes(PROD),
                   "v4_best": bundle_hashes(V4BEST)},
        "current_bundle": cur,
        "current_bundle_restored": cur == "prod_v4_best_r1",
        "v4_status": V4_STATUS,
        "load_smoke": {"prod_seconds": load_p,
                       "v4_best_seconds": load_v,
                       "ok": load_p > 0 and load_v > 0},
        "latency_regression": agg,
        "images": len(imgs), "rows": rows,
        "negative_sample": {
            "prod_accepted": sum(1 for p in (neg_row["prod"].get("detail")
                                             or [])
                                 if p["status"] == "accepted"),
            "v4_accepted": sum(1 for p in (neg_row["v4_best"].get("detail")
                                           or [])
                               if p["status"] == "accepted")},
        "honesty": [
            "本批为 selected-failure smoke（bad_samples 失败图），"
            "不是独立人工真值集",
            "无人工 GT：不输出准确率结论（不写'准确率提高/无错误'）",
            "V4 状态为 USER_SELECTED_UAT_MODEL，非 PRODUCTION_APPROVED",
            "旧报告 .eval/shadow_v4_best_report.json 因误读 name 键"
            "导致 sku 全 '?'，仅检出数量可用；本 v2 报告读 sku_name",
        ],
        "note": "shadow 仅对比，不修改 CURRENT；切换与回滚经平台 API"
                " 审计执行"}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"[OK] 报告已写入 {REPORT}（旧报告保留未动："
          f"{OLD_REPORT.exists()}）")
    print(json.dumps({"latency_regression": agg,
                      "load_smoke": report["load_smoke"],
                      "v4_status": V4_STATUS}, ensure_ascii=False,
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
