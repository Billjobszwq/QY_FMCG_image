"""契约：KB 文件夹名 与 实景它模名 经别名注册表后必须 100% 可解析，
且指定的跨命名对同属一个 canonical。这是自动标记评测能否对齐的前提。"""
import json
import pathlib

import pytest

openpyxl = pytest.importorskip("openpyxl")

from src.catalog.alias_registry import build_registry

ROOT = pathlib.Path(__file__).resolve().parents[2]
INV = pathlib.Path("/tmp/sku_recon/inventory.json")
XLSX = ROOT / "training-data" / "raw" / "source-spreadsheets" / "实景照片.xlsx"
ALIAS = ROOT / "data" / "sku_aliases.json"


def _field_names():
    wb = openpyxl.load_workbook(str(XLSX), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(c).strip() if c else "" for c in rows[0]]
    i = header.index("name")
    names = [r[i] for r in rows[1:] if i < len(r) and r[i] not in (None, "")]
    return sorted(set(names))


def _kb_names():
    if INV.exists():
        return sorted(json.loads(INV.read_text(encoding="utf-8"))["skus"].keys())
    # SKU 文件夹是本地原始资产；源码树不再携带旧顶层业务目录。
    d = ROOT / "training-data" / "raw" / "initial-p1"
    return sorted(p.name for p in d.iterdir() if p.is_dir())


@pytest.fixture(scope="module")
def reg():
    return build_registry(_kb_names(), ALIAS, extra_names=_field_names())


def test_kb_full_coverage(reg):
    cov = reg.coverage(_kb_names())
    assert cov["unresolved"] == [], cov


def test_field_full_coverage(reg):
    cov = reg.coverage(_field_names())
    assert cov["unresolved"] == [], cov


@pytest.mark.parametrize(
    "field_name,kb_folder",
    [
        ("1250ml原味乌龙茶（无糖）", "乌龙茶无糖PET1250ML"),
        ("900ml原味乌龙茶（无糖）", "乌龙茶无糖PET900ML"),
        ("480ml利趣拿铁", "利趣拿铁PET480ML"),
        ("500ml麦茶", "植物茶麦茶500ML"),
        ("针叶楼桃味维C饮PET450ML", "针叶樱桃味维C饮PET450ML"),
    ],
)
def test_cross_style_same_canonical(reg, field_name, kb_folder):
    assert reg.resolve(field_name)[0] == reg.resolve(kb_folder)[0]


def test_orange_oolong_is_kb_missing(reg):
    cid, _method = reg.resolve("500ml橘皮乌龙（无糖）")
    assert reg.canonicals[cid].kb_missing is True


def test_canonical_counts(reg):
    with_kb = [c for c in reg.canonicals.values() if c.kb_folder]
    missing = [c for c in reg.canonicals.values() if c.kb_missing]
    assert len(with_kb) == 27
    assert [c.id for c in missing] == ["500ml橘皮乌龙（无糖）"]
