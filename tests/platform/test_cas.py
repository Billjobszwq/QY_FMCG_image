"""W8 Asset/CAS TDD：内容寻址、去重、读取校验、数据库只存哈希/lineage、原图不动。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.platform.assets.cas import CASIntegrityError, ContentAddressedStore
from src.platform.data.store import PlatformStore


@pytest.fixture()
def store(tmp_path: Path) -> PlatformStore:
    s = PlatformStore(tmp_path / "platform.sqlite")
    yield s
    s.close()


@pytest.fixture()
def cas(tmp_path: Path, store: PlatformStore) -> ContentAddressedStore:
    return ContentAddressedStore(tmp_path / "cas", store)


def test_put_get_roundtrip(cas: ContentAddressedStore) -> None:
    data = b"hello fmcg"
    ref = cas.put(data, kind="photo", media_type="image/jpeg")
    assert ref.sha256 == hashlib.sha256(data).hexdigest()
    assert ref.size_bytes == len(data)
    assert cas.get(ref.sha256) == data


def test_dedup_same_content(cas: ContentAddressedStore, tmp_path: Path) -> None:
    data = b"same" * 10
    r1 = cas.put(data, kind="photo")
    r2 = cas.put(data, kind="photo")
    assert r1.sha256 == r2.sha256
    blobs = list((tmp_path / "cas").rglob("*"))
    files = [p for p in blobs if p.is_file()]
    assert len(files) == 1, "相同内容只存一份"


def test_corruption_detected(cas: ContentAddressedStore, tmp_path: Path) -> None:
    data = b"important evidence"
    ref = cas.put(data, kind="evidence")
    blob = tmp_path / "cas" / ref.sha256[:2] / ref.sha256
    blob.write_bytes(b"X" + data[1:])  # 模拟磁盘损坏
    with pytest.raises(CASIntegrityError):
        cas.get(ref.sha256)


def test_missing_blob_raises(cas: ContentAddressedStore) -> None:
    with pytest.raises(CASIntegrityError):
        cas.get("0" * 64)


def test_asset_row_recorded(cas: ContentAddressedStore, store: PlatformStore) -> None:
    ref = cas.put(b"abc", kind="crop", media_type="image/png")
    row = store._conn.execute(
        "SELECT * FROM asset WHERE sha256=?", (ref.sha256,)
    ).fetchone()
    assert row is not None
    assert row["kind"] == "crop"
    assert row["size_bytes"] == 3


def test_put_does_not_touch_original(tmp_path: Path, store: PlatformStore) -> None:
    original = tmp_path / "original.jpg"
    original.write_bytes(b"ORIGINAL-DO-NOT-TOUCH")
    before = original.read_bytes()
    cas = ContentAddressedStore(tmp_path / "cas", store)
    cas.put(original.read_bytes(), kind="photo")
    assert original.read_bytes() == before, "原图不得被修改/移动/覆盖"


def test_ref_is_contract_assetref(cas: ContentAddressedStore) -> None:
    from src.platform.contracts import AssetRef

    ref = cas.put(b"xyz", kind="photo")
    assert isinstance(ref, AssetRef)
