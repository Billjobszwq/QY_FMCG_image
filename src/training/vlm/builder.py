"""VLM-008：Canonical VLM 数据集 immutable staging builder。

红线：
- manual_pending/reject/frozen 审核状态与 model_provisional 标签无裁决
  不得进入正式 train；SAM geometry accepted 不自动等于 human_final；
- 输出目录已存在即拒绝（禁止覆盖旧数据集）；
- 先写 staging，完成 manifest hash / builder hash / registry hash /
  split report / sample histogram / 磁盘核对后原子发布。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.training.vlm.contracts import (
    SAMPLE_KINDS,
    TRAIN_ELIGIBLE_SOURCES,
    VlmSample,
)
from src.training.vlm.split_guard import validate_splits

BUILDER_VERSION = "vlm-builder.v1"
_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "fmcg://vlm-dataset-builder/v1")


class BuilderError(Exception):
    """builder 输入/状态错误（fail-closed）。"""


class DatasetExistsError(BuilderError):
    """输出目录已存在：禁止覆盖旧数据集。"""


def to_bbox_1000(box_px: Iterable[float], image_width: int,
                 image_height: int) -> list[int]:
    """原图像素 bbox → Qwen3-VL 0–1000 相对坐标（clamp 到 [0,1000]）。"""
    x1, y1, x2, y2 = [float(v) for v in box_px]
    return [
        max(0, min(1000, round(x1 * 1000.0 / image_width))),
        max(0, min(1000, round(y1 * 1000.0 / image_height))),
        max(0, min(1000, round(x2 * 1000.0 / image_width))),
        max(0, min(1000, round(y2 * 1000.0 / image_height))),
    ]


def _sample_id(row: Mapping) -> str:
    basis = json.dumps([row["photo_sha256"], list(row["box_px"]),
                        row["target_type"], row["split"]], sort_keys=True)
    return str(uuid.uuid5(_NAMESPACE, basis))


def _train_eligible(row: Mapping) -> str | None:
    """返回排除原因；None = 可进入其声明 split。"""
    status = row.get("review_status")
    if status != "train":
        return f"review_status:{status}"
    source = row.get("label_source")
    if source not in TRAIN_ELIGIBLE_SOURCES:
        # SAM 几何通过不自动等于 human_final，需人工裁决
        return f"label_source:{source}"
    if row.get("frozen"):
        return "frozen"
    if row.get("active_protocol"):
        return "active_protocol"
    return None


def build_dataset(
    rows: Iterable[Mapping[str, Any]],
    *,
    output_dir: Path | str,
    registry_version: str,
    builder_version: str = BUILDER_VERSION,
) -> dict[str, Any]:
    """构建不可变数据集：staging → 核对 → 原子发布。返回审计报告。"""
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise DatasetExistsError(f"输出目录已存在，禁止覆盖: {output_dir}")

    samples: list[VlmSample] = []
    excluded: list[dict] = []
    for row in rows:
        reason = _train_eligible(row)
        if reason is not None:
            excluded.append({"asset_id": row.get("asset_id"),
                             "photo_sha256": row.get("photo_sha256"),
                             "reason": reason})
            continue
        sample = VlmSample(
            sample_id=_sample_id(row),
            asset_id=row["asset_id"],
            photo_sha256=row["photo_sha256"],
            image_uri=row["image_uri"],
            image_width=int(row["image_width"]),
            image_height=int(row["image_height"]),
            box_px=tuple(float(v) for v in row["box_px"]),
            bbox_1000=tuple(to_bbox_1000(row["box_px"], row["image_width"],
                                         row["image_height"])),
            sku_id=row.get("sku_id"),
            package_version_id=row.get("package_version_id"),
            target_type=row["target_type"],
            label_source=row["label_source"],
            sample_weight=float(row.get("sample_weight", 1.0)),
            registry_version=registry_version,
            split=row["split"],
            split_group=dict(row["split_group"]),
            sample_kind=row.get("sample_kind", "region_crop"),
            evidence_ids=list(row.get("evidence_ids", [])),
        )
        samples.append(sample)

    # 防泄漏守卫：任何违规必须在发布前阻断
    guard_records = [
        {"sample_id": s.sample_id, "split": s.split,
         "sha256": s.photo_sha256,
         "split_group": s.split_group.model_dump(),
         "frozen": False, "active_protocol": False}
        for s in samples
    ]
    validate_splits(guard_records)

    histogram = {kind: 0 for kind in SAMPLE_KINDS}
    for s in samples:
        histogram[s.sample_kind] += 1
    total = max(1, len(samples))

    # 同一大图多条样本 → 重复视觉 token 估算审计
    asset_count: dict[str, int] = {}
    for s in samples:
        asset_count[s.asset_id] = asset_count.get(s.asset_id, 0) + 1
    audit = [{"type": "duplicate_visual_tokens", "asset_id": aid,
              "sample_count": n,
              "note": "同一大图多条样本，视觉 token 会重复计费/估算"}
             for aid, n in sorted(asset_count.items()) if n > 1]

    staging = output_dir.parent / (output_dir.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        lines = [s.model_dump_json() for s in samples]
        manifest_text = "\n".join(lines) + ("\n" if lines else "")
        (staging / "manifest.jsonl").write_text(manifest_text, encoding="utf-8")
        manifest_sha = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
        report = {
            "builder_version": builder_version,
            "builder_hash": hashlib.sha256(
                f"{builder_version}:{registry_version}:{manifest_sha}"
                .encode("utf-8")).hexdigest(),
            "registry_version": registry_version,
            "registry_hash": hashlib.sha256(
                registry_version.encode("utf-8")).hexdigest(),
            "manifest_sha256": manifest_sha,
            "sample_count": len(samples),
            "excluded_count": len(excluded),
            "excluded": excluded,
            "sample_histogram": histogram,
            "sample_kind_ratios": {k: round(v / total, 4)
                                   for k, v in histogram.items()},
            "split_counts": _split_counts(samples),
            "audit": audit,
        }
        (staging / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        # 磁盘核对：回读 manifest 逐条重新校验
        readback = (staging / "manifest.jsonl").read_text(encoding="utf-8")
        if readback != manifest_text:
            raise BuilderError("staging 磁盘核对失败：manifest 回读不一致")
        for line in readback.splitlines():
            VlmSample.model_validate(json.loads(line))
        os.replace(staging, output_dir)  # 原子发布
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return report


def _split_counts(samples: list[VlmSample]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in samples:
        counts[s.split] = counts.get(s.split, 0) + 1
    return counts
