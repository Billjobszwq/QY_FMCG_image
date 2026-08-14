"""SAM 精修批量执行脚本：数据集粗框 → SAM 紧框 → 新数据集。

口径：
- 源：多个 YOLO 数据集（默认 batch2_v4 ∪ sku_v6，208 类对齐）；
- 前置：--screen 质量筛选证据（反光/倾斜/模糊），仅 accept 且非 duplicate 进入；
- SAM 2.1 Hiera Small（隔离 venv .venv_sam，MPS fail-closed）；
- 粗框为 box prompt + 中心点正提示，类别沿用原框（坐标定位 SKU）；
- SAM 紧框不合法即回退原框（src.training.sam_refine.refine_one）；
- 内容 SHA 去重：同 SHA 只保留首份；--resume 断点续跑；
- 输出为新数据集目录，绝不覆盖源数据集；已存在且非空即拒绝。

用法（AC 电源 + caffeinate）：
  caffeinate -i python3 \
      -m scripts.run_sam_refine --sources .datasets/batch2_v4 \
      --screen .eval/sam_refine/quality_screen_<ts>.json --out .datasets/sam_refined_full_v1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.training.sam_refine import (  # noqa: E402
    parse_yolo_label, refine_one, write_yolo_label,
)

SAM_PYTHON = ROOT / ".venv_sam" / "bin" / "python"
CKPT_MANIFEST = ROOT / ".sam_checkpoints" / "manifest.json"
CHECKPOINTS = {
    "sam2.1_hiera_small": "configs/sam2.1/sam2.1_hiera_s.yaml",
    "sam2.1_hiera_base_plus": "configs/sam2.1/sam2.1_hiera_b+.yaml",
}


def load_checkpoint(model: str) -> tuple[Path, str]:
    man = json.loads(CKPT_MANIFEST.read_text(encoding="utf-8"))
    for e in man["entries"]:
        if e["model"] == model:
            p = Path(e["file"])
            if not p.exists():
                raise SystemExit(f"checkpoint 缺失: {p}")
            return p, e["sha256"]
    raise SystemExit(f"manifest 中无模型: {model}")


def load_screen_allowlist(screen_path: Path) -> set[str] | None:
    """从质量筛选证据提取 accept 文件名集合；无 --screen 返回 None（不筛）。"""
    if screen_path is None:
        return None
    ev = json.loads(screen_path.read_text(encoding="utf-8"))
    return {r["file"] for r in ev["records"] if r["decision"] == "accept"}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def call_worker(request: dict, req_dir: Path, timeout: int) -> dict:
    req_path = req_dir / f"req_{int(time.time()*1000)}.json"
    req_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(
        [str(SAM_PYTHON), "-m", "scripts.sam_refine_worker",
         "--request", str(req_path)],
        cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"SAM worker 失败 exit={proc.returncode}:\n{proc.stderr[-2000:]}")
    resp = json.loads(proc.stdout)
    if not resp.get("ok"):
        raise RuntimeError(f"SAM worker 报告失败: {resp.get('error')}")
    return resp


def collect_files(sources: list[str], allow: set[str] | None,
                  limit: int | None) -> list[tuple[str, str, Path, Path]]:
    """返回 [(source, split, img_path, lbl_path)]，按源顺序、文件名排序。"""
    out = []
    for src in sources:
        src_root = (ROOT / src).resolve()
        if not src_root.exists():
            raise SystemExit(f"源数据集不存在: {src_root}")
        for split in ("train", "val"):
            for p in sorted((src_root / "images" / split).glob("*.jpg")):
                if allow is not None and p.name not in allow:
                    continue
                out.append((src, split, p,
                            src_root / "labels" / split / (p.stem + ".txt")))
    if limit:
        out = out[:limit]
    return out


def refine_all(files, out_root: Path, ckpt: Path, ckpt_sha: str, model: str,
               chunk: int, req_dir: Path, progress: dict,
               lineage_f, prog_path: Path) -> dict:
    stats = {"images": 0, "boxes": 0, "sam_accepted": 0, "fallback_orig": 0,
             "dup_sha_skipped": 0, "screen_rejected": 0, "wall_sec": 0.0}
    t0 = time.time()
    done = progress.get("done", {})
    seen_sha = progress.get("seen_sha", {})

    pending = []
    for src, split, img_path, lbl_path in files:
        key = f"{src}:{split}:{img_path.name}"
        if key in done:
            continue
        sha = sha256_file(img_path)
        if sha in seen_sha:
            stats["dup_sha_skipped"] += 1
            done[key] = "dup"
            continue
        pending.append((src, split, img_path, lbl_path, sha))

    for i in range(0, len(pending), chunk):
        batch = pending[i:i + chunk]
        images, meta = [], {}
        for src, split, img_path, lbl_path, sha in batch:
            im = Image.open(img_path)
            w, h = im.size
            text = lbl_path.read_text(encoding="utf-8") if lbl_path.exists() else ""
            rows = parse_yolo_label(text, width=w, height=h)
            instances = [{
                "instance_id": f"b{bi}",
                "positive": [(r["box_px"][0] + r["box_px"][2]) / 2,
                             (r["box_px"][1] + r["box_px"][3]) / 2],
                "coarse_box": list(r["box_px"]),
            } for bi, r in enumerate(rows)]
            meta[img_path.name] = (src, split, w, h, rows)
            images.append({"image_id": img_path.name,
                           "image_path": str(img_path), "instances": instances})
            stats["boxes"] += len(rows)

        resp = call_worker({
            "model": model, "checkpoint": str(ckpt),
            "config": CHECKPOINTS[model], "checkpoint_sha256": ckpt_sha,
            "images": images,
        }, req_dir, timeout=7200)

        for res in resp["results"]:
            name = res["image_id"]
            src, split, w, h, rows = meta[name]
            sha = next(s for _, _, ip, _, s in batch if ip.name == name)
            out_img = out_root / "images" / split
            out_lbl = out_root / "labels" / split
            out_img.mkdir(parents=True, exist_ok=True)
            out_lbl.mkdir(parents=True, exist_ok=True)
            sam_by_id = {x["instance_id"]: x for x in res["instances"]}
            final_rows, lineage = [], []
            for bi, r in enumerate(rows):
                sam = sam_by_id.get(f"b{bi}")
                sam_box = tuple(sam["sam_box"]) if sam and sam.get("sam_box") else None
                final, source = refine_one(r["box_px"], sam_box, width=w, height=h)
                final_rows.append((r["class_id"], final))
                if source == "sam":
                    stats["sam_accepted"] += 1
                else:
                    stats["fallback_orig"] += 1
                lineage.append({"box_idx": bi, "class_id": r["class_id"],
                                "orig": [round(v, 1) for v in r["box_px"]],
                                "sam": [round(v, 1) for v in sam_box] if sam_box else None,
                                "sam_score": sam.get("sam_score") if sam else None,
                                "decision": source})
            write_yolo_label(out_lbl / (Path(name).stem + ".txt"), final_rows,
                             width=w, height=h)
            shutil.copy2(next(ip for _, _, ip, _, s in batch if ip.name == name),
                         out_img / name)
            seen_sha[sha] = name
            done[f"{src}:{split}:{name}"] = "ok"
            stats["images"] += 1
            lineage_f.write(json.dumps({"image": name, "source": src,
                                        "split": split, "sha256": sha,
                                        "encoder_sec": res["encoder_sec"],
                                        "boxes": lineage},
                                       ensure_ascii=False) + "\n")
            lineage_f.flush()
        # 每 chunk 落盘进度：中断后 --resume 可续跑，避免数小时白跑
        progress["done"] = done
        progress["seen_sha"] = seen_sha
        prog_path.write_text(json.dumps(progress, ensure_ascii=False),
                             encoding="utf-8")
        print(f"[{min(i + chunk, len(pending))}/{len(pending)}] 张完成,"
              f" 累计 accept={stats['sam_accepted']}", flush=True)

    progress["done"] = done
    progress["seen_sha"] = seen_sha
    stats["wall_sec"] = round(time.time() - t0, 1)
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default=".datasets/batch2_v4,.datasets/sku_v6")
    ap.add_argument("--out", default=".datasets/sam_refined_full_v1")
    ap.add_argument("--screen", default=None)
    ap.add_argument("--model", default="sam2.1_hiera_small")
    ap.add_argument("--chunk", type=int, default=16)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--resume", action="store_true",
                    help="允许在非空输出目录上断点续跑（依赖 progress 文件）")
    a = ap.parse_args()

    out_root = (ROOT / a.out).resolve()
    if out_root.exists() and any(out_root.iterdir()) and not a.resume:
        raise SystemExit(f"输出目录已存在且非空，拒绝覆盖: {out_root}")
    ckpt, ckpt_sha = load_checkpoint(a.model)
    allow = load_screen_allowlist(Path(a.screen)) if a.screen else None

    files = collect_files([s.strip() for s in a.sources.split(",")], allow, a.limit)
    req_dir = ROOT / ".sam_runs" / "refine_requests"
    req_dir.mkdir(parents=True, exist_ok=True)
    prog_path = ROOT / ".sam_runs" / "refine_progress.json"
    progress = {}
    if a.resume and prog_path.exists():
        progress = json.loads(prog_path.read_text(encoding="utf-8"))

    ev_dir = ROOT / ".eval" / "sam_refine"
    ev_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    lineage_f = open(ev_dir / f"refine_lineage_{ts}.jsonl", "w", encoding="utf-8")

    t0 = time.time()
    stats = refine_all(files, out_root, ckpt, ckpt_sha, a.model, a.chunk,
                       req_dir, progress, lineage_f, prog_path)
    lineage_f.close()
    prog_path.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")

    # data.yaml：names 沿用 batch2_v4（208 类对齐）；train_v1.validate_dataset
    # 要求 nc 字段且与 names 一致，从源 yaml 一并复制
    src_yaml = (ROOT / ".datasets/batch2_v4/data.yaml").read_text(encoding="utf-8")
    nc_block = src_yaml[src_yaml.index("nc:"):src_yaml.index("names:")]
    names_block = src_yaml[src_yaml.index("names:"):]
    out_root.mkdir(parents=True, exist_ok=True)
    yaml_content = (f"path: {out_root}\ntrain: images/train\nval: images/val\n"
                    + nc_block + names_block)
    (out_root / "data.yaml").write_text(yaml_content, encoding="utf-8")

    ev_path = ev_dir / f"refine_evidence_{ts}.json"
    ev_path.write_text(json.dumps({
        "created_at": datetime.now().isoformat(),
        "model": a.model, "checkpoint_sha256": ckpt_sha,
        "sources": a.sources, "out": str(out_root),
        "screen": a.screen, "limit": a.limit, "chunk": a.chunk,
        "wall_sec_total": round(time.time() - t0, 1),
        "stats": stats,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"stats": stats, "evidence": str(ev_path)},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
