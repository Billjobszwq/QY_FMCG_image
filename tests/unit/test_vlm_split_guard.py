"""VLM-008：训练/验证划分防泄漏守卫（fail-closed）。

红线（禁止随机 9:1 划分）：同一 SHA / near_dup_group / customer / store /
session / package_version 不得跨 split 出现；frozen 与 active protocol
样本不得进入 train。
"""

from __future__ import annotations

import pytest

from src.training.vlm.split_guard import SplitLeakageError, validate_splits


def _groups(**over) -> dict:
    g = {"customer": "c1", "store": "st1", "session": "ss1",
         "near_dup_group": "nd1", "package_version": "pv1"}
    g.update(over)
    return g


def _record(split: str = "train", *, sha: str = "sha-a", groups: dict | None = None,
            frozen: bool = False, active_protocol: bool = False,
            sid: str = "x") -> dict:
    return {"sample_id": sid, "split": split, "sha256": sha,
            "split_group": groups if groups is not None else _groups(),
            "frozen": frozen, "active_protocol": active_protocol}


_OTHER = dict(customer="c9", store="st9", session="ss9",
              near_dup_group="nd9", package_version="pv9")


def manifest_with_overlap(key: str) -> list[dict]:
    if key == "sha256":
        return [_record("train", sha="same", sid="a"),
                _record("val", sha="same", groups=_groups(**_OTHER), sid="b")]
    g_a = _groups()
    g_a[key] = "same"
    g_b = _groups(**_OTHER)
    g_b[key] = "same"
    return [_record("train", groups=g_a, sid="a"),
            _record("val", groups=g_b, sid="b")]


@pytest.mark.parametrize("key", [
    "sha256", "near_dup_group", "customer", "store", "session",
    "package_version",
])
def test_group_overlap_rejected(key) -> None:
    with pytest.raises(SplitLeakageError):
        validate_splits(manifest_with_overlap(key))


def test_clean_manifest_passes() -> None:
    records = [_record("train", sid="a"),
               _record("val", sha="sha-b", groups=_groups(**_OTHER), sid="b")]
    validate_splits(records)  # 不抛错


def test_same_group_within_same_split_ok() -> None:
    records = [_record("train", sha="sha-a", sid="a"),
               _record("train", sha="sha-b", groups=_groups(), sid="b")]
    validate_splits(records)


def test_frozen_record_in_train_rejected() -> None:
    with pytest.raises(SplitLeakageError):
        validate_splits([_record("train", frozen=True, sid="a")])


def test_active_protocol_in_train_rejected() -> None:
    with pytest.raises(SplitLeakageError):
        validate_splits([_record("train", active_protocol=True, sid="a")])


def test_frozen_in_holdout_allowed() -> None:
    validate_splits([_record("holdout", frozen=True, sid="a")])
    validate_splits([_record("val", active_protocol=True, sid="a")])


def test_error_lists_violations() -> None:
    with pytest.raises(SplitLeakageError) as ei:
        validate_splits(manifest_with_overlap("customer"))
    assert ei.value.violations  # 可审计的违规清单
