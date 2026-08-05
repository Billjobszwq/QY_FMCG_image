"""U3-2 红测试：不可变 source_asset_inventory_v1（追加式，原图不动）。

手册 §5.2/§7：所有源照片进入不可变台账；所有登记为追加式；
保留全部 source reference；不得移动、覆盖、删除原文件；数量守恒。

当前平台没有 source_asset_inventory_v1 表与登记方法，本测试必须 RED。
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


def _reg(**kw):
    base = dict(
        source_id="photo1106", source_type="file",
        source_uri="照片1106/1.jpg", photo_id="p1",
        sha256="a" * 64)
    base.update(kw)
    return base


class TestInventoryLedger:
    def test_register_creates_row(self, store):
        row = store.register_inventory_asset(**_reg())
        assert row["asset_id"]
        assert row["source_id"] == "photo1106"
        assert row["sha256"] == "a" * 64
        assert row["registered_at"]

    def test_register_is_idempotent_per_source_ref(self, store):
        """同一 (source_id, source_uri) 重复登记：幂等返回同一 asset。"""
        r1 = store.register_inventory_asset(**_reg())
        r2 = store.register_inventory_asset(**_reg())
        assert r1["asset_id"] == r2["asset_id"]
        assert store.count_inventory_assets() == 1

    def test_same_sha_different_source_kept_both(self, store):
        """同 SHA 不同来源必须各自保留 source reference（去重在 U3-3）。"""
        store.register_inventory_asset(**_reg())
        store.register_inventory_asset(
            **_reg(source_id="batch1_manifest",
                   source_uri=".training_data/manifest.json#p1",
                   source_type="manifest"))
        assert store.count_inventory_assets() == 2

    def test_delete_and_update_forbidden(self, store):
        """不可变：禁止 DELETE/UPDATE 台账行。"""
        store.register_inventory_asset(**_reg())
        with pytest.raises(Exception):
            store._conn.execute(
                "DELETE FROM source_asset_inventory_v1").fetchall()
            raise AssertionError("不应到达此处")
        # 通过触发器拒绝
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute(
                "UPDATE source_asset_inventory_v1 SET sha256='x'")

    def test_list_and_count_with_source_filter(self, store):
        store.register_inventory_asset(**_reg())
        store.register_inventory_asset(
            **_reg(photo_id="p2", sha256="b" * 64,
                   source_uri="照片1106/2.jpg"))
        store.register_inventory_asset(
            **_reg(source_id="batch1_manifest", source_type="manifest",
                   photo_id="p3", sha256="c" * 64,
                   source_uri="m.json#p3"))
        assert store.count_inventory_assets() == 3
        assert store.count_inventory_assets(source_id="photo1106") == 2
        rows = store.list_inventory_assets(
            source_id="photo1106", limit=1, offset=1)
        assert len(rows) == 1


class TestLedgerBuildConservation:
    def test_build_ledger_from_scan_conserves_raw(self, tmp_path, monkeypatch):
        """从扫描结果建账：台账行数 == total_raw（数量守恒）。"""
        import json

        from src.platform.assets.inventory import scan_sources
        from src.platform.assets.ledger import build_ledger_from_scan
        from src.platform.data.store import PlatformStore

        root = tmp_path / "repo"
        (root / "照片A").mkdir(parents=True)
        (root / "照片A" / "1.jpg").write_bytes(b"hello-1")
        (root / "照片A" / "2.jpg").write_bytes(b"hello-2")
        (root / "m.json").write_text(json.dumps({
            "q1": {"sha256": "c" * 64, "filename": "q1.jpg"}},
            ensure_ascii=False), encoding="utf-8")
        sources = [
            {"source_id": "dirA", "type": "directory", "path": "照片A"},
            {"source_id": "m1", "type": "manifest_sha_dict",
             "path": "m.json"},
        ]
        report = scan_sources(root, sources=sources)
        assert report["total_raw"] == 3
        s = PlatformStore(tmp_path / "p.sqlite")
        try:
            n = build_ledger_from_scan(s, root, sources=sources)
            assert n == 3 == s.count_inventory_assets()
            # 目录文件登记必须带真实 SHA（非空且长度 64）
            rows = s.list_inventory_assets(source_id="dirA", limit=10)
            assert all(len(r["sha256"]) == 64 for r in rows)
            # 重跑幂等：不新增
            n2 = build_ledger_from_scan(s, root, sources=sources)
            assert n2 == 0 and s.count_inventory_assets() == 3
        finally:
            s.close()
