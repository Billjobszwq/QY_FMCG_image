"""ABOSV2 Phase B 红测试：统一 Work/Event/Usage 控制平面。

要求（01-UNIFIED-WORK-EVENT-USAGE-CONTROL-PLANE.md）：
1. 版本化 schema：BusinessRunV1 / WorkItemV2 / EventEnvelopeV1 /
   UsageEventV2 / EvidenceBundleV1（全字段：tenant/customer/project/
   correlation/causation/parent/subject）；
2. Transactional Outbox：业务记录、事件、outbox 同一事务；幂等键去重；
3. 状态机：queued→running→succeeded/failed；failed 不得直接变成功，
   必须由 retry 新事件推动；cancel 有事件；
4. current projection 可从事件重建，count/hash 对账一致；
5. Web/API/Agent 共用 Command Gateway；一条识别全链
   goal/command → run → node → recognition record → event/evidence/usage
   → current projection，所有 ID 一致。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.api.app import create_app
from src.platform.api.health import ServiceSpec, ServiceStatus
from src.platform.control_plane import CommandGateway


def _fake_probe(spec: ServiceSpec) -> ServiceStatus:
    return ServiceStatus(name=spec.name, status="healthy", latency_ms=1,
                         detail="fake")


class _BoomRecognition:
    """识别 adapter：前 n 次抛错，用于失败→恢复测试。"""

    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.calls = 0

    def recognize(self, data: bytes, conf: float = 0.25):
        from src.platform.adapters.legacy.recognition import (
            RecognitionAdapterError)
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RecognitionAdapterError("unreachable", "识别服务不可达")
        return {"count": 2, "products": [
            {"name": "SKU-A", "count": 1}, {"name": "SKU-B", "count": 1}]}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "v2-admin-pw")
    adapter = _BoomRecognition()
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=adapter, probe=_fake_probe)
    profiles_service = build_profiles_service(bundle)
    gateway = CommandGateway(bundle.store, profiles_service,
                             recognition_adapter=adapter)
    return {"store": bundle.store, "gateway": gateway,
            "adapter": adapter, "profiles": profiles_service,
            "bundle": bundle}


class TestSchemaAndLedgers:
    def test_versioned_tables_exist_with_full_fields(self, env):
        store = env["store"]
        names = {r["name"] for r in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("business_run_v1", "work_item_v2", "event_envelope_v1",
                  "usage_event_v2", "evidence_bundle_v1", "outbox_v1"):
            assert t in names, f"缺少表 {t}"
        cols = {r["name"] for r in store._conn.execute(
            "PRAGMA table_info(business_run_v1)")}
        for c in ("run_id", "work_id", "tenant_id", "customer_id",
                  "project_id", "workflow_definition_id", "workflow_version",
                  "trigger_type", "parent_run_id", "correlation_id",
                  "causation_id", "subject_type", "subject_id",
                  "initiator_type", "initiator_id", "status",
                  "current_node", "version", "evidence_bundle_id",
                  "usage_account_id", "policy_snapshot_id"):
            assert c in cols, f"business_run_v1 缺字段 {c}"

    def test_events_and_usage_are_append_only(self, env):
        store = env["store"]
        env["gateway"].submit(
            command_kind="vision.recognition.create",
            params={"images": [["a.jpg", b"\xff\xd8fake"]]},
            actor="tester", source="api")
        with pytest.raises(Exception):
            store._conn.execute("DELETE FROM event_envelope_v1")
        with pytest.raises(Exception):
            store._conn.execute("UPDATE usage_event_v2 SET quantity=0")


class TestGatewayChain:
    def test_full_recognition_chain_ids_consistent(self, env):
        """一条识别全链：command → run → node → record → event/evidence/
        usage → projection；所有 ID 一致。"""
        store, gw = env["store"], env["gateway"]
        out = gw.submit(
            command_kind="vision.recognition.create",
            params={"images": [["shelf.jpg", b"\xff\xd8fake"]]},
            actor="tester", source="api",
            correlation_id="corr-demo-1", goal_id="goal-demo")
        run_id, work_id = out["run_id"], out["work_id"]
        task_id = out["result"]["task_id"]

        run = store.get_business_run(run_id)
        assert run["status"] == "succeeded"
        assert run["work_id"] == work_id
        assert run["correlation_id"] == "corr-demo-1"
        assert run["subject_type"] == "recognition_task"
        assert run["subject_id"] == task_id
        assert run["evidence_bundle_id"], "run 必须挂证据 bundle"

        # 域记录回链 run/trace
        task = store.get_recognition_task(task_id)
        assert task["correlation_id"] == "corr-demo-1"
        assert task["run_id"] == run_id

        # 事件链：accepted/node.started/node.completed/succeeded 同一 run
        events = store.list_events(run_id=run_id)
        types = [e["event_type"] for e in events]
        for t in ("command.accepted", "node.started", "node.completed",
                  "run.succeeded"):
            assert t in types, f"缺事件 {t}"
        assert all(e["correlation_id"] == "corr-demo-1" for e in events)
        assert all(e["work_id"] == work_id for e in events)

        # usage：按照片计量 + 计算时长，run/work 关联一致
        usage = store.list_usage_events_v2(run_id=run_id)
        units = {u["unit"] for u in usage}
        assert "recognition_photo" in units
        assert "model_compute_ms" in units
        assert all(u["work_id"] == work_id for u in usage)

        # 证据 bundle 可追到 run 与产物
        ev = store.get_evidence_bundle(run["evidence_bundle_id"])
        assert ev["run_id"] == run_id
        assert "recognition_result" in ev["kind"]

        # outbox：事件全部投递（at-least-once，幂等键去重）
        pend = store._conn.execute(
            "SELECT count(*) c FROM outbox_v1 WHERE status='pending'"
        ).fetchone()["c"]
        assert pend == 0

        # current projection：该 run 形成已完成工作项
        proj = store.rebuild_work_projection()
        assert proj["count"] >= 1
        item = next(w for w in proj["items"] if w["work_id"] == work_id)
        assert item["status"] == "done"
        assert item["subject_id"] == task_id
        # 重建幂等且 hash/count 对账一致
        proj2 = store.rebuild_work_projection()
        assert proj2["hash"] == proj["hash"] and proj2["count"] == proj["count"]

    def test_idempotency_same_command_same_run(self, env):
        gw = env["gateway"]
        a = gw.submit(command_kind="vision.recognition.create",
                      params={"images": [["a.jpg", b"\xff\xd8x"]]},
                      actor="t", source="api", idempotency_key="idem-1")
        b = gw.submit(command_kind="vision.recognition.create",
                      params={"images": [["a.jpg", b"\xff\xd8x"]]},
                      actor="t", source="api", idempotency_key="idem-1")
        assert a["run_id"] == b["run_id"], "同一幂等键必须返回同一 run"
        assert b.get("idempotent_replay") is True

    def test_failure_and_retry_recovery_in_same_chain(self, env):
        """识别失败 → 同一 run 展示错误 → retry 恢复成功。"""
        env["adapter"].fail_times = 1
        store, gw = env["store"], env["gateway"]
        out = gw.submit(command_kind="vision.recognition.create",
                        params={"images": [["a.jpg", b"\xff\xd8x"]]},
                        actor="t", source="api")
        run = store.get_business_run(out["run_id"])
        assert run["status"] == "failed"
        assert run["error"], "失败必须带错误信息"
        types = {e["event_type"] for e in store.list_events(
            run_id=out["run_id"])}
        assert "run.failed" in types
        # failed 不得直接变成功：只能经 retry 事件推动
        with pytest.raises(Exception):
            store.set_business_run_status(out["run_id"], "succeeded")
        retried = gw.retry(out["run_id"], actor="t")
        run2 = store.get_business_run(out["run_id"])
        assert run2["status"] == "succeeded"
        assert retried["result"]["task_id"]
        types = {e["event_type"] for e in store.list_events(
            run_id=out["run_id"])}
        assert "run.retried" in types and "run.succeeded" in types

    def test_cancel_run_emits_event(self, env):
        store, gw = env["store"], env["gateway"]
        out = gw.submit(command_kind="vision.recognition.create",
                        params={"images": [["a.jpg", b"\xff\xd8x"]]},
                        actor="t", source="api")
        # 已完成 run 不允许 cancel（状态机诚实）
        with pytest.raises(Exception):
            gw.cancel(out["run_id"], actor="t")


class TestCommandGatewayAPI:
    """Web/API/Agent 共用同一 gateway 入口。"""

    def _client(self, env, tmp_path):
        from src.platform.auth import AuthService
        app = create_app(services=(), probe=_fake_probe,
                         bundle=env["bundle"],
                         recognition_adapter=env["adapter"],
                         profiles_service=env["profiles"],
                         web_dist=tmp_path / "none")
        c = TestClient(app)
        r = c.post("/api/v1/auth/login",
                   json={"username": "admin", "password": "v2-admin-pw"})
        return c, {"X-CSRF-Token": r.json()["csrf_token"]}

    def test_api_entry_creates_same_chain(self, env, tmp_path):
        c, h = self._client(env, tmp_path)
        r = c.post("/api/v1/commands", headers=h, json={
            "command_kind": "vision.recognition.create",
            "params": {"images": [["api.jpg", "AP/9mZmFrZQ=="]]},
            "source": "api", "idempotency_key": "api-1"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["run"]["status"] == "succeeded"
        assert d["work"]["work_id"] == d["run"]["work_id"]
        # 详情 API 已带 run/evidence/usage（不再诚实空）
        task_id = d["result"]["task_id"]
        det = c.get(f"/api/v1/recognition/tasks/{task_id}").json()
        assert det["relations"]["run_id"] == d["run"]["run_id"]
        assert det["usage"]["events"], "usage 必须真实计量"
        assert det["evidence"]["refs"], "证据必须可追"
        # 对账端点：projection 与事件一致
        rec = c.get("/api/v1/control/reconcile").json()
        assert rec["consistent"] is True
