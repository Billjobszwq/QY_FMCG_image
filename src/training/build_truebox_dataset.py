"""e3_product_truebox_pilot_v1 构建器（手册§十一 / 用户要求#20/#21）。

沿用 `.datasets/e2_product_pilot_v1` 的同图同 split（train 2000 / val 300），
仅把合成点框替换为人工双审后的真实框。全部守卫 fail-closed：

- 目标目录已存在 → FileExistsError（绝不覆盖，需换新版本名）；
- 审核完成率必须 100%：每张 split 照片必须有 approved 的人工最终框；
- 未审核 prediction（review.status != approved）一律拒绝；
- quality manual_review 必须有最终人工裁决；
- 五键 protocol guard：diagnostic 等 active 冻结集零泄漏；
- train/val 门店与 session 交集必须为 0；
- staging + 原子发布（os.replace），失败不留半成品。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from ..data import protocol_guard

DATASET_VERSION = "e3_truebox_builder_v1"
REQUIRED_REVIEW_STATUS = "approved"


def _builder_hash() -> str:
    return hashlib.sha256(
        Path(__file__).read_bytes()).hexdigest()[:16]


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except Exception:
        return ""


def collect_e2_split(e2_root: Path) -> dict:
    """读取 e2 数据集的图片 split（pid 列表），e3 必须完全沿用。"""
    e2_root = Path(e2_root)
    out = {}
    for split in ("train", "val"):
        d = e2_root / "images" / split
        if not d.is_dir():
            raise FileNotFoundError(f"e2 split 缺失: {d}")
        pids = sorted(f.stem.split("_", 1)[1]
                      for f in d.glob("p_*.jpg"))
        out[split] = pids
    return out


def _validate_entries(split_ids: dict, manifest: list) -> dict:
    by_pid = {}
    for e in manifest:
        pid = str(e["photo_id"])
        if pid in by_pid:
            raise RuntimeError(f"truebox manifest 重复条目: {pid}")
        by_pid[pid] = e

    all_ids = split_ids["train"] + split_ids["val"]
    missing = [p for p in all_ids if p not in by_pid]
    if missing:
        done = len(all_ids) - len(missing)
        raise RuntimeError(
            f"人工审核完成率 {done}/{len(all_ids)} < 100%："
            f"{len(missing)} 张缺人工最终框（如 {missing[:3]}）。"
            f"fail-closed，禁止用 prediction 顶替。")

    for pid, e in by_pid.items():
        rv = e.get("review") or {}
        if rv.get("status") != REQUIRED_REVIEW_STATUS:
            raise RuntimeError(
                f"photo {pid} 未审核（review.status="
                f"{rv.get('status')!r}）：不允许使用未审核 prediction。")
        if not rv.get("annotator_1") or not rv.get("annotator_2"):
            raise RuntimeError(f"photo {pid} 缺双审标注者记录。")
        qv = e.get("quality_verdict")
        if qv == "reject":
            raise RuntimeError(f"photo {pid} 质量 reject，不得进入训练集。")
        if qv == "manual_review":
            fd = rv.get("final_quality_decision")
            if fd not in ("accept", "warn"):
                raise RuntimeError(
                    f"photo {pid} quality manual_review 无最终人工裁决"
                    f"（final_quality_decision={fd!r}）。")
        elif qv not in ("accept", "warn"):
            raise RuntimeError(f"photo {pid} 未知质量档: {qv!r}")
        for b in e.get("boxes", []):
            if b.get("source") != "human_final":
                raise RuntimeError(
                    f"photo {pid} 存在非 human_final 框: {b.get('source')!r}")
    return by_pid


def _yolo_line(box_px, w: int, h: int) -> str:
    x1, y1, x2, y2 = box_px
    cx = ((x1 + x2) / 2.0) / w
    cy = ((y1 + y2) / 2.0) / h
    bw = (x2 - x1) / w
    bh = (y2 - y1) / h
    if not (0 < bw <= 1 and 0 < bh <= 1 and 0 <= cx <= 1 and 0 <= cy <= 1):
        raise RuntimeError(f"框越界: {box_px} (图 {w}x{h})")
    return f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}"


def build_truebox_dataset(*, e2_root: Path, truebox_manifest: list,
                          target: Path, protocol_dir: Path,
                          clean: dict | None = None,
                          sam_checkpoint_sha256: str = "") -> dict:
    target = Path(target)
    if target.exists():
        raise FileExistsError(
            f"目标数据集已存在，绝不覆盖: {target}（请换新版本名）")

    split_ids = collect_e2_split(e2_root)
    by_pid = _validate_entries(split_ids, truebox_manifest)

    # 五键零泄漏守卫（diagnostic 等 active 冻结集）
    if not Path(protocol_dir).exists():
        raise FileNotFoundError(
            f"protocol 目录不存在，五键守卫无法执行（fail-closed）: "
            f"{protocol_dir}")
    pids = split_ids["train"] + split_ids["val"]
    entries = [by_pid[p] for p in pids]
    guard_report = protocol_guard.check_no_leak(
        pids, [e.get("sha256") for e in entries],
        [e.get("store_canonical") for e in entries],
        [e.get("session") for e in entries if e.get("session")],
        clean or {}, Path(protocol_dir), "e3 truebox build")

    # train/val 门店与 session 隔离
    def _sets(split):
        st = {by_pid[p]["store_canonical"] for p in split_ids[split]}
        se = {by_pid[p]["session"] for p in split_ids[split]
              if by_pid[p].get("session")}
        return st, se
    tr_st, tr_se = _sets("train")
    va_st, va_se = _sets("val")
    if tr_st & va_st:
        raise RuntimeError(f"train/val 门店交集非零: {sorted(tr_st & va_st)}")
    if tr_se & va_se:
        raise RuntimeError(f"train/val session 交集非零: {sorted(tr_se & va_se)}")
    if not split_ids["val"]:
        raise RuntimeError("val split 为空，禁止构建。")

    # staging → 原子发布
    stage = target.with_name(target.name + ".staging")
    if stage.exists():
        raise FileExistsError(f"staging 已存在（上次构建未完成？）: {stage}")
    stage.mkdir(parents=True)
    try:
        n_boxes = {"train": 0, "val": 0}
        for split in ("train", "val"):
            (stage / "images" / split).mkdir(parents=True)
            (stage / "labels" / split).mkdir(parents=True)
            for pid in split_ids[split]:
                src = Path(e2_root) / "images" / split / f"p_{pid}.jpg"
                shutil.copy2(src, stage / "images" / split / f"p_{pid}.jpg")
                e = by_pid[pid]
                lines = [_yolo_line(b["box_px"], e["width"], e["height"])
                         for b in e.get("boxes", [])]
                (stage / "labels" / split /
                 f"p_{pid}.txt").write_text("\n".join(lines) +
                                            ("\n" if lines else ""),
                                            encoding="utf-8")
                n_boxes[split] += len(lines)
            imgs = list((stage / "images" / split).glob("*.jpg"))
            lbls = {f.stem for f in (stage / "labels" / split).glob("*.txt")}
            if {f.stem for f in imgs} != lbls:
                raise RuntimeError(f"{split} 图片/标签不一一对应")

        (stage / "data.yaml").write_text(
            f"path: {target}\ntrain: images/train\nval: images/val\n"
            f'nc: 1\nnames: ["product"]\n', encoding="utf-8")

        manifest_hash = hashlib.sha256(
            json.dumps(truebox_manifest, sort_keys=True,
                       ensure_ascii=False).encode()).hexdigest()
        qdist = {}
        for e in entries:
            q = e["quality_verdict"]
            if q == "manual_review":
                q = e["review"]["final_quality_decision"]
            qdist[q] = qdist.get(q, 0) + 1
        audit = {
            "dataset": target.name,
            "builder_version": DATASET_VERSION,
            "base_split": Path(e2_root).name,
            "label_source": "human_final_only",
            "review_completion": 1.0,
            "quality_distribution": qdist,
            "splits": {s: {"images": len(split_ids[s]),
                           "boxes": n_boxes[s]} for s in ("train", "val")},
            "train_val_store_overlap": 0,
            "train_val_session_overlap": 0,
            "protocol_guard": guard_report,
            "manifest_sha256": manifest_hash,
            "builder_hash": _builder_hash(),
            "sam_checkpoint_sha256": sam_checkpoint_sha256,
            "git_commit": _git_commit(),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        (stage / "build_audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
        os.replace(stage, target)  # 原子发布
        return audit
    except Exception:
        # fail-closed：发布失败则 staging 保持可追溯但绝不发布
        raise
