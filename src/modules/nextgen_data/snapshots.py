"""N2 Task 7：四类 DatasetSnapshot builder（02 设计 §5）。

共享契约：
- label source tier：human_gold > legacy_coordinate_verified >
  sam_verified_pseudo；model_proposal 拒入训练；
- human gold 样本整体进独立冻结 eval，pseudo 永不进 eval；
- train/val 按 photo 组分组（SHA/store/session/near-dup/package
  五键零泄漏）；确定性分配（sha 排序 80/20）；
- staging → 原子发布；目标目录存在拒绝覆盖。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

LABEL_TIERS = ("human_gold", "legacy_coordinate_verified",
               "sam_verified_pseudo", "model_proposal",
               "unknown_new_packaging")

TRAIN_WEIGHTS = {"human_gold": 1.0,
                 "legacy_coordinate_verified": 0.8,
                 "sam_verified_pseudo": 0.6,
                 "unknown_new_packaging": 0.5}

BUILDER_VERSION = "nextgen_snapshot_builder_v1"
GUARD_KEYS = ("photo_sha256", "store", "session", "near_dup_group",
              "package_version_id")


class SnapshotError(RuntimeError):
    """Snapshot 构建错误（fail-closed）。"""


def _check_label_sources(samples: list[dict]) -> None:
    for s in samples:
        ls = s.get("label_source")
        if ls not in TRAIN_WEIGHTS:
            raise SnapshotError(
                f"label_source 不可训练（拒入）: {ls}；"
                f"region={s.get('region_id')}")


def group_split(samples: list[dict], *, val_ratio: float = 0.2
                ) -> dict[str, str]:
    """组级确定性 split：store/session/near-dup 组整体落同一 split
    （02 §2.3）；photo SHA 永不跨 split；hint 覆盖。"""
    by_photo: dict[str, list[dict]] = {}
    for s in samples:
        by_photo.setdefault(s["photo_sha256"], []).append(s)
    # photo -> 组键（store@session@near_dup；缺省退化为 sha 自身）
    group_of_photo: dict[str, str] = {}
    for sha, ss in by_photo.items():
        s0 = ss[0]
        gk = f"{s0.get('store') or ''}@{s0.get('session') or ''}" \
             f"@{s0.get('near_dup_group') or ''}"
        group_of_photo[sha] = gk if gk != "@@" else f"sha:{sha}"
    split_of_photo: dict[str, str] = {}
    hinted_photos: set[str] = set()
    for sha, ss in by_photo.items():
        hint = next((x.get("split_hint") for x in ss
                     if x.get("split_hint")), None)
        if hint:
            # hint 只作用于该 photo；若造成组键跨 split，
            # 由 _leak_check fail-closed 拒绝（不静默服从）
            split_of_photo[sha] = hint
            hinted_photos.add(sha)
    auto = sorted({g for sha, g in group_of_photo.items()
                   if sha not in hinted_photos})
    n_val = max(1, int(len(auto) * val_ratio)) if len(auto) > 1 else 0
    val_groups = set(auto[len(auto) - n_val:])
    for sha, g in group_of_photo.items():
        if sha not in split_of_photo:
            split_of_photo[sha] = "val" if g in val_groups else "train"
    return split_of_photo


def _leak_check(samples: list[dict], split_of_photo: dict[str, str]) -> None:
    """train/val 五键零泄漏（eval 为独立冻结 gold，不参与此检查）。"""
    def keysets(split):
        ks = {k: set() for k in GUARD_KEYS}
        for s in samples:
            if split_of_photo[s["photo_sha256"]] != split:
                continue
            for k in GUARD_KEYS:
                v = s.get(k)
                if v:
                    ks[k].add(v)
        return ks
    tr, va = keysets("train"), keysets("val")
    for k in GUARD_KEYS:
        ov = tr[k] & va[k]
        if ov:
            raise SnapshotError(
                f"split leakage: {k} 跨 train/val: {sorted(ov)[:5]}")


def _publish(snapshot_id: str, lane: str, schema: str,
             out_root: Path, samples_out: list[dict],
             split_of_photo: dict[str, str],
             exclusion_ledger: list[dict], extra: dict
             ) -> dict[str, Any]:
    final = Path(out_root) / snapshot_id
    if final.exists():
        raise SnapshotError(f"目标目录已存在，拒绝覆盖: {final}")
    staging = Path(out_root) / f".staging-{snapshot_id}"
    if staging.exists():
        raise SnapshotError(f"staging 残留，拒绝构建: {staging}")
    staging.mkdir(parents=True)
    try:
        split_report = {}
        for s in samples_out:
            split_report[s["split"]] = split_report.get(s["split"], 0) + 1
        body = {"schema_version": schema, "lane": lane,
                "builder_version": BUILDER_VERSION,
                "snapshot_id": snapshot_id,
                "split_report": split_report,
                "exclusion_ledger": exclusion_ledger,
                "quality_histogram": {},
                "source_hashes": {
                    "samples_sha256": hashlib.sha256(
                        json.dumps(samples_out, sort_keys=True,
                                   ensure_ascii=False).encode()).hexdigest()},
                "samples": samples_out, **extra}
        mh = hashlib.sha256(json.dumps(
            body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        manifest = {**body, "manifest_hash": mh}
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1),
            encoding="utf-8")
        os.replace(staging, final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {"snapshot_id": snapshot_id, "lane": lane,
            "path": str(final), "manifest": manifest}


def _assign_splits(samples, split_of_photo):
    for s in samples:
        s = dict(s)
    out = []
    for s in samples:
        d = dict(s)
        d["split"] = split_of_photo[d["photo_sha256"]]
        d["sample_weight"] = TRAIN_WEIGHTS.get(d["label_source"], 0.5)
        out.append(d)
    return out


def _separate_eval(samples):
    """human gold 整体进独立冻结 eval；其余进 train/val。"""
    eval_s, train_s = [], []
    for s in samples:
        (eval_s if s["label_source"] == "human_gold" else train_s).append(s)
    return train_s, eval_s


def _build_common(samples, out_root, snapshot_id, lane, schema, extra=None,
                  transform=None, exclusion_ledger=None):
    _check_label_sources(samples)
    train_s, eval_s = _separate_eval(samples)
    split_of_photo = group_split(train_s)
    _leak_check(train_s, split_of_photo)
    out = _assign_splits(train_s, split_of_photo)
    for s in eval_s:
        d = dict(s)
        d["split"] = "eval"
        d["sample_weight"] = TRAIN_WEIGHTS.get(d["label_source"], 1.0)
        out.append(d)
    if transform:
        out = [transform(s) for s in out]
    return _publish(snapshot_id, lane, schema, Path(out_root), out,
                    split_of_photo, exclusion_ledger or [], extra or {})


def build_detector_snapshot(samples, *, out_root, snapshot_id):
    def t(s):
        d = dict(s)
        d["class"] = "product"
        x1, y1, x2, y2 = d["box"]
        d["norm_box"] = [x1 / d["width"], y1 / d["height"],
                         x2 / d["width"], y2 / d["height"]]
        return d
    return _build_common(samples, out_root, snapshot_id, "detector",
                         "detector-snapshot.v2", transform=t)


def build_segmenter_snapshot(samples, *, out_root, snapshot_id):
    for s in samples:
        if not s.get("mask_rle") or not s.get("tight_box"):
            raise SnapshotError(
                f"segmenter 需要真实 mask（mask gold/SAM 审核门后）: "
                f"region={s.get('region_id')}")
    def t(s):
        d = dict(s)
        d["prompt"] = {"point": None, "box": d.get("box")}
        return d
    rep = _build_common(samples, out_root, snapshot_id, "segmenter",
                        "segmenter-snapshot.v2", transform=t,
                        extra={"trainable": True,
                               "teacher": "sam2.1_frozen（不训练 SAM 本体）"})
    return rep


def build_classifier_snapshot(samples, *, out_root, snapshot_id):
    def t(s):
        d = dict(s)
        d["crop"] = {"ref": f"crop://{d['photo_sha256']}/{d['region_id']}",
                     "split": d["split"], "kind": "tight_box"}
        return d
    return _build_common(samples, out_root, snapshot_id, "classifier",
                         "classifier-snapshot.v2", transform=t)


def build_vlm_snapshot(samples, *, out_root, snapshot_id):
    def t(s):
        d = dict(s)
        if not s.get("sku_id"):
            d["target_type"] = s.get("sku_status") in ("new_packaging",) \
                and "new_package" or "unknown"
        else:
            d["target_type"] = "closed_set"
        d["candidates"] = s.get("candidates", [])
        d["context"] = {
            "context_crop_ref":
                f"context://{d['photo_sha256']}/{d['region_id']}",
            "ocr_text": s.get("ocr_text") or ""}
        return d
    return _build_common(samples, out_root, snapshot_id, "vlm",
                         "vlm-snapshot.v2", transform=t)
