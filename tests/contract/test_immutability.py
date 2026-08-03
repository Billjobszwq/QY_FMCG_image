import pytest
from pathlib import Path
from src.common import paths
from src.common.config import PROJECT_ROOT, get_settings

def test_refuse_reference_dir():
    with pytest.raises(PermissionError): paths.assert_writable(PROJECT_ROOT / "搭建初期P1" / "x" / "y.jpg")

def test_refuse_xlsx():
    with pytest.raises(PermissionError): paths.assert_writable(Path(get_settings().field_xlsx))

def test_refuse_field_blobs_manifest():
    with pytest.raises(PermissionError): paths.assert_writable(PROJECT_ROOT / ".field" / "blobs" / "ab" / "x")
    with pytest.raises(PermissionError): paths.assert_writable(PROJECT_ROOT / ".field" / "manifest.json")

def test_allow_derived():
    for p in [PROJECT_ROOT / ".kb" / "s.json", PROJECT_ROOT / ".labels" / "i.txt", PROJECT_ROOT / ".warehouse" / "db.sqlite", PROJECT_ROOT / ".field" / "eval_report.json"]:
        assert paths.assert_writable(p) == p.resolve()

def test_safe_write_blocks(tmp_path, monkeypatch):
    ro = tmp_path / "prot"; ro.mkdir(); monkeypatch.setattr(paths, "readonly_sources", lambda: [ro]); t = ro / "z.txt"
    with pytest.raises(PermissionError): paths.safe_write_text(t, "x")
    assert not t.exists()
