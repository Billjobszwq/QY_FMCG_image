"""安全数据集构建器 v7（G2/G3 门禁实现）。

与旧 build_sku_v6_dataset 的本质区别：
  1. 抽样**前**排除全部 active protocol 的五键（photo ID / SHA /
     规范化门店 / 模糊别名 / 采集 session），抽样后再过一次
     fail-closed 复核（protocol_guard.check_no_leak）。
  2. 写入唯一 staging 目录 → 完整校验 → 原子发布（os.rename），
     发布目录已存在即拒绝；绝不复用 `.datasets/sku_v6`。
  3. build_audit.json 记录 Git commit、构建器哈希、完整参数、seed、
     环境、五键守卫报告、split manifest（逐文件 SHA256）与数据集哈希。
  4. 校验：图片/标签一一对应、label class 范围、空 val、损坏图片、
     train/val 门店与 session 零交集。

当前模式：
  product —— 单类商品检测器数据：注册与未注册商品统一标为
             class 0 "product"（E2 pilot / class-agnostic detector）。

用法：
  python -m src.training.build_dataset_v7 --name e2_product_pilot_v1 \
      --mode product --train-photos 2000 --val-photos 300 --seed 42 [--dry-run]
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT
from ..data import protocol_guard
from ..data.store_norm import norm_store, session_of_filename, store_of_filename
from ..training.build_sku_v6_dataset import parse_batch3_annotations
from ..training.ingest_train import sku_box_frac

CLEAN_MANIFEST = PROJECT_ROOT / ".batch3_clean" / "clean_manifest.json"
CLEAN_BLOBS = PROJECT_ROOT / ".batch3_clean" / "blobs"
GRAY_MANIFEST = PROJECT_ROOT / "batch3_gray" / "gray_manifest.json"
REGISTRY = PROJECT_ROOT / "data" / "sku_registry.json"
PROTOCOL_DIR = PROJECT_ROOT / ".data_protocol"
DATASETS_DIR = PROJECT_ROOT / ".datasets"
STAGING_DIR = DATASETS_DIR / ".staging"

# 未注册商品（other 等）没有 SKU 尺寸表，用标准瓶比例近似（pilot 口径，
# 在 build_audit 中披露；正式全量前应替换为真实框标注）。
UNREGISTERED_BOX_FRAC = (0.07, 0.18)


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True, cwd=PROJECT_ROOT).stdout.strip() or "(unknown)"
    except Exception:
        return "(unknown)"


def _builder_hash() -> str:
    h = hashlib.sha256()
    for f in (Path(__file__), Path(__file__).parent.parent / "data" / "store_norm.py",
              Path(__file__).parent.parent / "data" / "protocol_guard.py"):
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def _candidate_pool(clean: dict, anns: dict, gray_ids: set) -> list[str]:
    """有注册或未注册商品标注、非灰名单的 batch3 照片。"""
    out = []
    for pid, recd in clean.items():
        pid = str(pid)
        if pid in gray_ids or not anns.get(pid):
            continue
        if not recd.get("sha256") or not recd.get("filename"):
            continue
        out.append(pid)
    return out


def _exclude_sets(clean: dict) -> tuple[set, set, set, set]:
    """active protocol 五键排除集（抽样前）。返回 (pids, shas, stores, sessions)。"""
    active, _ = protocol_guard.load_active_sets(PROTOCOL_DIR, clean)
    pids, shas, stores, sessions = set(), set(), set(), set()
    for e in active.values():
        pids |= e["pids"]
        shas |= e["shas"]
        stores |= e["stores"]
        sessions |= e["sessions"]
    return pids, shas, stores, sessions


def sample_store_groups(pool: list, clean: dict, train_budget: int, val_budget: int,
                        seed: int) -> tuple[list, list]:
    """按门店整组抽样：train/val 门店互斥（session 隔离自动满足）。"""
    rng = random.Random(seed)
    groups: dict = collections.defaultdict(list)
    for pid in pool:
        groups[store_of_filename(clean[pid]["filename"])].append(pid)
    order = sorted(groups.keys())
    rng.shuffle(order)

    val_ids: list = []
    train_ids: list = []
    phase = "val"
    for st in order:
        if phase == "val":
            val_ids.extend(groups[st])
            if len(val_ids) >= val_budget:
                phase = "train"
        else:
            train_ids.extend(groups[st])
            if len(train_ids) >= train_budget:
                break
    if len(val_ids) < val_budget or len(train_ids) < train_budget:
        raise RuntimeError(
            f"候选不足：val {len(val_ids)}/{val_budget}，train {len(train_ids)}/{train_budget}")
    # 门店整组不可拆分：实际张数可能略超 budget（在 audit 中披露）
    return train_ids, val_ids


def _boxes_for(pid: str, anns: dict, registry: dict, W: int, H: int,
               mode: str) -> tuple[list[str], dict]:
    """生成 YOLO 标签行。mode=product：全部商品 → class 0。"""
    lines, stats = [], {"registered": 0, "unregistered": 0, "tiny_skipped": 0}
    for a in anns.get(pid, []):
        name = a["name"]
        if mode == "product":
            cls = 0
            wf, hf = sku_box_frac(name) if name in registry else UNREGISTERED_BOX_FRAC
            stats["registered" if name in registry else "unregistered"] += 1
        else:
            reg = registry.get(name)
            if reg is None:
                continue
            cls = reg["class_id"]
            wf, hf = sku_box_frac(name)
        bw, bh = wf * W, hf * H
        x, y = a["x"], a["y"]
        x1, y1 = max(0, x - bw / 2), max(0, y - bh / 2)
        x2, y2 = min(W, x + bw / 2), min(H, y + bh / 2)
        if x2 - x1 < 2 or y2 - y1 < 2:
            stats["tiny_skipped"] += 1
            continue
        lines.append(f"{cls} {(x1+x2)/2/W:.6f} {(y1+y2)/2/H:.6f} {(x2-x1)/W:.6f} {(y2-y1)/H:.6f}")
    return lines, stats


def _validate_stage(root: Path, nc: int, clean: dict) -> dict:
    """发布前强校验，任何失败抛异常（staging 目录随后由调用方清理）。"""
    report = {"splits": {}}
    all_stores, all_sessions = {}, {}
    for split in ("train", "val"):
        imgs = {f.stem: f for f in (root / "images" / split).iterdir()}
        lbls = {f.stem: f for f in (root / "labels" / split).iterdir()}
        if set(imgs) != set(lbls):
            raise RuntimeError(f"{split} 图片/标签不一一对应: "
                               f"img-only={len(set(imgs)-set(lbls))}, lbl-only={len(set(lbls)-set(imgs))}")
        if split == "val" and not imgs:
            raise RuntimeError("val 为空，拒绝发布")
        n_boxes, corrupt = 0, []
        stores, sessions = set(), set()
        from PIL import Image
        for stem, fp in sorted(imgs.items()):
            try:
                with Image.open(fp) as im:
                    im.verify()
            except Exception:
                corrupt.append(stem)
                continue
            for ln in lbls[stem].read_text(encoding="utf-8").strip().splitlines():
                c = int(ln.split()[0])
                if not (0 <= c < nc):
                    raise RuntimeError(f"{split}/{stem} label class 越界: {c} (nc={nc})")
                n_boxes += 1
            # 从文件名还原门店/session（写入时以 pid 命名: p_<pid>）
            pid = stem.split("_", 1)[1] if "_" in stem else ""
            fn = (clean.get(pid) or {}).get("filename", "")
            if fn:
                stores.add(norm_store(store_of_filename(fn)))
                sessions.add(session_of_filename(fn))
        if corrupt:
            raise RuntimeError(f"{split} 损坏图片 {len(corrupt)} 张: {corrupt[:5]}")
        report["splits"][split] = {"images": len(imgs), "boxes": n_boxes}
        all_stores[split], all_sessions[split] = stores, sessions
    cross_store = all_stores["train"] & all_stores["val"]
    cross_sess = all_sessions["train"] & all_sessions["val"]
    if cross_store or cross_sess:
        raise RuntimeError(f"train/val 泄漏: 门店交集 {len(cross_store)}，session 交集 {len(cross_sess)}")
    report["train_val_store_overlap"] = 0
    report["train_val_session_overlap"] = 0
    return report


def _manifest(root: Path) -> tuple[str, int]:
    h, n = hashlib.sha256(), 0
    for split in ("train", "val"):
        for sub in ("images", "labels"):
            d = root / sub / split
            for f in sorted(d.iterdir()):
                n += 1
                h.update(f"{sub}/{split}/{f.name}".encode())
                fh = hashlib.sha256()
                with open(f, "rb") as fp:
                    while True:
                        b = fp.read(1 << 20)
                        if not b:
                            break
                        fh.update(b)
                h.update(fh.digest())
    return h.hexdigest()[:16], n


def build(name: str, mode: str = "product", train_photos: int = 2000,
          val_photos: int = 300, seed: int = 42, dry_run: bool = False) -> dict:
    t0 = time.time()
    final_dir = DATASETS_DIR / name
    if final_dir.exists():
        raise RuntimeError(f"数据集已存在，拒绝覆盖: {final_dir}（新版本请用新名称）")

    clean = json.loads(CLEAN_MANIFEST.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    gray_ids = set(json.loads(GRAY_MANIFEST.read_text(encoding="utf-8")).keys()) \
        if GRAY_MANIFEST.exists() else set()
    print(f"[{name}] 解析标注 ...")
    anns = parse_batch3_annotations()

    # G2：抽样前排除 active protocol 五键
    ex_pids, ex_shas, ex_stores, ex_sessions = _exclude_sets(clean)
    pool_all = _candidate_pool(clean, anns, gray_ids)
    pool = []
    rej = collections.Counter()
    for pid in pool_all:
        recd = clean[pid]
        st = norm_store(store_of_filename(recd["filename"]))
        if pid in ex_pids:
            rej["photo_id"] += 1
        elif recd["sha256"] in ex_shas:
            rej["sha256"] += 1
        elif st in ex_stores:
            rej["store_alias"] += 1
        elif session_of_filename(recd["filename"]) in ex_sessions:
            rej["session"] += 1
        else:
            pool.append(pid)
    print(f"  候选池: {len(pool_all)} → 排除 {dict(rej)} → 可用 {len(pool)}")

    train_ids, val_ids = sample_store_groups(pool, clean, train_photos, val_photos, seed)
    sel = train_ids + val_ids

    # 抽样后 fail-closed 复核（五键，active 集交集即抛错）
    sel_shas = [clean[p]["sha256"] for p in sel]
    sel_stores = [store_of_filename(clean[p]["filename"]) for p in sel]
    sel_sessions = [session_of_filename(clean[p]["filename"]) for p in sel]
    guard_report = protocol_guard.check_no_leak(
        sel, sel_shas, sel_stores, sel_sessions, clean, PROTOCOL_DIR, f"{name} 抽样复核")

    nc = 1 if mode == "product" else len(registry)
    names = ["product"] if mode == "product" else \
        sorted(registry.keys(), key=lambda n: registry[n]["class_id"])
    if dry_run:
        print(f"  [dry-run] train={len(train_ids)} val={len(val_ids)} nc={nc}")
        return {"dry_run": True, "train": len(train_ids), "val": len(val_ids)}

    # staging 写入
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    stage = STAGING_DIR / f"{name}_{stamp}_{os.getpid()}"
    try:
        box_stats = collections.Counter()
        for split, ids in (("train", train_ids), ("val", val_ids)):
            (stage / "images" / split).mkdir(parents=True)
            (stage / "labels" / split).mkdir(parents=True)
            for pid in ids:
                recd = clean[pid]
                blob = CLEAN_BLOBS / recd["sha256"][:2] / recd["sha256"]
                if not blob.exists():
                    raise RuntimeError(f"blob 缺失: {pid}")
                from PIL import Image
                with Image.open(blob) as im:
                    W, H = im.size
                lines, stt = _boxes_for(pid, anns, registry, W, H, mode)
                if not lines:
                    continue
                img = stage / "images" / split / f"p_{pid}.jpg"
                if not img.exists():
                    img.symlink_to(blob.resolve())
                (stage / "labels" / split / f"p_{pid}.txt").write_text(
                    "\n".join(lines) + "\n", encoding="utf-8")
                box_stats.update(stt)

        val_report = _validate_stage(stage, nc, clean)
        manifest_hash, n_files = _manifest(stage)

        # data.yaml
        yaml = (f"path: {final_dir.resolve()}\ntrain: images/train\nval: images/val\n"
                f"nc: {nc}\nnames: {json.dumps(names, ensure_ascii=False)}\n")
        (stage / "data.yaml").write_text(yaml, encoding="utf-8")

        # build_audit（发布前先写进 staging，随数据集一起原子落盘）
        audit = {
            "dataset": name, "mode": mode, "seed": seed,
            "train_photos_target": train_photos, "val_photos_target": val_photos,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": round(time.time() - t0, 1),
            "git_commit": _git_commit(), "builder_hash": _builder_hash(),
            "python": platform.python_version(), "platform": platform.platform(),
            "params": {"mode": mode, "train_photos": train_photos,
                       "val_photos": val_photos, "seed": seed,
                       "unregistered_box_frac": UNREGISTERED_BOX_FRAC},
            "splits": val_report["splits"],
            "train_val_store_overlap": val_report["train_val_store_overlap"],
            "train_val_session_overlap": val_report["train_val_session_overlap"],
            "box_stats": dict(box_stats),
            "candidate_exclusion": dict(rej),
            "protocol_guard": guard_report,
            "manifest_hash": manifest_hash, "n_files": n_files,
            "train_photo_ids": sorted(train_ids), "val_photo_ids": sorted(val_ids),
        }
        (stage / "build_audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

        # 原子发布
        DATASETS_DIR.mkdir(parents=True, exist_ok=True)
        if final_dir.exists():
            raise RuntimeError(f"发布目录已存在，拒绝覆盖: {final_dir}")
        os.rename(stage, final_dir)
    except Exception:
        import shutil
        shutil.rmtree(stage, ignore_errors=True)
        raise

    print(f"\n=== 数据集 {name} 发布完成 ===")
    print(f"  train={val_report['splits']['train']['images']} "
          f"val={val_report['splits']['val']['images']} nc={nc}")
    print(f"  manifest={manifest_hash} ({n_files} 文件) 目录={final_dir}")
    return {"dataset": name, "dir": str(final_dir), "manifest_hash": manifest_hash,
            "splits": val_report["splits"], "guard": guard_report}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--mode", choices=["product"], default="product")
    ap.add_argument("--train-photos", type=int, default=2000)
    ap.add_argument("--val-photos", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    build(a.name, a.mode, a.train_photos, a.val_photos, a.seed, a.dry_run)
