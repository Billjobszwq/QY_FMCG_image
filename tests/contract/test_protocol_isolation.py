"""数据协议零泄漏 fail-closed 回归测试（RA-002/RA-008 复核修订）。

有效冻结集（gold_v2/dev/calibration/diagnostic）任何照片/SHA 交集必须终止构建；
legacy 集仅报告不阻断。"""
import json
import pytest

from src.training import build_sku_v6_dataset as BV


@pytest.fixture
def proto_dir(tmp_path, monkeypatch):
    d = tmp_path / "protocol"
    d.mkdir()
    monkeypatch.setattr(BV, "PROTOCOL_DIR", d)
    return d


def _write_set(d, name, ids, shas, role=None):
    rec = {"frozen": True, "photo_ids": list(ids), "sha256": list(shas)}
    if role:
        rec["role"] = role
    (d / name).write_text(json.dumps(rec), encoding="utf-8")


def test_active_set_id_leak_fail_closed(proto_dir):
    _write_set(proto_dir, "gold_v2.json", ["p1", "p2"], ["sha-a"])
    with pytest.raises(RuntimeError, match="泄漏"):
        BV._protocol_no_leak(["p1", "p9"], ["sha-x"], "unit-test")


def test_active_set_sha_leak_fail_closed(proto_dir):
    _write_set(proto_dir, "dev_v1.json", ["p1"], ["sha-a"])
    with pytest.raises(RuntimeError, match="泄漏"):
        BV._protocol_no_leak(["p9"], ["sha-a"], "unit-test")


def test_legacy_set_report_only(proto_dir, capsys):
    _write_set(proto_dir, "gold_holdout.json", ["p1"], ["sha-a"],
               role="legacy_regression_v1")
    # 不得抛异常，仅报告
    BV._protocol_no_leak(["p1"], ["sha-a"], "unit-test")
    out = capsys.readouterr().out
    assert "legacy" in out


def test_disjoint_passes(proto_dir):
    _write_set(proto_dir, "gold_v2.json", ["p1"], ["sha-a"])
    _write_set(proto_dir, "calibration_v1.json", ["p2"], ["sha-b"])
    BV._protocol_no_leak(["p9"], ["sha-z"], "unit-test")


def test_non_frozen_file_ignored(proto_dir):
    (proto_dir / "draft.json").write_text(json.dumps({"frozen": False,
                                                      "photo_ids": ["p1"]}), encoding="utf-8")
    BV._protocol_no_leak(["p1"], None, "unit-test")
