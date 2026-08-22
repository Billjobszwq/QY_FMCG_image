"""M6（G5）：账号级计量、预算、限流与监控合同测试。

覆盖 03 §1–§6 与 05 计划 M6：
- token/embedding/字符/算力单位不得互相伪换算；
- 每行 Usage 完整归属（principal/tenant/customer/project/connection/
  model/binding/model_call_id）；
- 调用意图先落账（预算预留），成功/失败后结算；
- Usage finalize 失败 → MODEL_METERING_INCOMPLETE + 对账收敛，
  不得重复计费、不得免费调用；
- 硬预算 100% 拒绝（429 + Retry 窗口），软阈值 80% → Governance Alert；
- 无价格表时成本标注 unknown（本地模型不伪装零成本）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.platform.data.store import PlatformStore
from src.platform.models.metering import (
    CallContext,
    MeteringIncomplete,
    ModelBudgetExhausted,
    ModelBudgetService,
    ModelMeteringService,
    Settlement,
)

TENANT = "local"


@pytest.fixture()
def services(tmp_path: Path):
    store = PlatformStore(tmp_path / "p.sqlite")
    budgets = ModelBudgetService(store)
    metering = ModelMeteringService(store, budgets=budgets)
    yield store, budgets, metering
    store.close()


def _ctx(**over) -> CallContext:
    base = dict(
        tenant_id=TENANT, principal_id="svc-research",
        principal_kind="service_account", customer_id="c1",
        project_id="p1", run_id="run-1", work_id="work-1",
        agent_id="", module="research-rag", capability="embedding",
        connection_id="local-omlx", connection_version=1,
        binding_id="cognition-embedding-default", binding_version=1,
        model_id="Qwen3-Embedding-0.6B-8bit", model_revision="")
    base.update(over)
    return CallContext(**base)


class TestUsageNormalization:
    def test_chat_usage_rows_use_provider_reported_tokens(self, services):
        store, _, metering = services
        call = metering.begin_call(_ctx(capability="chat"))
        out = metering.settle_call(call, Settlement(
            ok=True, input_tokens=11, output_tokens=7,
            cached_input_tokens=3, reasoning_tokens=2,
            compute_ms=120.5, provider_request_id="req-1"))
        assert out["status"] == "succeeded"
        rows = {r["unit"]: r for r in store.list_usage_events_v2()}
        assert rows["input_token"]["quantity"] == 11
        assert rows["output_token"]["quantity"] == 7
        assert rows["cached_input_token"]["quantity"] == 3
        assert rows["reasoning_token"]["quantity"] == 2
        assert rows["model_request"]["quantity"] == 1
        for row in rows.values():
            assert row["meter_source"] == "provider_reported"
            assert row["provider_request_id"] == "req-1"
        # token 缺失不得以 0 冒充
        assert "input_character" not in rows

    def test_embedding_without_tokens_uses_honest_units(self, services):
        store, _, metering = services
        call = metering.begin_call(_ctx())
        metering.settle_call(call, Settlement(
            ok=True, embedding_inputs=4, embedding_vectors=4,
            input_characters=512, compute_ms=88.0))
        rows = {r["unit"]: r for r in store.list_usage_events_v2()}
        assert rows["embedding_input"]["quantity"] == 4
        assert rows["embedding_vector"]["quantity"] == 4
        assert rows["input_character"]["quantity"] == 512
        assert rows["model_compute_ms"]["quantity"] == 88.0
        # 未报告 token：不产生 token 行，不伪造
        for forbidden in ("input_token", "output_token"):
            assert forbidden not in rows
        for row in rows.values():
            assert row["meter_source"] == "platform_observed"

    def test_failed_call_still_settles(self, services):
        store, _, metering = services
        call = metering.begin_call(_ctx(capability="chat"))
        metering.settle_call(call, Settlement(
            ok=False, error_code="MODEL_RATE_LIMITED", compute_ms=12))
        rows = store.list_usage_events_v2()
        assert all(r["outcome"] == "failed" for r in rows)
        assert rows[0]["error_code"] == "MODEL_RATE_LIMITED"


class TestAttribution:
    def test_every_row_has_full_attribution(self, services):
        store, _, metering = services
        call = metering.begin_call(_ctx())
        metering.settle_call(call, Settlement(
            ok=True, embedding_inputs=1, compute_ms=5))
        for row in store.list_usage_events_v2():
            assert row["principal_id"] == "svc-research"
            assert row["principal_kind"] == "service_account"
            assert row["tenant_id"] == TENANT
            assert row["customer_id"] == "c1"
            assert row["project_id"] == "p1"
            assert row["run_id"] == "run-1"
            assert row["connection_id"] == "local-omlx"
            assert row["connection_version"] == 1
            assert row["binding_id"] == "cognition-embedding-default"
            assert row["binding_version"] == 1
            assert row["model_call_id"] == call
            assert row["model"] == "Qwen3-Embedding-0.6B-8bit"

    def test_begin_requires_principal(self, services):
        _, _, metering = services
        with pytest.raises(Exception):
            metering.begin_call(_ctx(principal_id=""))


class TestCallLedgerAndReconciliation:
    def test_idempotency_key_returns_same_call(self, services):
        _, _, metering = services
        c1 = metering.begin_call(_ctx(), idempotency_key="k1")
        c2 = metering.begin_call(_ctx(), idempotency_key="k1")
        assert c1 == c2

    def test_double_settle_rejected_no_double_billing(self, services):
        store, _, metering = services
        call = metering.begin_call(_ctx())
        metering.settle_call(call, Settlement(ok=True, input_tokens=5,
                                              output_tokens=3))
        with pytest.raises(Exception):
            metering.settle_call(call, Settlement(ok=True, input_tokens=5,
                                                  output_tokens=3))
        units = [r["unit"] for r in store.list_usage_events_v2()]
        assert units.count("input_token") == 1

    def test_finalize_failure_marks_incomplete_and_reconciles(
            self, services):
        store, _, metering = services
        call = metering.begin_call(_ctx())

        # 模拟外部调用成功但 Usage finalize 失败：
        # sqlite3.Connection 属性只读，用 store 代理注入故障
        class _BrokenConn:
            def __init__(self, conn):
                self._c = conn

            def execute(self, sql, *a, **k):
                if "INSERT OR IGNORE INTO usage_event_v2" in sql:
                    raise RuntimeError("disk full")
                return self._c.execute(sql, *a, **k)

            def __getattr__(self, name):
                return getattr(self._c, name)

        class _BrokenStore:
            def __init__(self, inner):
                self._inner = inner
                self._conn = _BrokenConn(inner._conn)

            def __getattr__(self, name):
                return getattr(self._inner, name)

        broken = ModelMeteringService(_BrokenStore(store))
        with pytest.raises(MeteringIncomplete) as ei:
            broken.settle_call(call, Settlement(ok=True, input_tokens=1,
                                                output_tokens=1))
        assert ei.value.code == "MODEL_METERING_INCOMPLETE"
        row = store._conn.execute(
            "SELECT status FROM model_call_ledger_v1 WHERE"
            " model_call_id=?", (call,)).fetchone()
        assert row["status"] == "metering_incomplete"
        report = metering.reconcile()
        assert report["metering_incomplete"] == 1
        assert report["gate_ok"] is False

    def test_stale_requested_converges_no_free_calls(self, services):
        store, _, metering = services
        call = metering.begin_call(_ctx())
        # 把 created_at 拨到结算窗口外，模拟进程中断
        store._conn.execute(
            "UPDATE model_call_ledger_v1 SET created_at="
            " datetime('now','-1 hour') WHERE model_call_id=?", (call,))
        report = metering.reconcile(window_seconds=600)
        assert report["marked_incomplete"] == 1
        row = store._conn.execute(
            "SELECT status FROM model_call_ledger_v1 WHERE"
            " model_call_id=?", (call,)).fetchone()
        assert row["status"] == "metering_incomplete"

    def test_clean_ledger_gate_ok(self, services):
        _, _, metering = services
        call = metering.begin_call(_ctx())
        metering.settle_call(call, Settlement(ok=True, compute_ms=3))
        report = metering.reconcile()
        assert report["gate_ok"] is True


class TestBudgets:
    def test_hard_limit_blocks_before_provider(self, services):
        _, budgets, metering = services
        budgets.create_budget(tenant_id=TENANT, period="day",
                              unit="request", hard_limit=2,
                              created_by="admin")
        for _ in range(2):
            call = metering.begin_call(_ctx())
            metering.settle_call(call, Settlement(ok=True))
        with pytest.raises(ModelBudgetExhausted) as ei:
            metering.begin_call(_ctx())
        assert ei.value.http_status == 429
        assert ei.value.retry_after is not None and ei.value.retry_after > 0
        # 第三次调用没有进入账本（Provider 前被拦）
        n = metering.store._conn.execute(
            "SELECT count(*) c FROM model_call_ledger_v1").fetchone()[0]
        assert n == 2

    def test_token_budget_includes_reservation(self, services):
        _, budgets, metering = services
        budgets.create_budget(tenant_id=TENANT, period="day",
                              unit="output_token", hard_limit=100,
                              created_by="admin")
        # 预留 100 → 下一次预留即被拒
        metering.begin_call(_ctx(capability="chat"),
                            reserved_output_tokens=100)
        with pytest.raises(ModelBudgetExhausted):
            metering.begin_call(_ctx(capability="chat"),
                                reserved_output_tokens=1)

    def test_soft_limit_raises_governance_alert(self, services):
        store, budgets, metering = services
        from src.platform.governance.alert_service import AlertService
        alerts = AlertService(store)
        budgets.alerts = alerts
        metering.alerts = alerts
        budgets.create_budget(tenant_id=TENANT, period="day",
                              unit="request", hard_limit=10, soft_limit=2,
                              created_by="admin")
        for _ in range(2):
            call = metering.begin_call(_ctx())
            metering.settle_call(call, Settlement(ok=True))
        # 第三次 begin 触发软阈值检查（消耗 2 ≥ 2）
        metering.begin_call(_ctx())
        rows = store._conn.execute(
            "SELECT * FROM governance_alert_v1 WHERE"
            " rule_id='budget_soft_limit'").fetchall()
        assert len(rows) >= 1
        assert rows[0]["severity"] == "warning"

    def test_scoped_budget_does_not_leak_across_principal(self, services):
        _, budgets, metering = services
        budgets.create_budget(tenant_id=TENANT, period="day",
                              unit="request", hard_limit=1,
                              principal_id="svc-a", created_by="admin")
        call = metering.begin_call(_ctx(principal_id="svc-a"))
        metering.settle_call(call, Settlement(ok=True))
        with pytest.raises(ModelBudgetExhausted):
            metering.begin_call(_ctx(principal_id="svc-a"))
        # 其它 principal 不受该预算约束
        ok = metering.begin_call(_ctx(principal_id="svc-b"))
        assert ok


class TestCostAndMonitoring:
    def test_no_rate_card_cost_marked_unknown(self, services):
        _, _, metering = services
        call = metering.begin_call(_ctx())
        metering.settle_call(call, Settlement(ok=True, input_tokens=10,
                                              compute_ms=5))
        summary = metering.summary(tenant_id=TENANT)
        assert summary["cost"]["status"] == "unknown"
        assert summary["requests"] == 1

    def test_rate_card_snapshot_prices_usage(self, services):
        store, _, metering = services
        store._conn.execute(
            "INSERT INTO model_rate_card_v1 (rate_card_id, tenant_id,"
            " connection_id, model_id, model_revision, unit, price_minor,"
            " currency, cost_kind, effective_from, status, created_by,"
            " created_at) VALUES ('rc-1', ?, 'local-omlx',"
            " 'Qwen3-Embedding-0.6B-8bit', '', 'input_token', 5, 'CNY',"
            " 'resource_cost', '2020-01-01T00:00:00+00:00', 'active',"
            " 'admin', '2020-01-01T00:00:00+00:00')", (TENANT,))
        call = metering.begin_call(_ctx())
        metering.settle_call(call, Settlement(ok=True, input_tokens=1000,
                                              compute_ms=5))
        rows = {r["unit"]: r for r in store.list_usage_events_v2()}
        # 5/10000 * 1000 = 0.5
        assert abs(rows["input_token"]["resource_cost"] - 0.5) < 1e-9
        summary = metering.summary(tenant_id=TENANT)
        assert summary["cost"]["status"] == "measured"
        assert abs(summary["cost"]["resource_cost"] - 0.5) < 1e-9

    def test_summary_metrics_shape(self, services):
        _, budgets, metering = services
        budgets.create_budget(tenant_id=TENANT, period="day",
                              unit="request", hard_limit=100,
                              created_by="admin")
        for i in range(3):
            call = metering.begin_call(_ctx())
            metering.settle_call(call, Settlement(
                ok=i != 2, embedding_inputs=1, compute_ms=10 + i,
                error_code="" if i != 2 else "MODEL_TIMEOUT"))
        summary = metering.summary(tenant_id=TENANT)
        assert summary["requests"] == 3
        assert summary["errors"]["failed"] == 1
        assert summary["latency_ms"]["samples"] == 3
        assert summary["latency_ms"]["p50"] is not None
        assert summary["budgets"][0]["consumed"] == 3
        ts = metering.timeseries(tenant_id=TENANT)
        assert ts and ts[0].get("model_request") == 3
