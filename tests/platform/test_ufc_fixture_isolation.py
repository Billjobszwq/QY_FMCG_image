"""UFC T4 红测试：UAT fixture 结构性隔离与归档。

要求：
- fixture 不进入运营投影（不以名字前缀为唯一机制，按 data_scope/
  visibility 结构过滤）；
- 当前一次运行的 UAT 可在测试与证据页查询；结束后归档；
- 历史失败/取消/审批对象仍可审计（不删除）；
- 归档后 operational current 残留 = 0。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.test_data import TestDataService


class _OkRecognition:
    def recognize(self, data, conf=0.25):
        return {"count": 0, "products": []}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "ufc-t4-pw")
    adapter = _OkRecognition()
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=adapter, probe=lambda spec: None)
    build_profiles_service(bundle)
    return {"store": bundle.store, "svc": TestDataService(bundle.store)}


def _mk_run_work(store, run_id, work_id, customer_id, status_run,
                 status_work, scope="operational", visibility="current",
                 title="任务"):
    store._conn.execute(
        "INSERT INTO business_run_v1 (run_id, work_id, customer_id,"
        " status, command_kind, data_scope, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,datetime('now'),datetime('now'))",
        (run_id, work_id, customer_id, status_run, "workflow.run",
         scope))
    store._conn.execute(
        "INSERT INTO work_item_v2 (work_id, run_id, customer_id,"
        " status, title, data_scope, visibility, created_at,"
        " updated_at) VALUES (?,?,?,?,?,?,?,datetime('now'),"
        "datetime('now'))",
        (work_id, run_id, customer_id, status_work, title, scope,
         visibility))
    store._conn.commit()


class TestFixtureIsolation:
    def test_archived_fixture_not_in_projection(self, env):
        """归档 fixture（uat_fixture+history）不得进入运营投影。"""
        store, svc = env["store"], env["svc"]
        _mk_run_work(store, "run-op1", "work-op1", "real-cust",
                     "running", "running")
        _mk_run_work(store, "run-uat1", "work-uat1", "uat-x_cust",
                     "failed", "blocked", scope="uat_fixture",
                     visibility="history")
        proj = store.rebuild_work_projection()
        ids = {i["work_id"] for i in proj["items"]}
        assert "work-op1" in ids
        assert "work-uat1" not in ids, "归档 fixture 进入了运营投影"

    def test_current_fixture_also_not_operational(self, env):
        """正在运行的 UAT（visibility=current）同样不进运营首页，
        只在测试与证据页可见。"""
        store, svc = env["store"], env["svc"]
        _mk_run_work(store, "run-uat2", "work-uat2", "uat-y_cust",
                     "running", "running", scope="uat_fixture",
                     visibility="current")
        proj = store.rebuild_work_projection()
        ids = {i["work_id"] for i in proj["items"]}
        assert "work-uat2" not in ids
        ns_list = svc.list_namespaces()
        assert any(n["namespace"] == "uat-y_cust"
                   and n["visibility"] == "current" for n in ns_list)

    def test_mark_and_archive_namespace(self, env):
        """mark→current；archive→history 且 operational 残留=0。"""
        store, svc = env["store"], env["svc"]
        store._conn.execute(
            "INSERT INTO md_customer_v1 (customer_id, name, created_by,"
            " created_at, updated_at) VALUES"
            " ('nsz_cust','UAT Z','admin',datetime('now'),"
            "datetime('now'))")
        _mk_run_work(store, "run-z1", "work-z1", "nsz_cust",
                     "cancelled", "running")
        svc.mark_namespace("nsz", customer_ids=["nsz_cust"])
        # 标记后：run/work 均为 uat_fixture
        w = store.get_work_item_v2("work-z1")
        assert w["data_scope"] == "uat_fixture"
        assert w["visibility"] == "current"
        svc.archive_namespace("nsz")
        w = store.get_work_item_v2("work-z1")
        assert w["visibility"] == "history"
        assert w["superseded_at"], "归档必须记录 superseded_at"
        # 行仍存在（可审计，不删除）
        assert store.get_work_item_v2("work-z1") is not None
        # operational current 残留 = 0
        residue = svc.operational_residue()
        assert residue == 0, f"残留 {residue}"

    def test_legacy_backfill(self, env):
        """遗留 uat* 客户追加式回填为 fixture 并归档（不删除）。"""
        store, svc = env["store"], env["svc"]
        store._conn.execute(
            "INSERT INTO md_customer_v1 (customer_id, name, created_by,"
            " created_at, updated_at) VALUES"
            " ('uatv2_old_cust','旧 UAT','admin',datetime('now'),"
            "datetime('now'))")
        _mk_run_work(store, "run-old", "work-old", "uatv2_old_cust",
                     "cancelled", "running")
        n = svc.converge_legacy_fixtures()
        assert n >= 1
        w = store.get_work_item_v2("work-old")
        assert w["data_scope"] == "uat_fixture"
        assert w["visibility"] == "history"
        c = store._conn.execute(
            "SELECT data_scope FROM md_customer_v1 WHERE"
            " customer_id='uatv2_old_cust'").fetchone()
        assert c["data_scope"] == "uat_fixture"
        proj = store.rebuild_work_projection()
        assert all(i["work_id"] != "work-old" for i in proj["items"])
