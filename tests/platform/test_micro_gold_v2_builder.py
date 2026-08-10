"""Micro-Gold V2 builder TDD（纯函数层）。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location(
    "mgv2", Path("scripts/build_micro_gold_v2.py"))
mgv2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mgv2)


def _cand(photo, stratum, sku="A", conf=0.9):
    return {"photo": photo, "stratum": stratum,
            "provisional_sku": sku, "conf": conf,
            "bbox": [0, 0, 10, 10], "quality": {"reasons": []}}


def test_one_region_per_photo_and_cross_stratum_exclusive():
    cands = [_cand("p1", "canonical", "A"), _cand("p1", "hard"),
             _cand("p2", "canonical", "A"), _cand("p3", "canonical", "A"),
             _cand("p4", "canonical", "A")]
    out = mgv2.sample_strata(cands, {"canonical": 3, "hard": 1,
                                     "pending": 0, "negative": 0})
    photos = [c["photo"] for lst in out.values() for c in lst]
    assert len(photos) == len(set(photos))


def test_canonical_per_class_minimum_groups():
    cands = [_cand(f"p{i}", "canonical", "A") for i in range(5)] + \
            [_cand(f"q{i}", "canonical", "B") for i in range(5)]
    out = mgv2.sample_strata(cands, {"canonical": 6, "hard": 0,
                                     "pending": 0, "negative": 0})
    na = sum(1 for c in out["canonical"] if c["provisional_sku"] == "A")
    nb = sum(1 for c in out["canonical"] if c["provisional_sku"] == "B")
    assert na >= 3 and nb >= 3


def test_insufficient_fail_closed_no_padding():
    cands = [_cand(f"p{i}", "canonical", "A") for i in range(2)]
    out = mgv2.sample_strata(cands, {"canonical": 120, "hard": 0,
                                     "pending": 0, "negative": 0})
    assert len(out["canonical"]) == 2  # 不凑数


def test_quality_metrics_reasons():
    dark = np.full((50, 50, 3), 30, np.uint8)
    q = mgv2.quality_metrics(dark, 0.005)
    assert "low_light" in q["reasons"] and "tiny_object" in q["reasons"]
    bright = np.full((50, 50, 3), 250, np.uint8)
    q2 = mgv2.quality_metrics(bright, 0.05)
    assert "reflection" in q2["reasons"] or "over_exposure" in q2["reasons"]
