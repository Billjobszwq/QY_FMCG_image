"""ABOSV2 Phase F 红测试：财务与计费纵向切片（Gate G8）。

要求（任务书 §十/财务 + D-008）：
1. 账单只能从 immutable usage_event_v2 生成（不扫业务表凑金额），
   行可下钻到 usage/run/node/证据；
2. 月订阅 + 按照片 + 按时长混合；按客户生成；
3. 幂等：同一 period 重复生成不重复计费；
4. 价格版本绑定：新 rate card 版本不改已开票金额；
5. 调整 append-only（reversal/折扣带原因），不删除 Usage；
6. 作用域：他客户 contract 不可用于本客户账单。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.control_plane import CommandGateway
from src.platform.finance import FinanceError, FinanceService


class _FakeRec:
    def recognize(self, data: bytes, conf: float = 0.25):
        return {"count": 1, "products": [{"name": "X", "count": 1}]}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "v2-admin-pw")
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=_FakeRec(), probe=lambda spec: None)
    profiles = build_profiles_service(bundle)
    gateway = CommandGateway(bundle.store, profiles,
                             recognition_adapter=_FakeRec())
    fin = FinanceService(bundle.store)
    # 造 usage：cust-a 两次识别
    run_ids = []
    for i in range(2):
        out = gateway.submit(
            command_kind="vision.recognition.create",
            params={"images": [[f"p{i}.jpg", b"\xff\xd8fake"]]},
            actor="admin", source="api", customer_id="cust-a",
            project_id="pj-a")
        assert out["status"] == "succeeded"
        run_ids.append(out["run_id"])
    # cust-b 一次识别
    gateway.submit(command_kind="vision.recognition.create",
                   params={"images": [["b.jpg", b"\xff\xd8fake"]]},
                   actor="admin", source="api", customer_id="cust-b")
    return {"store": bundle.store, "fin": fin, "gateway": gateway,
            "run_ids": run_ids}


def _period() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m")


class TestInvoiceFromImmutableUsage:
    def test_invoice_lines_from_usage_with_drilldown(self, env):
        fin = env["fin"]
        ct = fin.create_contract(customer_id="cust-a")
        inv = fin.generate_invoice(customer_id="cust-a",
                                   period=_period(),
                                   contract_id=ct["contract_id"],
                                   actor="admin")
        units = {l["unit"] for l in inv["lines"]}
        assert {"subscription_month", "recognition_photo",
                "model_compute_ms"} <= units
        photo_line = next(l for l in inv["lines"]
                          if l["unit"] == "recognition_photo")
        assert photo_line["quantity"] == 2.0          # 两次识别各 1 张
        assert photo_line["amount"] == 2.0 * 0.5
        # 下钻到 usage/run/node/证据
        dd = photo_line["drilldown"]
        assert {d["run_id"] for d in dd} == set(env["run_ids"])
        assert all(d["node"] == "recognition" for d in dd)
        assert all(d["source_evidence"].startswith("recognition_task:")
                   for d in dd)
        # 总额 = 各行之和
        assert inv["total"] == round(
            sum(l["amount"] for l in inv["lines"]), 4)

    def test_idempotent_generation_same_period(self, env):
        fin = env["fin"]
        inv1 = fin.generate_invoice(customer_id="cust-a",
                                    period=_period(), actor="admin")
        inv2 = fin.generate_invoice(customer_id="cust-a",
                                    period=_period(), actor="admin")
        photo1 = next(l for l in inv1["lines"]
                      if l["unit"] == "recognition_photo")
        # 第二次：已计费 usage 跳过 → 仅订阅行
        assert all(l["unit"] != "recognition_photo"
                   for l in inv2["lines"])
        assert photo1["quantity"] == 2.0

    def test_customer_scope_isolation(self, env):
        fin = env["fin"]
        ct_b = fin.create_contract(customer_id="cust-b")
        with pytest.raises(FinanceError):
            fin.generate_invoice(customer_id="cust-a",
                                 period=_period(),
                                 contract_id=ct_b["contract_id"],
                                 actor="admin")
        inv_b = fin.generate_invoice(customer_id="cust-b",
                                     period=_period(),
                                     contract_id=ct_b["contract_id"],
                                     actor="admin")
        photo_b = next(l for l in inv_b["lines"]
                       if l["unit"] == "recognition_photo")
        assert photo_b["quantity"] == 1.0


class TestPriceVersionAndAdjustments:
    def test_new_rate_card_version_does_not_change_issued_invoice(
            self, env):
        fin = env["fin"]
        inv = fin.generate_invoice(customer_id="cust-a",
                                   period=_period(), actor="admin")
        issued = fin.issue_invoice(inv["invoice_id"], actor="admin")
        original_total = issued["total"]
        # 涨价：新版本价格翻倍
        fin.new_rate_card_version(
            "rc_standard", actor="admin", lines=[
                {"unit": "subscription_month", "price": 200.0},
                {"unit": "recognition_photo", "price": 1.0},
                {"unit": "model_compute_ms", "price": 0.002}])
        after = fin.get_invoice(inv["invoice_id"])
        assert after["total"] == original_total, "已开票金额不得随新价格变动"
        assert after["rate_card_version"] == 1

    def test_adjustments_append_only_and_reason_required(self, env):
        fin = env["fin"]
        inv = fin.generate_invoice(customer_id="cust-a",
                                   period=_period(), actor="admin")
        fin.issue_invoice(inv["invoice_id"], actor="admin")
        with pytest.raises(FinanceError):
            fin.adjust_invoice(inv["invoice_id"], kind="discount",
                               amount=-5.0, reason="", actor="admin")
        out = fin.adjust_invoice(inv["invoice_id"], kind="discount",
                                 amount=-5.0, reason="首月优惠",
                                 actor="admin")
        assert out["net_total"] == round(out["total"] - 5.0, 4)
        assert out["adjustments"][0]["reason"] == "首月优惠"
        # append-only：usage 与调整都不得删改
        with pytest.raises(Exception):
            env["store"]._conn.execute("DELETE FROM fin_adjustment_v1")
        with pytest.raises(Exception):
            env["store"]._conn.execute(
                "UPDATE usage_event_v2 SET quantity=0")
        # 结算后不得再调整
        fin.settle_invoice(inv["invoice_id"], actor="admin")
        with pytest.raises(FinanceError):
            fin.adjust_invoice(inv["invoice_id"], kind="reversal",
                               amount=-1.0, reason="x", actor="admin")

    def test_issue_gate(self, env):
        fin = env["fin"]
        inv = fin.generate_invoice(customer_id="cust-a",
                                   period=_period(), actor="admin")
        assert inv["status"] == "draft"
        issued = fin.issue_invoice(inv["invoice_id"], actor="admin")
        assert issued["status"] == "issued" and issued["issued_at"]
        with pytest.raises(FinanceError):
            fin.issue_invoice(inv["invoice_id"], actor="admin")
