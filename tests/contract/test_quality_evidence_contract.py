"""质量证据链契约（手册§八）：每张图的判定必须含原图哈希、原始指标、
算法/阈值版本、触发规则与结论；原图必须内容寻址保留，派生物只是 derived。"""
import json

import numpy as np
import pytest

from src.data_quality.contracts import Finding
from src.data_quality.evidence import QualityEvidenceStore, original_blob_path


def test_original_blob_path_is_content_addressed():
    p = original_blob_path("ab" * 32)
    assert p.name == "ab" * 32
    assert p.parent.name == "ab"


def test_store_records_full_fields(tmp_path):
    store = QualityEvidenceStore(tmp_path / "quality.jsonl")
    store.record(
        image_sha256="c" * 64,
        verdict="warn",
        findings=[Finding(name="reflection", severity="weak", recoverable=True,
                          detail="roi_sat=0.21")],
        metrics={"laplacian": 55.0, "roi_sat": 0.21},
        policy_version="qpol_v1",
        analyzer_version="qa_v1",
        source_uri="oss://batch3/x.jpg",
    )
    rec = json.loads((tmp_path / "quality.jsonl").read_text(encoding="utf-8").strip())
    for k in ("image_sha256", "verdict", "findings", "metrics",
              "policy_version", "analyzer_version", "timestamp", "source_uri"):
        assert k in rec, f"缺少证据字段 {k}"
    assert rec["verdict"] == "warn"
    assert rec["findings"][0]["name"] == "reflection"


def test_store_append_only(tmp_path):
    store = QualityEvidenceStore(tmp_path / "quality.jsonl")
    store.record(image_sha256="c" * 64, verdict="accept", findings=[],
                 metrics={}, policy_version="qpol_v1", analyzer_version="qa_v1",
                 source_uri="")
    store.record(image_sha256="c" * 64, verdict="warn", findings=[],
                 metrics={}, policy_version="qpol_v2", analyzer_version="qa_v1",
                 source_uri="")
    lines = (tmp_path / "quality.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2, "重算只追加新证据，不改写历史"
    assert not hasattr(store, "delete")
    assert not hasattr(store, "overwrite")


def test_store_rejects_unknown_verdict(tmp_path):
    store = QualityEvidenceStore(tmp_path / "quality.jsonl")
    with pytest.raises(ValueError):
        store.record(image_sha256="c" * 64, verdict="discard", findings=[],
                     metrics={}, policy_version="qpol_v1", analyzer_version="qa_v1",
                     source_uri="")
