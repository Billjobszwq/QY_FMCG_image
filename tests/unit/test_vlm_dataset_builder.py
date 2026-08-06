"""VLM-008：Canonical VLM 数据集 builder（immutable staging + 原子发布）TDD。

红线：
- manual_pending/reject/frozen/model_provisional 无裁决不得进入正式 train；
- SAM geometry accepted 不自动等于 human_final；
- 每条 sample 保留 asset、原图尺寸、像素 bbox、bbox_1000、registry version、
  label source、weight 与 evidence；
- 输出目录已存在即拒绝；先 staging 核对后原子发布；禁止覆盖旧数据集；
- HF 格式仅 images+messages，禁止手工 <|vision_start|>。
"""

from __future__ import annotations

import json

import pytest

from src.training.vlm.builder import (
    DatasetExistsError,
    build_dataset,
    to_bbox_1000,
)
from src.training.vlm.contracts import VlmSample
from src.training.vlm.hf_dataset import build_hf_rows
from src.training.vlm.split_guard import SplitLeakageError

REGISTRY = "registry-2026-08-v1"


def _row(**over) -> dict:
    row = {
        "asset_id": "asset-1",
        "photo_sha256": "aa" * 32,
        "image_uri": "cas://" + "aa" * 32,
        "image_width": 100,
        "image_height": 200,
        "box_px": [10.0, 20.0, 30.0, 60.0],
        "sku_id": "SKU-A",
        "package_version_id": "pv1",
        "target_type": "closed_set",
        "label_source": "human_final",
        "review_status": "train",
        "sample_weight": 1.0,
        "split": "train",
        "sample_kind": "region_crop",
        "split_group": {"customer": "c1", "store": "st1", "session": "ss1",
                        "near_dup_group": "nd1", "package_version": "pv1"},
        "evidence_ids": ["e1"],
        "frozen": False,
        "active_protocol": False,
    }
    row.update(over)
    return row


def _build(tmp_path, rows):
    out = tmp_path / "ds_v1"
    report = build_dataset(rows, output_dir=out, registry_version=REGISTRY)
    return out, report


# ---------- bbox 0–1000 坐标 ----------

def test_bbox_1000_conversion_and_clamp() -> None:
    assert to_bbox_1000([10, 20, 30, 60], 100, 200) == [100, 100, 300, 300]
    assert to_bbox_1000([-5, 0, 200, 400], 100, 200) == [0, 0, 1000, 1000]


# ---------- 裁决门禁 ----------

