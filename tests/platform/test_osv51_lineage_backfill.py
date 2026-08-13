"""OSV51 C-4 红测试：历史批次客户血缘回填（确定性、追加式、守恒）。

契约：batch.test_run_id → uat_test_run_v1 唯一行 → customer_ids_json
（md_customer_v1 交叉印证）；禁止名称模糊猜测；不可唯一确定 → 未绑定/
待裁决（不得显示“全局”）；回填前后逐批审计 + 守恒；history/quarantine/
detail/API/权限共用同一关联源（import_batch_customer_scope_v1）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.test_data import FixtureTestDataService

NS = "uatv7_osv51_lin"
NS_B = "uatv7_osv51_lin_b"


class _OkRecognition:
    def recognize(self, data, conf=0.25):
        return {"count": 0, "products": []}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "osv51-lin-pw")
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=_OkRecognition(), probe=lambda spec: None)
    build_profiles_service(bundle)
    store = bundle.store
    tds = FixtureTestDataService(store)
    tds.create_test_run_context(NS, customer_ids=[f"{NS}_cust"])
    tds.create_test_run_context(NS_B,
                                customer_ids=[f"{NS_B}_cust",
                                              f"{NS_B}_cust2"])
    # 现场事实：test_run 客户在 md_customer_v1 存在（交叉印证源）
    for ns, cids in ((NS, [f"{NS}_cust"]),
                     (NS_B, [f"{NS_B}_cust", f"{NS_B}_cust2"])):
        for cid in cids:
            store._conn.execute(
                "INSERT INTO md_customer_v1 (customer_id, name,"
                " created_by, created_at, updated_at, data_scope,"
                " test_run_id) VALUES (?,?,?,?,?,?,?)",
                (cid, cid, "tds", "2026-08-12T04:34:29+00:00",
                 "2026-08-12T04:34:29+00:00", "uat_fixture", ns))
    store._conn.commit()
    return {"store": store, "tds": tds}


def _seed_history_batch(env, bid: str, template_id: str,
                        test_run_id: str, data_scope="uat_fixture"):
    env["store"]._conn.execute(
        "INSERT INTO import_batch_v1 (batch_id, template_id, filename,"
        " file_format, file_hash, status, actor, row_count,"
        " mapping_json, dry_run_json, error_report_json, commit_json,"
        " created_at, updated_at, data_scope, test_run_id, visibility,"
        " archived_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (bid, template_id, f"{bid}.csv", "csv", "h" + bid, "committed",
         "bill", 1, "{}", "{}", "[]", "{}",
         "2026-08-12T04:34:29+00:00", "2026-08-12T04:34:29+00:00",
         data_scope, test_run_id, "history",
         "2026-08-13T05:28:36+00:00"))
    env["store"]._conn.commit()


def _assoc(env, bid):
    rows = env["store"]._conn.execute(
        "SELECT customer_id, scope_source FROM"
        " import_batch_customer_scope_v1 WHERE batch_id=? ORDER BY"
        " customer_id", (bid,)).fetchall()
    return [(r["customer_id"], r["scope_source"]) for r in rows]


class TestBackfill:
    def test_deterministic_bind_single_customer(self, env):
        _seed_history_batch(env, "imp-lin-01", "customers_v1", NS)
        from scripts.osv51_backfill_batch_customer_scope import \
            backfill_store
        rep = backfill_store(env["store"], apply=True)
        assert _assoc(env, "imp-lin-01") == \
            [(f"{NS}_cust", "backfill_osv51")]
        assert rep["bound"]["imp-lin-01"] == [f"{NS}_cust"]

    def test_multi_customer_registry(self, env):
        _seed_history_batch(env, "imp-lin-02", "stores_addresses_v1",
                            NS_B)
        from scripts.osv51_backfill_batch_customer_scope import \
            backfill_store
        backfill_store(env["store"], apply=True)
        assert _assoc(env, "imp-lin-02") == [
            (f"{NS_B}_cust", "backfill_osv51"),
            (f"{NS_B}_cust2", "backfill_osv51")]

    def test_unresolvable_not_bound(self, env):
        _seed_history_batch(env, "imp-lin-03", "customers_v1",
                            "no_such_run")
        from scripts.osv51_backfill_batch_customer_scope import \
            backfill_store
        rep = backfill_store(env["store"], apply=True)
        assert _assoc(env, "imp-lin-03") == []
        assert "imp-lin-03" in rep["pending"]

    def test_quarantine_batches_never_bound(self, env):
        _seed_history_batch(env, "imp-lin-04", "customers_v1", "",
                            data_scope="quarantine")
        from scripts.osv51_backfill_batch_customer_scope import \
            backfill_store
        rep = backfill_store(env["store"], apply=True)
        assert _assoc(env, "imp-lin-04") == []
        assert "imp-lin-04" in rep["quarantine_pending"]

    def test_idempotent_and_audit_contains_batch_id(self, env):
        _seed_history_batch(env, "imp-lin-05", "customers_v1", NS)
        from scripts.osv51_backfill_batch_customer_scope import \
            backfill_store
        backfill_store(env["store"], apply=True)
        rep2 = backfill_store(env["store"], apply=True)
        assert len(_assoc(env, "imp-lin-05")) == 1
        assert rep2["bound"] == {}
        auds = env["store"]._conn.execute(
            "SELECT detail_json FROM scope_backfill_audit_v1 WHERE"
            " matched_by='osv51_backfill'").fetchall()
        assert auds, "回填必须逐批审计入账"
        assert all("imp-lin-05" in a["detail_json"] for a in auds)

    def test_dry_run_writes_nothing(self, env):
        _seed_history_batch(env, "imp-lin-06", "customers_v1", NS)
        from scripts.osv51_backfill_batch_customer_scope import \
            backfill_store
        rep = backfill_store(env["store"], apply=False)
        assert _assoc(env, "imp-lin-06") == []
        assert rep["bound"]["imp-lin-06"] == [f"{NS}_cust"]


class TestGateAssociationCompleteness:
    def test_gate_flags_unassociated_history_batch(self, env):
        from src.platform.gate_evaluator import \
            evaluate_gate_from_evidence
        _seed_history_batch(env, "imp-lin-07", "customers_v1",
                            "no_such_run")
        res = evaluate_gate_from_evidence(store=env["store"])
        bad = [c["check"] for c in res["checks"] if not c["ok"]]
        assert "import_batch_association_complete" in bad
        assert res["gate"] != "READY_FOR_REAL_DATA_UAT"

    def test_gate_ok_after_backfill_or_quarantine(self, env):
        from src.platform.gate_evaluator import \
            evaluate_gate_from_evidence
        _seed_history_batch(env, "imp-lin-08", "customers_v1", NS)
        _seed_history_batch(env, "imp-lin-09", "customers_v1", "",
                            data_scope="quarantine")
        from scripts.osv51_backfill_batch_customer_scope import \
            backfill_store
        backfill_store(env["store"], apply=True)
        res = evaluate_gate_from_evidence(store=env["store"])
        bad = [c["check"] for c in res["checks"] if not c["ok"]]
        assert "import_batch_association_complete" not in bad


class TestSingleAssociationSource:
    def test_dto_global_flag_and_display(self, env):
        """全局模板（users_v1 等）才可显示全局；有客户列模板空关联
        → 未绑定/待裁决。"""
        from src.platform.field_ops import FieldOpsService
        from src.platform.finance import FinanceService
        from src.platform.iam import IAMService, MasterDataService
        from src.platform.import_center import ImportCenter
        from src.platform.survey import SurveyService
        iam = IAMService(env["store"])
        center = ImportCenter(env["store"], iam=iam,
                              master=MasterDataService(env["store"],
                                                       iam),
                              survey=SurveyService(env["store"]),
                              field_ops=FieldOpsService(env["store"]),
                              finance=FinanceService(env["store"]))
        _seed_history_batch(env, "imp-lin-10", "customers_v1", NS)
        _seed_history_batch(env, "imp-lin-11", "users_v1", "")
        dto_c = center.batch_dto(center._must("imp-lin-10"))
        dto_u = center.batch_dto(center._must("imp-lin-11"))
        assert dto_c["is_global_template"] is False
        assert dto_u["is_global_template"] is True
        # 单一关联源：回填后 DTO 客户范围立即可见
        from scripts.osv51_backfill_batch_customer_scope import \
            backfill_store
        backfill_store(env["store"], apply=True)
        dto2 = center.batch_dto(center._must("imp-lin-10"))
        assert [c["customer_id"]
                for c in dto2["customer_scopes"]] == [f"{NS}_cust"]
