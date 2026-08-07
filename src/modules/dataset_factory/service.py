"""Dataset Factory：四训练通道数据集构建（GLTC Task 3 / 01 §3）。

四条 builder 共享本模块的身份、准入、泄漏守卫、staging/原子发布与
审计基础库，但各自拥有独立 schema（不共享错误标签语义）。

红线：
- 只从事实源读取（gold_region/审核事实注入），不接受客户端自由 JSON
  冒充审核结论；
- 仅 human_final/gold_verified 准入；rq_v1、invalidated、frozen
  protocol、model-only proposal 一律拒入（exclusion ledger 留痕）；
- unknown/new_packaging 保留原语义，不强行改写成已有 SKU；
- 输出目录已存在拒绝覆盖；staging 完成后原子发布；
- D3 无真实 mask gold 只能 calibration，不可 trainable；
- D4 CandidateSet 构造签名禁止接收 GT。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from src.modules.training_control.contracts import SNAPSHOT_SCHEMA_BY_LANE
from src.modules.training_control.vocabulary import TRAINING_LANES

BUILDER_VERSION = "dataset_factory_v1"

ADMITTED_REVIEW_STATUSES = frozenset({"human_final", "gold_verified"})
FROZEN_QUEUE_VERSIONS = frozenset({"rq_v1"})
FROZEN_PROTOCOL_PREFIXES = ("diagnostic_", "calibration_", "dev_",
                            "gold_", "holdout_")
SPLIT_GUARD_KEYS = ("sha256", "store", "session", "near_dup_group",
                    "package_version")


class DatasetFactoryError(RuntimeError):
    """Dataset Factory 错误基类（fail-closed）。"""


class SplitLeakageError(DatasetFactoryError):
    def __init__(self, violations: list[dict[str, Any]]) -> None:
        self.violations = violations
        super().__init__(f"split 泄漏守卫拦截: {violations}")


class PublishError(DatasetFactoryError):
    """发布失败（目录已存在/覆盖企图）。"""


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_admission(row: dict[str, Any]) -> str | None:
    """返回排除原因；None = 准入。"""
    if row.get("queue_version") in FROZEN_QUEUE_VERSIONS:
        return "invalid_queue_version"
    protocol = str(row.get("protocol") or "")
    if protocol.startswith(FROZEN_PROTOCOL_PREFIXES):
        return "frozen_protocol"
    if row.get("review_status") not in ADMITTED_REVIEW_STATUSES:
        return "forbidden_label_source"
    if not (row.get("asset_id") and row.get("photo_sha256")
            and row.get("region_id")):
        return "identity_incomplete"
    return None


def check_split_leakage(rows: list[dict[str, Any]]) -> None:
    """group split 守卫：SHA/门店/session/近重复/包装版本跨 split 即拒。"""
    violations: list[dict[str, Any]] = []
    field_map = {"sha256": "photo_sha256", "package_version":
                 "package_version_id"}
    for key in SPLIT_GUARD_KEYS:
        field = field_map.get(key, key)
        train = {r[field] for r in rows if r.get("split") == "train"
                 and r.get(field)}
        val = {r[field] for r in rows if r.get("split") == "val"
               and r.get(field)}
        overlap = sorted(train & val)
        if overlap:
            violations.append({"key": key, "overlap": overlap})
    if violations:
        raise SplitLeakageError(violations)


def _quality_histogram(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """简单质量分布（面积占比分桶 + 图像尺寸集合）。"""
    buckets: dict[str, int] = {"small(<1%)": 0, "medium(1-10%)": 0,
                               "large(>10%)": 0}
    sizes: set[tuple[int, int]] = set()
    for r in rows:
        x1, y1, x2, y2 = r["box"]
        w = int(r.get("image_width") or 0)
        h = int(r.get("image_height") or 0)
        sizes.add((w, h))
        if w <= 0 or h <= 0:
            continue
        frac = ((x2 - x1) * (y2 - y1)) / (w * h)
        if frac < 0.01:
            buckets["small(<1%)"] += 1
        elif frac <= 0.10:
            buckets["medium(1-10%)"] += 1
        else:
            buckets["large(>10%)"] += 1
    return {"box_area_fraction": buckets,
            "image_sizes": sorted(f"{w}x{h}" for w, h in sizes)}


def _to_sample(lane: str, r: dict[str, Any]) -> dict[str, Any]:
    """lane 专属样本序列化（身份统一：asset_id+sha+region_id）。"""
    base = {
        "asset_id": r["asset_id"], "photo_sha256": r["photo_sha256"],
        "region_id": r["region_id"], "image_uri": f"cas://{r['photo_sha256']}",
        "box": r["box"], "sku_id": r["sku_id"],
        "package_version_id": r.get("package_version_id", ""),
        "label_source": r["review_status"], "split": r["split"],
        "image_width": r.get("image_width"),
        "image_height": r.get("image_height"),
        "split_group": {"store": r.get("store", ""),
                        "session": r.get("session", ""),
                        "near_dup_group": r.get("near_dup_group", "")},
    }
    if lane == "detector":
        base["class"] = "product"  # 已知/未知/新包装都可作为 product 框
    elif lane == "classifier":
        # 派生 crop 继承原图 split（泄漏守卫由组键保证）
        base["crop"] = {
            "ref": f"crop://{r['photo_sha256']}/{r['region_id']}",
            "split": r["split"], "kind": "tight_box"}
    elif lane == "segmenter":
        base["mask_ref"] = r.get("mask_ref", "")
        base["prompt"] = {"box": r["box"]}
    elif lane == "vlm":
        base["context_crop_ref"] = (
            f"context://{r['photo_sha256']}/{r['region_id']}")
    return base


def build_candidate_set(query_text: str, *, registry_ids: list[str],
                        topk: int = 8,
                        score_fn: Any = None) -> list[dict[str, Any]]:
    """D4 候选构造：签名禁止接收 GT；不足 topk 自然截断，不补真值。

    score_fn(sku_id) -> float；缺省按 registry 顺序给递减分（占位检索）。
    """
    scored = []
    for i, sku in enumerate(registry_ids):
        score = score_fn(sku) if score_fn else (1.0 - 0.01 * i)
        scored.append({"sku_id": sku, "score": round(float(score), 6)})
    scored.sort(key=lambda c: c["score"], reverse=True)
    return scored[:max(0, topk)]


def build_snapshot(lane: str, *, rows: list[dict[str, Any]],
                   out_root: Path | str, dataset_id: str,
                   builder_version: str = BUILDER_VERSION
                   ) -> dict[str, Any]:
    """四通道统一构建入口：准入 → 泄漏守卫 → staging → 原子发布。

    0 条准入不写任何文件；目标目录已存在拒绝覆盖。
    """
    if lane not in TRAINING_LANES:
        raise DatasetFactoryError(f"非法 lane: {lane}")
    out_root = Path(out_root)
    final_dir = out_root / dataset_id
    if final_dir.exists():
        raise PublishError(f"目标目录已存在，拒绝覆盖: {final_dir}")

    # 1. 准入过滤（exclusion ledger 留痕）
    admitted: list[dict[str, Any]] = []
    exclusion_ledger: list[dict[str, Any]] = []
    for r in rows:
        reason = check_admission(r)
        if reason:
            exclusion_ledger.append({
                "asset_id": r.get("asset_id", ""),
                "region_id": r.get("region_id", ""),
                "reason": reason,
                "detail": f"review_status={r.get('review_status')}/"
                          f"queue={r.get('queue_version')}/"
                          f"protocol={r.get('protocol')}"})
        else:
            admitted.append(r)

    report: dict[str, Any] = {
        "lane": lane, "dataset_id": dataset_id,
        "builder_version": builder_version,
        "schema_version": SNAPSHOT_SCHEMA_BY_LANE[lane],
        "admitted": len(admitted), "rejected": len(exclusion_ledger),
        "exclusion_ledger": exclusion_ledger,
        "published": False,
    }
    if not admitted:
        report["note"] = "0 条准入样本：不写任何文件（fail-closed）"
        return report

    # 2. split 泄漏守卫（fail-closed）
    check_split_leakage(admitted)

    # 3. lane 专属门
    trainable = True
    mode = "trainable"
    if lane == "segmenter":
        if any(not r.get("mask_ref") for r in admitted):
            trainable, mode = False, "calibration_only"

    # 4. staging → 原子发布
    staging = out_root / f".staging-{dataset_id}"
    if staging.exists():
        raise PublishError(f"staging 残留，拒绝构建: {staging}")
    staging.mkdir(parents=True)
    try:
        samples = [_to_sample(lane, r) for r in admitted]
        split_report = {
            "train": sum(1 for s in samples if s["split"] == "train"),
            "val": sum(1 for s in samples if s["split"] == "val"),
        }
        source_hashes = {
            "input_rows_sha256": _sha_text(_canonical(rows)),
        }
        manifest_body = {
            "lane": lane, "dataset_id": dataset_id,
            "schema_version": SNAPSHOT_SCHEMA_BY_LANE[lane],
            "builder_version": builder_version,
            "trainable": trainable, "mode": mode,
            "split_report": split_report,
            "quality_histogram": _quality_histogram(admitted),
            "exclusion_ledger": exclusion_ledger,
            "source_hashes": source_hashes,
            "samples": samples,
        }
        manifest_hash = _sha_text(_canonical(
            {k: v for k, v in manifest_body.items()}))
        manifest = {**manifest_body, "manifest_hash": manifest_hash}
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1),
            encoding="utf-8")
        os.replace(staging, final_dir)  # 原子发布
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    report.update({
        "published": True, "path": str(final_dir),
        "manifest_hash": manifest_hash, "trainable": trainable,
        "mode": mode, "split_report": split_report,
        "quality_histogram": manifest["quality_histogram"],
        "source_hashes": source_hashes,
    })
    return report
