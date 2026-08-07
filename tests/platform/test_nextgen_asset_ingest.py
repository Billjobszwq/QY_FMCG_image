"""N2 Task 3：三批资产接入与去重契约（小样例 + 真实对账投影）。

- 合成样例验证 canonical 规则（批2 优先/批1 补独有/批3 独立/差异 ledger）；
- 真实计数经 reports/nextgen_v2/data_scope_reconciliation.json 对账。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.modules.nextgen_data.ingest import (
    AssetScopeError,
    build_asset_scope,
    canonical_points,
)

ROOT = Path(__file__).resolve().parents[2]


def _photo(pid, sha, anns):
    return {"id": pid, "image": {"sha256": sha},
            "annotations": [{"x": x, "y": y, "name": n}
                             for x, y, n in anns]}


class TestCanonicalRules:
    def test_batch2_priority_and_batch1_unique(self):
        b1 = [_photo("p1", "shaA", [(1, 2, "S1")]),
              _photo("p2", "shaB", [(3, 4, "S2")])]          # p2 独有
        b2 = [_photo("q1", "shaA", [(1, 2, "S1"), (5, 6, "S3")])]  # 覆盖 shaA
        b3 = [_photo("r1", "shaC", [(7, 8, "S4")])]
        scope = build_asset_scope(batches={"batch1": b1, "batch2": b2,
                                           "batch3": b3})
        assert scope["exact_unique"] == 3
        canon = scope["canonical_photos"]
        # shaA 用批2 版本（2 点），shaB 批1 独有，shaC 批3
        assert canon["shaA"]["source_batch"] == "batch2"
        assert len(canon["shaA"]["points"]) == 2
        assert canon["shaB"]["source_batch"] == "batch1"
        assert canon["shaC"]["source_batch"] == "batch3"
        cp = canonical_points(scope)
        assert cp == 2 + 1 + 1

    def test_discrepancy_ledger_written(self):
        b1 = [_photo("p1", "shaA", [(1, 2, "S1")])]
        b2 = [_photo("q1", "shaA", [(1, 2, "S1"), (9, 9, "S9")])]
        scope = build_asset_scope(batches={"batch1": b1, "batch2": b2})
        assert len(scope["coordinate_discrepancies"]) == 1
        d = scope["coordinate_discrepancies"][0]
        assert d["batch1_points"] == 1 and d["batch2_points"] == 2
        assert d["canonical_choice"] == "batch2"

    def test_missing_sha_fail_closed(self):
        b1 = [{"id": "p1", "image": {}, "annotations": []}]
        with pytest.raises(AssetScopeError):
            build_asset_scope(batches={"batch1": b1})


class TestRealReconciliation:
    """真实三批对账结果（脚本生成，测试断言任务书预期）。"""

    @pytest.fixture()
    def report(self):
        p = ROOT / "reports/nextgen_v2/data_scope_reconciliation.json"
        if not p.exists():
            pytest.skip("对账报告未生成（scripts/reconcile_nextgen_data_scope.py）")
        return json.loads(p.read_text(encoding="utf-8"))

    def test_canonical_points_exact(self, report):
        assert report["canonical_points"] == 745695
        assert report["batch3_points_total"] == 571404
        assert report["batch3_unique_photos"] == 22664
        assert report["b1_b3_overlap"] == 0 and report["b2_b3_overlap"] == 0

    def test_exact_unique_discrepancy_explained(self, report):
        # 29,171 vs 任务书 29,176：差额 5 = 批3 反光 reject（无 blob/SHA），
        # 其 photo_id 与点数已记入缺失账本；不静默吞差。
        assert report["exact_unique_all"] == 29171
        assert report["batch3_missing_sha_photos"] == 5
        assert report["exact_unique_expected_by_taskbook"] == 29176

    def test_other_points_discrepancy_explained(self, report):
        # 40,586 vs 40,591：差额 5 点属于上述 5 张 reject 照片
        assert sum(report["other_points"].values()) == 40586
        assert report["missing_photo_points_in_other"] == 5

    def test_discrepancy_ledger_exists(self):
        p = ROOT / "reports/nextgen_v2/coordinate_discrepancy_ledger.json"
        assert p.exists()
        d = json.loads(p.read_text(encoding="utf-8"))
        assert d["measured"] == 463 and len(d["rows"]) == 463
