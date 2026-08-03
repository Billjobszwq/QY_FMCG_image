"""G2 五键零泄漏守卫契约测试：photo ID / SHA / 规范门店 / 模糊别名 / session。

active 冻结集任何键交集非零必须抛 RuntimeError；legacy 与被取代集
（supersedes 声明）仅报告不阻断。"""
import json

import pytest

from src.data import protocol_guard as PG
from src.data.store_norm import norm_store

CLEAN = {
    "1": {"filename": "连锁_门店甲_货架_20260730_张三_1.jpg"},
    "2": {"filename": "连锁_门店乙_货架_20260731_李四_1.jpg"},
}


def _write_set(d, name, **rec):
    rec.setdefault("frozen", True)
    (d / name).write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


def _guard(d, photo_ids=None, shas=None, stores=None, sessions=None):
    return PG.check_no_leak(photo_ids or [], shas or [], stores or [],
                            sessions or [], CLEAN, d, "unit-test")


def test_photo_id_leak_fail_closed(tmp_path):
    _write_set(tmp_path, "gold_v2.json", role="gold", photo_ids=["1"],
               stores=["门店丙"], sessions=["x@20260101"])
    with pytest.raises(RuntimeError, match="零泄漏失败"):
        _guard(tmp_path, photo_ids=["1"])


def test_sha_leak_fail_closed(tmp_path):
    _write_set(tmp_path, "calibration_v1.json", role="calibration", photo_ids=["9"],
               sha256=["sha-a"], stores=["门店丙"], sessions=["x@20260101"])
    with pytest.raises(RuntimeError, match="零泄漏失败"):
        _guard(tmp_path, photo_ids=["8"], shas=["sha-a"])


def test_store_alias_leak_fail_closed(tmp_path):
    """G4 核心：全半角括号别名必须视为同一门店并阻断。"""
    _write_set(tmp_path, "dev_v1.json", role="dev", photo_ids=["9"],
               stores=["何惠晴(上海如海)"], sessions=["x@20260101"])
    with pytest.raises(RuntimeError, match="零泄漏失败"):
        _guard(tmp_path, photo_ids=["8"], stores=["何惠晴（上海如海）"])


def test_session_leak_fail_closed(tmp_path):
    _write_set(tmp_path, "diagnostic_v1.json", role="diagnostic", photo_ids=["9"],
               stores=["门店丙"], sessions=[f"{norm_store('门店甲')}@20260730"])
    with pytest.raises(RuntimeError, match="零泄漏失败"):
        _guard(tmp_path, photo_ids=["8"],
               sessions=[f"{norm_store('门店甲')}@20260730"])


def test_legacy_set_report_only(tmp_path, capsys):
    _write_set(tmp_path, "gold_holdout.json", role="legacy_regression_v1",
               photo_ids=["1"], sha256=["sha-a"])
    rep = _guard(tmp_path, photo_ids=["1"], shas=["sha-a"])
    assert rep["gold_holdout"]["enforced"] is False
    assert rep["gold_holdout"]["hits"]["photo_id"] == 1
    assert "仅报告" in capsys.readouterr().out


def test_superseded_set_report_only(tmp_path):
    """dev_v2 声明 supersedes=dev_v1 后，dev_v1 降为仅报告。"""
    _write_set(tmp_path, "dev_v1.json", role="dev", photo_ids=["1"],
               stores=["门店甲"], sessions=["s@20260730"])
    _write_set(tmp_path, "dev_v2.json", role="dev", photo_ids=["2"],
               stores=["门店乙"], sessions=["s2@20260731"], supersedes="dev_v1")
    # dev_v1 的门店泄漏不阻断（被取代），dev_v2 仍 fail-closed
    rep = _guard(tmp_path, photo_ids=["8"], stores=["门店甲"])
    assert rep["dev_v1"]["enforced"] is False
    assert rep["dev_v2"]["enforced"] is True
    with pytest.raises(RuntimeError, match="零泄漏失败"):
        _guard(tmp_path, photo_ids=["8"], stores=["门店乙"])


def test_disjoint_passes_with_report(tmp_path):
    _write_set(tmp_path, "gold_v2.json", role="gold", photo_ids=["1"],
               stores=["门店丙"], sessions=["x@20260101"])
    rep = _guard(tmp_path, photo_ids=["8"], shas=["sha-z"],
                 stores=["门店丁"], sessions=["y@20260202"])
    assert all(v == 0 for v in rep["gold_v2"]["hits"].values())


def test_non_frozen_file_ignored(tmp_path):
    _write_set(tmp_path, "draft.json", frozen=False, photo_ids=["1"])
    rep = _guard(tmp_path, photo_ids=["1"])
    assert "draft" not in rep


def test_derived_keys_from_old_format(tmp_path):
    """旧格式协议集（无内嵌 stores/sessions）必须从 clean_manifest 推导五键。"""
    _write_set(tmp_path, "old_set.json", role="gold", photo_ids=["1"])
    with pytest.raises(RuntimeError, match="零泄漏失败"):
        _guard(tmp_path, photo_ids=["8"], stores=["门店甲"])
