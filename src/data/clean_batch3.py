"""阶段一执行：第三批训练数据清洗（图像质量拦截器分流）。

流程：
  1. 解析 第三批训练数据.xlsx → 照片 (id, filename, url)
  2. 并发下载（断点续传，跳过已处理）
  3. 每张过 QualityGate：
       通过(好图) → 存内容寻址 blob + 记入 batch3_clean manifest（可进 Label Studio/训练）
       未通过(坏图) → 隔离到 bad_samples/<id>_<reason>.jpg，绝不进训练集
  4. 生成拦截报告：总数/坏图数/分布(模糊/反光/翻拍)

用法：python -m src.data.clean_batch3 [--workers 12] [--limit N] [--resume]"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures
import json
import time
from pathlib import Path

import cv2
import httpx
import numpy as np
import openpyxl

from ..common import hashing
from ..common.config import PROJECT_ROOT
from ..common.oss_urls import oss_url
from .quality_gate import QualityGate

XLSX = PROJECT_ROOT / "第三批训练数据.xlsx"
OUT_DIR = PROJECT_ROOT / ".batch3_clean"
CLEAN_BLOBS = OUT_DIR / "blobs"
BAD_DIR = PROJECT_ROOT / "bad_samples"
GATE = QualityGate()
REASON_SUFFIX = {"blurry": "_blurry", "reflection": "_reflection", "screen": "_screen"}


def parse_photos() -> dict:
    wb = openpyxl.load_workbook(str(XLSX), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(c).strip() if c else "" for c in rows[0]]
    idx = {n: i for i, n in enumerate(header)}
    wb.close()

    def g(r, k):
        return r[idx[k]] if k in idx and idx[k] < len(r) else None

    photos = collections.OrderedDict()
    for r in rows[1:]:
        pid = g(r, "ID")
        if pid is None:
            continue
        pid = str(int(pid)) if isinstance(pid, float) else str(pid)
        if pid not in photos:
            photos[pid] = {"id": pid, "filename": g(r, "TypeValue"), "url": g(r, "URL")}
    return photos


def gate_one(pid, filename):
    """下载单张并过分流。返回 (pid, result_dict)。"""
    url = oss_url(filename)
    try:
        with httpx.Client(follow_redirects=True, timeout=60.0, headers={"User-Agent": "Mozilla/5.0"}) as c:
            r = c.get(url)
            if r.status_code != 200 or not r.content:
                return pid, {"status": "download_fail", "code": r.status_code}
            data = r.content
    except Exception as e:
        return pid, {"status": "download_fail", "err": str(e)}

    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return pid, {"status": "decode_fail"}

    verdict = GATE.check(img)
    h = hashing.sha256_bytes(data)
    if verdict["pass"]:
        bp = CLEAN_BLOBS / h[:2] / h
        if not bp.exists():
            bp.parent.mkdir(parents=True, exist_ok=True)
            bp.write_bytes(data)
        return pid, {"status": "clean", "sha256": h, "height": img.shape[0], "width": img.shape[1],
                     "filename": filename, "metrics": verdict["metrics"]}
    else:
        primary = verdict["reasons"][0]
        suffix = REASON_SUFFIX.get(primary, "_bad")
        BAD_DIR.mkdir(parents=True, exist_ok=True)
        bad_path = BAD_DIR / f"{pid}{suffix}.jpg"
        if not bad_path.exists():
            cv2.imwrite(str(bad_path), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return pid, {"status": "bad", "reasons": verdict["reasons"], "filename": filename,
                     "metrics": verdict["metrics"]}


def run(workers: int = 12, limit: int | None = None):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    photos = parse_photos()
    keys = list(photos.keys())
    if limit:
        keys = keys[:limit]
    print(f"[清洗] 第三批照片: {len(keys)} 张")

    # 断点续传：加载已有结果
    prog_file = OUT_DIR / "gate_results.json"
    results = {}
    if prog_file.exists():
        try:
            results = json.loads(prog_file.read_text(encoding="utf-8"))
        except Exception:
            results = {}
    todo = [k for k in keys if k not in results]
    print(f"[清洗] 已处理 {len(results)}, 待处理 {len(todo)}")

    t0 = time.time()
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(gate_one, pid, photos[pid]["filename"]): pid for pid in todo}
        for fut in concurrent.futures.as_completed(futs):
            pid, res = fut.result()
            results[pid] = res
            done += 1
            if done % 300 == 0 or done == len(todo):
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed else 0
                eta = (len(todo) - done) / rate if rate else 0
                print(f"  {done}/{len(todo)} | {rate:.1f}/s | ETA {eta/60:.1f}min", flush=True)
                prog_file.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")

    prog_file.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")

    # 汇总报告
    clean = [p for p, r in results.items() if r.get("status") == "clean"]
    bad = {p: r for p, r in results.items() if r.get("status") == "bad"}
    dl_fail = [p for p, r in results.items() if "fail" in r.get("status", "")]
    reason_cnt = collections.Counter()
    for r in bad.values():
        for reason in r["reasons"]:
            reason_cnt[reason] += 1
    total = len(results)
    report = {
        "total": total,
        "clean": len(clean), "bad": len(bad), "download_fail": len(dl_fail),
        "bad_rate": round(len(bad) / total, 4) if total else 0,
        "reason_distribution": {
            "blurry": reason_cnt.get("blurry", 0),
            "reflection": reason_cnt.get("reflection", 0),
            "screen": reason_cnt.get("screen", 0),
        },
        "reason_pct_of_bad": {k: round(v / len(bad), 3) if bad else 0 for k, v in reason_cnt.items()},
    }
    (OUT_DIR / "intercept_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # 好图 manifest（供 Label Studio / 训练）
    clean_manifest = {p: results[p] for p in clean}
    (OUT_DIR / "clean_manifest.json").write_text(json.dumps(clean_manifest, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 56)
    print("第三批数据拦截报告")
    print("=" * 56)
    print(f"  原始图片总数: {total}")
    print(f"  好图(通过): {len(clean)} ({len(clean)/total*100:.1f}%)")
    print(f"  坏图(拦截): {len(bad)} ({len(bad)/total*100:.1f}%)")
    print(f"  下载失败: {len(dl_fail)}")
    rd = report["reason_distribution"]
    print(f"  坏图分布: 模糊 {rd['blurry']} | 反光 {rd['reflection']} | 翻拍 {rd['screen']}")
    print(f"  报告: {OUT_DIR/'intercept_report.json'}")
    print(f"  坏图隔离: {BAD_DIR}/")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    run(a.workers, a.limit)
