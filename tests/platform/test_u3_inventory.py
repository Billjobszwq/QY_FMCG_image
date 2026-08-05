"""U3-1 红测试：扫描手册 §5.1 全部照片来源（原始数，禁止相加冒充唯一数）。

手册 §5.1/§7：扫描全部 Excel、manifest、目录、URL 和历史数据集；
输出每个来源的原始数；不得把目录数量简单相加后宣称唯一照片总数。

当前平台没有来源扫描器，本测试必须 RED。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _mini_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    # manifest_photos_dict：photos 为 {photo_id: {...image.sha256/ok}}
    (root / "m1.json").write_text(json.dumps({
        "photos": {
            "p1": {"id": "p1", "image": {"ok": True, "sha256": "a" * 64}},
            "p2": {"id": "p2", "image": {"ok": True, "sha256": "b" * 64}},
            "p3": {"id": "p3", "image": {"ok": False}},
        }}, ensure_ascii=False), encoding="utf-8")
    # manifest_sha_dict：{photo_id: {sha256: ...}}
    (root / "m2.json").write_text(json.dumps({
        "q1": {"sha256": "c" * 64},
        "q2": {"sha256": "d" * 64}}, ensure_ascii=False), encoding="utf-8")
    # 目录来源
    d = root / "photos_dir"
    d.mkdir()
    (d / "1.jpg").write_bytes(b"x1")
    (d / "2.jpg").write_bytes(b"x2")
    (d / "note.txt").write_text("skip")
    return root


def test_scan_sources_counts_raw_and_sha(tmp_path):
    from src.platform.assets.inventory import scan_sources

    root = _mini_repo(tmp_path)
    report = scan_sources(root, sources=[
        {"source_id": "s1", "type": "manifest_photos_dict",
         "path": "m1.json"},
        {"source_id": "s2", "type": "manifest_sha_dict",
         "path": "m2.json"},
        {"source_id": "s3", "type": "directory", "path": "photos_dir"},
    ])
    by_id = {s["source_id"]: s for s in report["sources"]}
    assert by_id["s1"]["raw_count"] == 3
    assert by_id["s1"]["sha_present"] == 2, "ok=false 条目无 SHA"
    assert by_id["s1"]["download_failed"] == 1, "ok=false 计为下载失败"
    assert by_id["s2"]["raw_count"] == 2
    assert by_id["s2"]["sha_present"] == 2
    assert by_id["s3"]["raw_count"] == 2, "目录只计图片扩展名"
    assert report["total_raw"] == 7
    assert report["total_raw"] == sum(
        s["raw_count"] for s in report["sources"])


def test_scan_sources_missing_path_reported(tmp_path):
    from src.platform.assets.inventory import scan_sources

    root = _mini_repo(tmp_path)
    report = scan_sources(root, sources=[
        {"source_id": "gone", "type": "manifest_photos_dict",
         "path": "nope.json"},
    ])
    s = report["sources"][0]
    assert s["raw_count"] == 0
    assert s["missing"] is True, "缺失来源必须显式报告，不得静默吞掉"


@pytest.mark.parametrize("source_id,path,want", [
    ("batch1_manifest", ".training_data/manifest.json", 2947),
    ("batch2_manifest", ".eval/batch2/manifest.json", 6510),
    ("batch3_clean", ".batch3_clean/clean_manifest.json", 22659),
])
def test_real_repo_known_manifest_counts(source_id, path, want):
    """真实库只读核验：手册 §5.1 已核验数量必须精确复现。"""
    from src.platform.assets.inventory import DEFAULT_SOURCES, scan_sources

    pytest.importorskip("json")
    if not (REPO_ROOT / path).is_file():
        pytest.skip(f"{path} 不存在")
    report = scan_sources(REPO_ROOT, sources=[
        s for s in DEFAULT_SOURCES if s["source_id"] == source_id])
    s = report["sources"][0]
    assert s["raw_count"] == want, (source_id, s["raw_count"])
    assert s["sha_present"] == want, "batch1/2/3 manifest 每条必须带 SHA"


def test_real_repo_default_sources_cover_manual_5_1():
    """DEFAULT_SOURCES 必须覆盖手册 §5.1 的全部来源族。"""
    from src.platform.assets.inventory import DEFAULT_SOURCES

    ids = {s["source_id"] for s in DEFAULT_SOURCES}
    for need in ["batch1_manifest", "batch2_manifest",
                 "batch3_clean", "batch3_gray",
                 "photo1106", "photo1107", "pepsi_cola",
                 "p1_reference", "field_blobs", "bad_samples",
                 "protocols"]:
        assert need in ids, f"缺少来源 {need}"
