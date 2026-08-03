import json
import pathlib
import tempfile

import pytest

from src.catalog.alias_registry import build_registry


def _write(data):
    p = pathlib.Path(tempfile.mkdtemp()) / "a.json"
    p.write_text(json.dumps({"canonicals": data}), encoding="utf-8")
    return p


def test_exact_and_alias_resolve_to_same_canonical():
    p = _write([{"kb_folder": "乌龙茶无糖PET1250ML", "aliases": ["1250ml原味乌龙茶（无糖）"]}])
    reg = build_registry(["乌龙茶无糖PET1250ML", "500ml茉莉乌龙（无糖）"], p)
    assert reg.resolve("乌龙茶无糖PET1250ML")[0] == "乌龙茶无糖PET1250ML"
    assert reg.resolve("1250ml原味乌龙茶（无糖）")[0] == "乌龙茶无糖PET1250ML"
    assert reg.resolve("500ml茉莉乌龙（无糖）")[0] == "500ml茉莉乌龙（无糖）"


def test_unknown_returns_none_without_extra():
    p = _write([])
    reg = build_registry(["X"], p)
    assert reg.resolve("完全不存在的名字") is None


def test_alias_conflict_raises():
    p = _write([{"kb_folder": "A", "aliases": ["Z"]}, {"kb_folder": "B", "aliases": ["Z"]}])
    with pytest.raises(ValueError):
        build_registry(["A", "B"], p)


def test_kb_missing_placeholder_via_extra():
    p = _write([])
    reg = build_registry(["A"], p, extra_names=["新品Z"])
    cid, _method = reg.resolve("新品Z")
    assert cid == "新品Z"
    assert reg.canonicals["新品Z"].kb_missing is True
