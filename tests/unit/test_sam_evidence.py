"""SAM 证据链契约（手册§七）：完整字段、追加式保存、内容哈希、禁止覆盖。"""
import json

import numpy as np
import pytest

from src.sam_assist.evidence import EvidenceRecord, EvidenceStore, mask_sha256


def _full_record(**overrides):
    d = dict(
        photo_id="p1", image_sha256="a" * 64, instance_id="i1",
        original_point=(500.0, 800.0),
        prompts={"positive": [500.0, 800.0], "negatives": [], "coarse_box": [400, 600, 600, 1000],
                 "coarse_only": True, "config_version": "pc_v1"},
        model_id="sam2.1_hiera_small", checkpoint_sha256="b" * 64,
        code_commit="c" * 40, params={"multimask": True},
        candidates=[{"candidate_id": "c1", "mask_sha256": "d" * 64,
                     "iou_score": 0.9, "stability_score": 0.9,
                     "bbox": [480, 700, 520, 900], "reject_reasons": []}],
        selection_reason="highest_valid_score", rules_version="rules_v1",
        auto_box=(480.0, 700.0, 520.0, 900.0),
    )
    d.update(overrides)
    return EvidenceRecord(**d)


def test_record_requires_complete_fields():
    rec = _full_record()
    assert rec.photo_id == "p1"
    with pytest.raises(TypeError):
        EvidenceRecord(photo_id="p1")  # 缺字段必须报错，不得静默接受


def test_mask_sha256_deterministic():
    m = np.ones((10, 10), dtype=np.uint8)
    assert mask_sha256(m) == mask_sha256(m.copy())
    assert len(mask_sha256(m)) == 64
    m2 = np.zeros((10, 10), dtype=np.uint8)
    assert mask_sha256(m) != mask_sha256(m2)


def test_store_append_only_no_overwrite(tmp_path):
    store = EvidenceStore(tmp_path / "evidence.jsonl")
    store.append(_full_record())
    store.append(_full_record(instance_id="i2"))
    lines = (tmp_path / "evidence.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    ids = [json.loads(l)["instance_id"] for l in lines]
    assert ids == ["i1", "i2"]
    # 禁止提供覆盖/删除接口
    assert not hasattr(store, "overwrite")
    assert not hasattr(store, "delete")
    assert not hasattr(store, "replace")


def test_store_reappends_same_instance_keeps_history(tmp_path):
    """同一实例重跑不得覆盖历史，只允许追加新记录。"""
    store = EvidenceStore(tmp_path / "evidence.jsonl")
    store.append(_full_record())
    store.append(_full_record(params={"multimask": False}))
    lines = (tmp_path / "evidence.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["params"] == {"multimask": True}
    assert json.loads(lines[1])["params"] == {"multimask": False}


def test_each_record_has_timestamp_and_source_sha(tmp_path):
    store = EvidenceStore(tmp_path / "evidence.jsonl")
    store.append(_full_record())
    rec = json.loads((tmp_path / "evidence.jsonl").read_text(encoding="utf-8").strip())
    assert rec["timestamp"]
    assert rec["image_sha256"] == "a" * 64
    assert rec["checkpoint_sha256"] == "b" * 64
    assert rec["rules_version"] == "rules_v1"


def test_store_validates_image_sha_format(tmp_path):
    store = EvidenceStore(tmp_path / "evidence.jsonl")
    with pytest.raises(ValueError):
        store.append(_full_record(image_sha256="nothex"))
