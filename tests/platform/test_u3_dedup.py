"""U3-3 红测试：SHA 精确去重 + pHash 近重复分组。

手册 §5.2/§7/指令：使用 SHA 精确去重和 pHash/embedding 近重复分组；
保留所有 source reference（去重只产出分组，不删台账行）；输出原始数、
SHA 唯一数、近重复组数、下载失败数。

当前平台没有去重模块，本测试必须 RED。
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def store(tmp_path: Path):
    from src.platform.data.store import PlatformStore

    s = PlatformStore(tmp_path / "p.sqlite")
    yield s
    s.close()


def _img(seed: int, size=(64, 64)):
    """生成确定性测试图像。"""
    import numpy as np
    from PIL import Image

    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, (*size, 3), dtype=np.uint8)
    return Image.fromarray(arr)


def _seed_ledger(store, tmp_path: Path):
    """3 条同 SHA（跨 3 来源）+ 1 条异 SHA + 2 张本地目录照片。"""
    store.register_inventory_asset(
        source_id="batch1_manifest", source_type="manifest_photos_dict",
        source_uri="m1.json#p1", photo_id="p1", sha256="a" * 64)
    store.register_inventory_asset(
        source_id="batch2_manifest", source_type="manifest_photos_dict",
        source_uri="m2.json#p1", photo_id="p1", sha256="a" * 64)
    store.register_inventory_asset(
        source_id="protocols", source_type="protocol_dir",
        source_uri="proto.json#p1", photo_id="p1", sha256="a" * 64)
    store.register_inventory_asset(
        source_id="batch3_clean", source_type="manifest_sha_dict",
        source_uri="m3.json#q1", photo_id="q1", sha256="b" * 64)
    d = tmp_path / "照片X"
    d.mkdir(exist_ok=True)
    _img(1).save(d / "1.jpg")
    _img(2).save(d / "2.jpg")
    import hashlib
    for name in ("1.jpg", "2.jpg"):
        sha = hashlib.sha256((d / name).read_bytes()).hexdigest()
        store.register_inventory_asset(
            source_id="photoX", source_type="directory",
            source_uri=f"照片X/{name}", photo_id=name, sha256=sha)


class TestShaDedupe:
    def test_unique_sha_count(self, store, tmp_path):
        from src.platform.assets.dedup import sha_dedupe

        _seed_ledger(store, tmp_path)
        rep = sha_dedupe(store)
        # 6 条台账（4 manifest + 2 本地照片）；3 条同 SHA → 唯一 = 6-3+1 = 4
        assert rep["total_refs"] == 6
        assert rep["unique_sha"] == 4
        assert rep["exact_dup_groups"] == 1, "只有 a*64 是跨来源重复"

    def test_dup_group_keeps_all_source_refs(self, store, tmp_path):
        from src.platform.assets.dedup import sha_dedupe

        _seed_ledger(store, tmp_path)
        rep = sha_dedupe(store)
        grp = [g for g in rep["groups"] if g["sha256"] == "a" * 64][0]
        assert grp["count"] == 3
        srcs = {m["source_id"] for m in grp["members"]}
        assert srcs == {"batch1_manifest", "batch2_manifest", "protocols"}
        assert store.count_inventory_assets() == 6, "去重不得删除台账行"


class TestPHash:
    def test_near_identical_grouped(self, store, tmp_path):
        """同一图轻微亮度扰动 → 近重复同组。"""
        from PIL import ImageEnhance

        from src.platform.assets.dedup import group_near_duplicates

        d = tmp_path / "照片X"
        d.mkdir(exist_ok=True)
        base = _img(7, (128, 128))
        base.save(d / "a.jpg")
        ImageEnhance.Brightness(base).enhance(1.05).save(d / "a2.jpg")
        _img(99, (128, 128)).save(d / "zz.jpg")
        import hashlib
        for name in ("a.jpg", "a2.jpg", "zz.jpg"):
            sha = hashlib.sha256((d / name).read_bytes()).hexdigest()
            store.register_inventory_asset(
                source_id="photoX", source_type="directory",
                source_uri=f"照片X/{name}", photo_id=name, sha256=sha)
        rep = group_near_duplicates(store, tmp_path)
        assert rep["scanned"] == 3
        by_uri = {}
        for g in rep["groups"]:
            for m in g["members"]:
                by_uri[m["source_uri"]] = g["group_id"]
        assert by_uri["照片X/a.jpg"] == by_uri["照片X/a2.jpg"]
        assert by_uri["照片X/zz.jpg"] not in (
            by_uri["照片X/a.jpg"],)

    def test_sha_exact_dup_not_double_grouped(self, store, tmp_path):
        """同 SHA 的两条本地引用（同一文件两个来源）不重复进近重复组。"""
        from src.platform.assets.dedup import group_near_duplicates

        d = tmp_path / "照片X"
        d.mkdir(exist_ok=True)
        _img(5).save(d / "s.jpg")
        import hashlib
        sha = hashlib.sha256((d / "s.jpg").read_bytes()).hexdigest()
        store.register_inventory_asset(
            source_id="photoX", source_type="directory",
            source_uri="照片X/s.jpg", photo_id="s.jpg", sha256=sha)
        store.register_inventory_asset(
            source_id="photoX_copy", source_type="directory",
            source_uri="照片X/s.jpg", photo_id="s.jpg", sha256=sha)
        rep = group_near_duplicates(store, tmp_path)
        assert rep["scanned"] == 1, "按唯一文件扫描，不按台账行扫描"


class TestDedupReport:
    def test_report_fields_and_conservation(self, store, tmp_path):
        from src.platform.assets.dedup import build_dedup_report

        _seed_ledger(store, tmp_path)
        rep = build_dedup_report(store, tmp_path)
        for k in ("raw_refs", "unique_sha", "exact_dup_groups",
                  "near_dup_groups", "download_failed"):
            assert k in rep, f"缺少报告字段 {k}"
        assert rep["raw_refs"] == 6
        assert rep["unique_sha"] == 4
        assert rep["download_failed"] == 0
        assert rep["note"], "必须声明唯一数口径，禁止目录相加冒充唯一数"