@pytest.mark.parametrize("review_status", ["manual_pending", "reject", "frozen"])
def test_unadjudicated_rows_never_enter_train(tmp_path, review_status) -> None:
    rows = [_row(), _row(asset_id="asset-2", photo_sha256="bb" * 32,
                         review_status=review_status,
                         split_group={"customer": "c2", "store": "st2",
                                      "session": "ss2", "near_dup_group": "nd2",
                                      "package_version": "pv2"})]
    out, report = _build(tmp_path, rows)
    manifest = [json.loads(line) for line in
                (out / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    train_assets = {m["asset_id"] for m in manifest if m["split"] == "train"}
    assert train_assets == {"asset-1"}
    assert any(e["reason"] == f"review_status:{review_status}"
               for e in report["excluded"])


def test_model_provisional_never_enters_train(tmp_path) -> None:
    rows = [_row(label_source="model_provisional")]
    out, report = _build(tmp_path, rows)
    assert not (out / "manifest.jsonl").read_text(encoding="utf-8").strip()
    assert report["excluded"][0]["reason"] == "label_source:model_provisional"


def test_sam_geometry_not_auto_human_final(tmp_path) -> None:
    rows = [_row(label_source="sam_geometry_verified")]
    out, report = _build(tmp_path, rows)
    manifest = (out / "manifest.jsonl").read_text(encoding="utf-8")
    assert manifest.strip() == ""
    assert any("sam_geometry_verified" in e["reason"] for e in report["excluded"])


# ---------- 样本字段完整性 ----------

def test_sample_fields_complete(tmp_path) -> None:
    out, _ = _build(tmp_path, [_row()])
    line = (out / "manifest.jsonl").read_text(encoding="utf-8").splitlines()[0]
    sample = VlmSample.model_validate(json.loads(line))
    assert sample.photo_sha256 == "aa" * 32
    assert sample.image_width == 100 and sample.image_height == 200
    assert sample.box_px == (10.0, 20.0, 30.0, 60.0)
    assert sample.bbox_1000 == (100, 100, 300, 300)
    assert sample.registry_version == REGISTRY
    assert sample.label_source == "human_final"
    assert sample.sample_weight == 1.0
    assert sample.evidence_ids == ["e1"]


# ---------- staging / 原子发布 / 防覆盖 ----------

def test_existing_output_dir_rejected(tmp_path) -> None:
    out = tmp_path / "ds_v1"
    out.mkdir()
    with pytest.raises(DatasetExistsError):
        build_dataset([_row()], output_dir=out, registry_version=REGISTRY)


def test_staging_cleaned_after_publish(tmp_path) -> None:
    out, _ = _build(tmp_path, [_row()])
    assert out.is_dir()
    leftovers = [p for p in tmp_path.iterdir() if ".staging" in p.name]
    assert leftovers == []


def test_split_leakage_aborts_before_publish(tmp_path) -> None:
    rows = [_row(),
            _row(asset_id="asset-2", split="val",
                 split_group={"customer": "c2", "store": "st2", "session": "ss2",
                              "near_dup_group": "nd2", "package_version": "pv2"})]
    # 同一原图 SHA 跨 train/val → 泄漏
    with pytest.raises(SplitLeakageError):
        build_dataset(rows, output_dir=tmp_path / "ds_v1",
                      registry_version=REGISTRY)
    assert not (tmp_path / "ds_v1").exists()


# ---------- 报告 ----------

def test_report_histogram_and_hashes(tmp_path) -> None:
    rows = [
        _row(),
        _row(asset_id="asset-2", photo_sha256="bb" * 32, sample_kind="full_image",
             split="val",
             split_group={"customer": "c2", "store": "st2", "session": "ss2",
                          "near_dup_group": "nd2", "package_version": "pv2"}),
        _row(asset_id="asset-3", photo_sha256="cc" * 32, target_type="unknown",
             sample_kind="unknown", sku_id=None, split="val",
             split_group={"customer": "c3", "store": "st3", "session": "ss3",
                          "near_dup_group": "nd3", "package_version": "pv3"}),
        _row(asset_id="asset-4", photo_sha256="dd" * 32,
             target_type="hard_negative", sample_kind="hard_negative",
             split="val",
             split_group={"customer": "c4", "store": "st4", "session": "ss4",
                          "near_dup_group": "nd4", "package_version": "pv4"}),
    ]
    out, report = _build(tmp_path, rows)
    hist = report["sample_histogram"]
    assert hist["region_crop"] == 1 and hist["full_image"] == 1
    assert hist["unknown"] == 1 and hist["hard_negative"] == 1
    assert report["manifest_sha256"] and report["builder_hash"]
    assert report["registry_hash"]
    # 报告落盘可审计
    on_disk = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert on_disk["manifest_sha256"] == report["manifest_sha256"]


def test_duplicate_large_image_audit(tmp_path) -> None:
    # 同一大图出两条样本（region crop + full image）→ 视觉 token 重复审计
    rows = [_row(sample_kind="region_crop"),
            _row(sample_kind="full_image",
                 split_group={"customer": "c1", "store": "st1", "session": "ss1",
                              "near_dup_group": "nd1", "package_version": "pv1"})]
    _, report = _build(tmp_path, rows)
    assert any(a["type"] == "duplicate_visual_tokens" for a in report["audit"])


# ---------- HF 格式（images + messages，禁手工 vision token） ----------

def test_hf_rows_images_messages_only(tmp_path) -> None:
    out, _ = _build(tmp_path, [_row(),
                               _row(asset_id="asset-2", photo_sha256="bb" * 32,
                                    target_type="unknown", sku_id=None,
                                    split="val",
                                    split_group={"customer": "c2", "store": "st2",
                                                 "session": "ss2",
                                                 "near_dup_group": "nd2",
                                                 "package_version": "pv2"})])
    manifest = [VlmSample.model_validate(json.loads(line)) for line in
                (out / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    rows = build_hf_rows(manifest, load_image=lambda uri: f"IMG:{uri}")
    assert len(rows) == 2
    for row in rows:
        assert set(row.keys()) == {"images", "messages"}
        assert "<|vision_start|>" not in json.dumps(row, ensure_ascii=False, default=str)
        user = row["messages"][0]
        assert user["role"] == "user"
        types = [c["type"] for c in user["content"]]
        assert types == ["image", "text"]
        assistant = row["messages"][1]
        answer = json.loads(assistant["content"][0]["text"])
        assert answer["schema_version"] == "qwen-sku-decision.v1"
    answers = [json.loads(r["messages"][1]["content"][0]["text"]) for r in rows]
    assert answers[0]["decision"] == "accepted" and answers[0]["sku_id"] == "SKU-A"
    assert answers[1]["decision"] == "unknown"
