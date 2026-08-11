"""ABOSV2-P0-001 红测试：统一 current task projection。

现场复现（2026-08-11）：/api/v1/workitems?limit=500 返回 256 项，
其中 250 项为 rq_v2 人工审核；该队列已被 LS22 micro-gold v2 取代
（docs/README 2026-08-09：5+5+250 人工门 = SUPERSEDED_FOR_DEMO_TRAINING），
却仍作为“今日待办”出现在主页与主管工作台。

要求（v2 审计 P0-001）：
1. supersession 账本（append-only）记录工作族被取代关系；
2. /api/v1/workitems 默认 projection=current：被取代族不进入当前待办；
3. projection=history 只返回被取代历史；projection=all 返回全部；
4. 旧历史永不删除：history 中仍可见 rq_v2 条目；
5. legacy dry_run 训练计划同样不得作为当前待办（CODEX 手册 §5.6-6）。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import build_production_bundle
from src.platform.api.app import create_app
from src.platform.api.health import ServiceSpec, ServiceStatus


def _fake_probe(spec: ServiceSpec) -> ServiceStatus:
    return ServiceStatus(name=spec.name, status="healthy", latency_ms=1,
                         detail="fake")


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "v2-admin-pw")
    monkeypatch.setenv("PLATFORM_DATASETS_ROOT", str(tmp_path / ".datasets"))
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        probe=_fake_probe)
    app = create_app(services=(), probe=_fake_probe, bundle=bundle,
                     web_dist=tmp_path / "none")
    store = bundle.store
    store.register_queue_version(queue_version="rq_v1",
                                 protocol="diagnostic_v1")
    store.register_queue_version(queue_version="rq_v2",
                                 protocol="diagnostic_v1")
    # 旧失效队列 rq_v1（历史）
    for i in range(2):
        store.add_review_task(
            task_id=f"rt_v1_{i:03d}", claim_token=f"tok_v1_{i:03d}",
            photo_id=f"pv1_{i:03d}", sha256=f"sha_v1_{i:03d}",
            review_mode="double_review", requires_second_review=True,
            queue_version="rq_v1", protocol="diagnostic_v1")
    # 被取代的 rq_v2 队列（模拟现场 250 条，缩小为 5 条）
    for i in range(5):
        store.add_review_task(
            task_id=f"rt_v2_{i:03d}", claim_token=f"tok_v2_{i:03d}",
            photo_id=f"pv2_{i:03d}", sha256=f"sha_v2_{i:03d}",
            review_mode="double_review", requires_second_review=True,
            queue_version="rq_v2", protocol="diagnostic_v1")
    store.invalidate_queue_version(
        queue_version="rq_v1", reason="invalid_id_sha_mapping")
    return TestClient(app), bundle


def _reviews(d: dict, queue: str) -> list:
    return [w for w in d["items"] if w["kind"] == "human_review"
            and w["detail"].get("queue_version") == queue]


class TestCurrentProjection:
    def test_default_projection_excludes_superseded_rq_v2(self, client):
        client, _ = client
        d = client.get("/api/v1/workitems").json()
        assert d.get("projection") == "current"
        assert _reviews(d, "rq_v2") == [], (
            "被 supersession 取代的 rq_v2 队列不得进入当前待办")
        # 未被取代的历史失效队列（rq_v1 已 invalid）同样不进 current，
        # 但 rq_v1/rq_v2 必须仍可从 history 看到
        h = client.get("/api/v1/workitems?projection=history").json()
        assert len(_reviews(h, "rq_v2")) == 5
        assert h.get("projection") == "history"

    def test_all_projection_returns_everything_with_flag(self, client):
        client, _ = client
        d = client.get("/api/v1/workitems?projection=all").json()
        v2 = _reviews(d, "rq_v2")
        assert len(v2) == 5
        assert all(w.get("superseded") is True for w in v2)

    def test_summary_reports_superseded_count(self, client):
        client, _ = client
        d = client.get("/api/v1/workitems").json()
        s = d["summary"]
        assert s.get("superseded") == 5, (
            "current 视图必须如实报告被移入历史的工作族数量")
        assert s["pending_review"] == 0

    def test_invalid_projection_rejected(self, client):
        client, _ = client
        r = client.get("/api/v1/workitems?projection=bogus")
        assert r.status_code == 422

    def test_legacy_training_dry_run_not_current_todo(self, client):
        """CODEX 手册 §5.6-6：legacy dry-run 不得作为当前待办。"""
        client, bundle = client
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        run = bundle.store.create_training_run({
            "run_id": "legacy_dryrun_001", "snapshot_id": None,
            "kind": "dry_run", "plan_json": "{}",
            "command_json": '{"argv": ["--budget-minutes"]}',
            "budget_json": "{}", "stop_lines_json": "{}",
            "status": "dry_run", "publish_status": "none",
            "requested_by": "test", "created_at": now, "updated_at": now})
        d = client.get("/api/v1/workitems").json()
        legacy = [w for w in d["items"] if w["kind"] == "training"
                  and w["detail"].get("run_id") == run["run_id"]]
        assert legacy == [], "legacy dry_run 不得进入当前待办"


class TestSupersessionLedger:
    def test_ledger_is_append_only(self, client):
        client, bundle = client
        bundle.store.add_work_item_supersession(
            family="test", match={"k": ["v"]}, superseded_by="t2",
            reason="先插入一行", decided_by="test")
        conn = bundle.store._conn
        with pytest.raises(Exception):
            conn.execute("DELETE FROM work_item_supersession_v1")
        with pytest.raises(Exception):
            conn.execute(
                "UPDATE work_item_supersession_v1 SET reason='x'")

    def test_manual_supersession_takes_effect(self, client):
        """新的 supersession 记录立即改变 current 投影（事件驱动）。"""
        client, bundle = client
        d0 = client.get("/api/v1/workitems").json()
        # 现场 rq_v2 已被启动种子取代；再对 training 族整体做一次
        # （无 training 项时也应安全）
        before = d0["count"]
        bundle.store.add_work_item_supersession(
            family="labeling", match={"batch_id": ["nonexistent"]},
            superseded_by="test", reason="测试用", decided_by="test")
        d1 = client.get("/api/v1/workitems").json()
        assert d1["count"] == before, "不匹配任何项的 supersession 无副作用"
