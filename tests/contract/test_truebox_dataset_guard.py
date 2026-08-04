"""e3 真实框训练集守卫契约测试（手册§十一 / 用户要求#20/#21）。

锁定行为（全部 fail-closed）：
- 目标目录已存在 → 拒绝构建，绝不覆盖旧数据集；
- 人工审核完成率 <100%（缺照片/缺框/未审核 prediction）→ 拒绝；
- diagnostic 冻结集照片泄漏 → 五键守卫拒绝；
- train/val 门店或 session 交集非零 → 拒绝；
- 沿用 e2 同图同 split（仅替换标签），staging+原子发布；
- build audit 记录审核完成率、质量分布、builder hash、manifest hash。
"""
from __future__ import annotations

import json

import pytest

from src.training.build_truebox_dataset import (
    build_truebox_dataset, collect_e2_split)

JPEG_MIN = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\xff\xd9"


@pytest.fixture
def e2_root(tmp_path):
    root = tmp_path / "e2_product_pilot_v1"
    for split, pids in (("train", ["1", "2", "3"]), ("val", ["9"])):
        (root / "images" / split).mkdir(parents=True)
        (root / "labels" / split).mkdir(parents=True)
        for pid in pids:
            (root / "images" / split / f"p_{pid}.jpg").write_bytes(JPEG_MIN)
            (root / "labels" / split / f"p_{pid}.txt").write_text(
                "0 0.5 0.5 0.1 0.1\n")
    return root


def _entry(pid, split, *, status="approved", verdict="accept",
           store=None, session=None, boxes=None):
    return {
        "photo_id": pid,
        "sha256": f"{int(pid):064x}",
        "width": 100, "height": 100,
        "split": split,
        "store_canonical": store or f"store_{pid}",
        "session": session or f"sess_{pid}",
        "quality_verdict": verdict,
        "boxes": boxes if boxes is not None else
        [{"box_px": [10, 10, 30, 40], "source": "human_final"}],
        "review": {"status": status, "annotator_1": "a1",
                   "annotator_2": "a2", "reviewed_at": "2026-08-05T00:00:00"},
    }


def _full_manifest():
    return [_entry(p, "train") for p in ("1", "2", "3")] + [_entry("9", "val")]


class TestSplitReuse:
    def test_collect_matches_e2_images(self, e2_root):
        sp = collect_e2_split(e2_root)
        assert sorted(sp["train"]) == ["1", "2", "3"]
        assert sp["val"] == ["9"]


class TestGuards:
    def test_happy_path_builds_same_split_only_new_labels(self, e2_root,
                                                         tmp_path):
        target = tmp_path / "e3_product_truebox_pilot_v1"
        proto = tmp_path / "empty_protocol"
        proto.mkdir()
        audit = build_truebox_dataset(
            e2_root=e2_root, truebox_manifest=_full_manifest(),
            target=target, protocol_dir=proto)
        assert target.exists() and (target / "data.yaml").exists()
        assert audit["splits"]["train"]["images"] == 3
        assert audit["splits"]["val"]["images"] == 1
        assert audit["review_completion"] == 1.0
        assert audit["label_source"] == "human_final_only"
        assert audit["base_split"] == "e2_product_pilot_v1"
        lbl = (target / "labels/train/p_1.txt").read_text()
        assert lbl.strip() == "0 0.200000 0.250000 0.200000 0.300000"

    def test_existing_target_refused(self, e2_root, tmp_path):
        target = tmp_path / "e3_product_truebox_pilot_v1"
        target.mkdir()
        with pytest.raises(FileExistsError):
            build_truebox_dataset(e2_root=e2_root,
                                  truebox_manifest=_full_manifest(),
                                  target=target,
                                  protocol_dir=tmp_path / "p")

    def test_missing_photo_review_refused(self, e2_root, tmp_path):
        target = tmp_path / "e3_x"
        m = _full_manifest()[:-1]  # val 照片 9 缺审核记录
        with pytest.raises(RuntimeError, match="审核完成率"):
            build_truebox_dataset(e2_root=e2_root, truebox_manifest=m,
                                  target=target,
                                  protocol_dir=tmp_path / "p")
        assert not target.exists()  # fail-closed 不留半成品

    def test_unreviewed_prediction_refused(self, e2_root, tmp_path):
        target = tmp_path / "e3_x"
        m = _full_manifest()
        m[0]["review"]["status"] = "sam_prediction_only"
        with pytest.raises(RuntimeError, match="未审核"):
            build_truebox_dataset(e2_root=e2_root, truebox_manifest=m,
                                  target=target,
                                  protocol_dir=tmp_path / "p")

    def test_manual_review_without_final_decision_refused(self, e2_root,
                                                          tmp_path):
        target = tmp_path / "e3_x"
        m = _full_manifest()
        m[0]["quality_verdict"] = "manual_review"
        m[0]["review"]["final_quality_decision"] = None
        with pytest.raises(RuntimeError, match="manual_review"):
            build_truebox_dataset(e2_root=e2_root, truebox_manifest=m,
                                  target=target,
                                  protocol_dir=tmp_path / "p")

    def test_diagnostic_leak_refused_by_five_key_guard(self, e2_root,
                                                       tmp_path):
        proto = tmp_path / "protocol"
        proto.mkdir()
        diag_pid = "1"  # 与 split 中照片冲突 → 五键泄漏
        (proto / "diagnostic_v1.json").write_text(json.dumps({
            "frozen": True, "role": "diagnostic_v1",
            "photo_ids": [diag_pid], "sha256": [], "stores": [],
        }))
        with pytest.raises(RuntimeError, match="protocol-guard"):
            build_truebox_dataset(
                e2_root=e2_root, truebox_manifest=_full_manifest(),
                target=tmp_path / "e3_x", protocol_dir=proto)

    def test_train_val_store_overlap_refused(self, e2_root, tmp_path):
        target = tmp_path / "e3_x"
        proto = tmp_path / "p2"
        proto.mkdir()
        m = _full_manifest()
        m[-1]["store_canonical"] = m[0]["store_canonical"]  # val=train 门店
        with pytest.raises(RuntimeError, match="门店"):
            build_truebox_dataset(e2_root=e2_root, truebox_manifest=m,
                                  target=target, protocol_dir=proto)

    def test_empty_val_refused(self, e2_root, tmp_path):
        target = tmp_path / "e3_x"
        m = [e for e in _full_manifest() if e["split"] == "train"]
        with pytest.raises(RuntimeError):
            build_truebox_dataset(e2_root=e2_root, truebox_manifest=m,
                                  target=target,
                                  protocol_dir=tmp_path / "p")

    def test_missing_protocol_dir_refused(self, e2_root, tmp_path):
        with pytest.raises(FileNotFoundError):
            build_truebox_dataset(
                e2_root=e2_root, truebox_manifest=_full_manifest(),
                target=tmp_path / "e3_x",
                protocol_dir=tmp_path / "no_such_dir")

    def test_quality_distribution_disclosed(self, e2_root, tmp_path):
        target = tmp_path / "e3_x"
        proto = tmp_path / "proto"
        proto.mkdir()
        m = _full_manifest()
        m[1]["quality_verdict"] = "warn"
        audit = build_truebox_dataset(e2_root=e2_root, truebox_manifest=m,
                                      target=target, protocol_dir=proto)
        assert audit["quality_distribution"] == {"accept": 3, "warn": 1}
