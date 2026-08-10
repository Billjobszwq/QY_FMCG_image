"""Forbidden Identity Index TDD：同源识别与 fail-closed 排除。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.data_governance.forbidden_identity_index import (
    IdentityRecord,
    check_candidate,
    parse_cropped_identity,
)


def test_same_photo_different_sha_rejected():
    """同 photo_id、不同 crop SHA → 命中排除。"""
    idx = {"photo_ids": {"P1"}, "shas": set(), "groups": set(),
           "store_sessions": set(), "symlink_targets": set()}
    cand = IdentityRecord(photo_id="P1", sha="a" * 64, group="G9",
                          store=None, session=None, symlink_target=None)
    res = check_candidate(cand, idx)
    assert res["excluded"] and res["reason"] == "photo_id_hit"


def test_same_group_different_crop_rejected():
    idx = {"photo_ids": set(), "shas": set(), "groups": {"G1"},
           "store_sessions": set(), "symlink_targets": set()}
    cand = IdentityRecord(photo_id="P2", sha="b" * 64, group="G1",
                          store=None, session=None, symlink_target=None)
    res = check_candidate(cand, idx)
    assert res["excluded"] and res["reason"] == "leakage_group_hit"


def test_store_session_alias_rejected():
    idx = {"photo_ids": set(), "shas": set(), "groups": set(),
           "store_sessions": {"st1@20260601"}, "symlink_targets": set()}
    cand = IdentityRecord(photo_id="P3", sha="c" * 64, group="G3",
                          store="ST1", session="20260601",
                          symlink_target=None)
    res = check_candidate(cand, idx)
    assert res["excluded"] and res["reason"] == "store_session_hit"


def test_symlink_target_rejected():
    idx = {"photo_ids": set(), "shas": set(), "groups": set(),
           "store_sessions": set(), "symlink_targets": {"T1"}}
    cand = IdentityRecord(photo_id="P4", sha="d" * 64, group="G4",
                          store=None, session=None, symlink_target="T1")
    res = check_candidate(cand, idx)
    assert res["excluded"] and res["reason"] == "symlink_target_hit"


def test_unresolved_identity_rejected():
    idx = {"photo_ids": set(), "shas": set(), "groups": set(),
           "store_sessions": set(), "symlink_targets": set()}
    cand = IdentityRecord(photo_id=None, sha="e" * 64, group=None,
                          store=None, session=None, symlink_target=None)
    res = check_candidate(cand, idx)
    assert res["excluded"] and res["reason"] == "identity_unresolved"


def test_clean_candidate_passes():
    idx = {"photo_ids": {"P1"}, "shas": {"s1"}, "groups": {"G1"},
           "store_sessions": {"x@y"}, "symlink_targets": {"T1"}}
    cand = IdentityRecord(photo_id="P9", sha="f" * 64, group="G9",
                          store="S9", session="20260101",
                          symlink_target="T9")
    res = check_candidate(cand, idx)
    assert not res["excluded"]


def test_parse_cropped_identity_fields():
    name = ("01058c2e__6e382c76-百事PC_朱兆岩家家乐超市_百事_"
            "IR百事冰柜1_20250625152308881_hc0022_29_"
            "25-百事可乐-美橙600ml_0.jpg")
    rec = parse_cropped_identity(name)
    assert rec["group"].startswith("6e382c76")
    assert "家家乐超市" in rec["store"]
    assert rec["session"] == "20250625"
    assert rec["source_batch"] == "cropped_images"
