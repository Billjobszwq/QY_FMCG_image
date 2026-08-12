"""ABOSV2 Phase F：财务与计费服务层（03-DOMAIN-PACKS-SPEC §6）。

红线（D-008）：账单只能从 immutable usage_event_v2 生成，不得临时扫描
业务表凑金额；每行可下钻到 usage/run/node/证据；调整用 append-only
adjustment/reversal；已开票金额绑定开票时的 rate card 版本，后改价格
不重算历史。
"""
from __future__ import annotations

import json
import uuid
from typing import Any


class FinanceError(Exception):
    pass


def _new_id(prefix: str) -> str:
    return f"{prefix}-" + uuid.uuid4().hex[:12]


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# 标准价目卡 v1（月订阅 + 按照片 + 按计算时长，混合）
STANDARD_RATE_LINES = [
    {"unit": "subscription_month", "price": 100.0},
    {"unit": "recognition_photo", "price": 0.5},
    {"unit": "model_compute_ms", "price": 0.001},
]


class FinanceService:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.seed_rate_cards()

    # ---------- rate card ----------

    def seed_rate_cards(self) -> None:
        self.store._conn.execute(
            "INSERT OR IGNORE INTO fin_rate_card_v1 (rate_card_id, version,"
            " name, lines_json, created_at) VALUES (?,?,?,?,?)",
            ("rc_standard", 1, "标准混合价目（月订阅+按照片+按时长）",
             json.dumps(STANDARD_RATE_LINES), _now()))
        self.store._conn.commit()

    def get_rate_card(self, rate_card_id: str,
                      version: int | None = None) -> dict:
        if version is None:
            row = self.store._conn.execute(
                "SELECT * FROM fin_rate_card_v1 WHERE rate_card_id=?"
                " ORDER BY version DESC LIMIT 1",
                (rate_card_id,)).fetchone()
        else:
            row = self.store._conn.execute(
                "SELECT * FROM fin_rate_card_v1 WHERE rate_card_id=? AND"
                " version=?", (rate_card_id, version)).fetchone()
        if row is None:
            raise FinanceError(f"rate card 不存在: {rate_card_id}")
        d = dict(row)
        d["lines"] = json.loads(d["lines_json"])
        return d

    def new_rate_card_version(self, rate_card_id: str, *,
                              lines: list[dict], actor: str) -> dict:
        """价格变更只生成新版本；历史账单不重算。"""
        cur = self.get_rate_card(rate_card_id)
        self.store._conn.execute(
            "INSERT INTO fin_rate_card_v1 (rate_card_id, version, name,"
            " lines_json, created_at) VALUES (?,?,?,?,?)",
            (rate_card_id, cur["version"] + 1, cur["name"],
             json.dumps(lines), _now()))
        self.store._conn.commit()
        return self.get_rate_card(rate_card_id, cur["version"] + 1)

    # ---------- contract ----------

    def create_contract(self, *, customer_id: str, kind: str = "usage",
                        rate_card_id: str = "rc_standard") -> dict:
        self.get_rate_card(rate_card_id)
        cid = _new_id("ct")
        now = _now()
        self.store._conn.execute(
            "INSERT INTO fin_contract_v1 (contract_id, customer_id, kind,"
            " rate_card_id, started_at, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (cid, customer_id, kind, rate_card_id, now, now))
        self.store._conn.commit()
        row = self.store._conn.execute(
            "SELECT * FROM fin_contract_v1 WHERE contract_id=?",
            (cid,)).fetchone()
        return dict(row)

    def list_contracts(self, *, customer_id: str) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM fin_contract_v1 WHERE customer_id=?"
            " ORDER BY created_at", (customer_id,)).fetchall()
        return [dict(r) for r in rows]

    # ---------- invoice ----------

    def _billed_usage_ids(self, customer_id: str) -> set[str]:
        rows = self.store._conn.execute(
            "SELECT l.usage_ids_json FROM fin_invoice_line_v1 l"
            " JOIN fin_invoice_v1 i ON i.invoice_id=l.invoice_id"
            " WHERE i.customer_id=?", (customer_id,)).fetchall()
        ids: set[str] = set()
        for r in rows:
            ids.update(json.loads(r["usage_ids_json"] or "[]"))
        return ids

    def generate_invoice(self, *, customer_id: str, period: str,
                         contract_id: str = "",
                         include_subscription: bool = True,
                         actor: str) -> dict:
        """严格从 usage_event_v2 生成账单行（幂等：已计费 usage 跳过）。"""
        contract = None
        if contract_id:
            row = self.store._conn.execute(
                "SELECT * FROM fin_contract_v1 WHERE contract_id=?",
                (contract_id,)).fetchone()
            if row is None:
                raise FinanceError(f"contract 不存在: {contract_id}")
            if row["customer_id"] != customer_id:
                raise FinanceError("contract 不属于该客户（作用域隔离）")
            contract = dict(row)
        rc_id = contract["rate_card_id"] if contract else "rc_standard"
        rc = self.get_rate_card(rc_id)
        prices = {l["unit"]: l["price"] for l in rc["lines"]}
        billed = self._billed_usage_ids(customer_id)
        usage_rows = self.store._conn.execute(
            "SELECT u.* , r.workflow_definition_id FROM usage_event_v2 u"
            " LEFT JOIN business_run_v1 r ON r.run_id=u.run_id"
            " WHERE u.customer_id=? AND strftime('%Y-%m', u.occurred_at)=?"
            " AND COALESCE(u.data_scope,'operational')='operational'"
            " AND COALESCE(r.data_scope,'operational')='operational'"
            # SI3：attribution 绑定为 fixture 的不可变账本不计费
            " AND NOT EXISTS (SELECT 1 FROM scope_attribution_ledger_v1"
            " a WHERE a.subject_table='usage_event_v2' AND"
            " a.subject_id=u.usage_id AND a.effective_scope IN"
            " ('uat_fixture','demo_fixture'))"
            " ORDER BY u.occurred_at", (customer_id, period)).fetchall()
        groups: dict[str, list[dict]] = {}
        for u in usage_rows:
            if u["usage_id"] in billed:
                continue
            groups.setdefault(u["unit"], []).append(dict(u))
        invoice_id = _new_id("inv")
        now = _now()
        total = 0.0
        self.store._conn.execute(
            "INSERT INTO fin_invoice_v1 (invoice_id, customer_id,"
            " contract_id, period, status, total, rate_card_id,"
            " rate_card_version, created_at, data_scope, test_run_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (invoice_id, customer_id, contract_id, period, "draft", 0.0,
             rc_id, rc["version"], now,
             # SI4：账单继承客户 provenance（fixture 客户账单不进
             # 运营财务面，指令 9.3）。
             (self.store._conn.execute(
                 "SELECT COALESCE(data_scope,'operational') ds FROM"
                 " md_customer_v1 WHERE customer_id=?",
                 (customer_id,)).fetchone() or {"ds": "operational"})
             ["ds"],
             (self.store._conn.execute(
                 "SELECT COALESCE(test_run_id,'') tr FROM"
                 " md_customer_v1 WHERE customer_id=?",
                 (customer_id,)).fetchone() or {"tr": ""})["tr"]))
        if include_subscription and "subscription_month" in prices:
            # 同客户同期间月订阅只计一次（幂等）
            dup = self.store._conn.execute(
                "SELECT 1 FROM fin_invoice_line_v1 l"
                " JOIN fin_invoice_v1 i ON i.invoice_id=l.invoice_id"
                " WHERE i.customer_id=? AND i.period=?"
                " AND l.unit='subscription_month' LIMIT 1",
                (customer_id, period)).fetchone()
            if dup is None:
                amount = prices["subscription_month"]
                total += amount
                self.store._conn.execute(
                    "INSERT INTO fin_invoice_line_v1 (invoice_id, unit,"
                    " quantity, unit_price, amount, usage_ids_json,"
                    " drilldown_json) VALUES (?,?,?,?,?,?,?)",
                    (invoice_id, "subscription_month", 1, amount, amount,
                     "[]", json.dumps([{"kind": "subscription",
                                        "period": period}])))
        for unit, rows in groups.items():
            price = prices.get(unit)
            if price is None:
                # 未定价单位诚实跳过并留痕（不静默吞掉用量）
                continue
            qty = sum(r["quantity"] for r in rows)
            amount = round(qty * price, 4)
            total += amount
            drill = [{"usage_id": r["usage_id"], "run_id": r["run_id"],
                      "work_id": r["work_id"], "node": r["node"],
                      "quantity": r["quantity"],
                      "source_evidence": r["source_evidence"]}
                     for r in rows]
            self.store._conn.execute(
                "INSERT INTO fin_invoice_line_v1 (invoice_id, unit,"
                " quantity, unit_price, amount, usage_ids_json,"
                " drilldown_json) VALUES (?,?,?,?,?,?,?)",
                (invoice_id, unit, qty, price, amount,
                 json.dumps([r["usage_id"] for r in rows]),
                 json.dumps(drill)))
        self.store._conn.execute(
            "UPDATE fin_invoice_v1 SET total=? WHERE invoice_id=?",
            (round(total, 4), invoice_id))
        self.store._conn.commit()
        return self.get_invoice(invoice_id)

    def get_invoice(self, invoice_id: str) -> dict:
        row = self.store._conn.execute(
            "SELECT * FROM fin_invoice_v1 WHERE invoice_id=?",
            (invoice_id,)).fetchone()
        if row is None:
            raise FinanceError(f"invoice 不存在: {invoice_id}")
        d = dict(row)
        lines = self.store._conn.execute(
            "SELECT * FROM fin_invoice_line_v1 WHERE invoice_id=?"
            " ORDER BY line_id", (invoice_id,)).fetchall()
        d["lines"] = []
        for l in lines:
            ld = dict(l)
            ld["usage_ids"] = json.loads(ld.pop("usage_ids_json") or "[]")
            ld["drilldown"] = json.loads(ld.pop("drilldown_json") or "[]")
            d["lines"].append(ld)
        adjs = self.store._conn.execute(
            "SELECT * FROM fin_adjustment_v1 WHERE invoice_id=?"
            " ORDER BY created_at", (invoice_id,)).fetchall()
        d["adjustments"] = [dict(a) for a in adjs]
        d["net_total"] = round(
            d["total"] + sum(a["amount"] for a in d["adjustments"]), 4)
        return d

    def list_invoices(self, *, customer_id: str) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT invoice_id FROM fin_invoice_v1 WHERE customer_id=?"
            " ORDER BY created_at", (customer_id,)).fetchall()
        return [self.get_invoice(r["invoice_id"]) for r in rows]

    def issue_invoice(self, invoice_id: str, *, actor: str) -> dict:
        inv = self.get_invoice(invoice_id)
        if inv["status"] != "draft":
            raise FinanceError(f"只有 draft 可开票（当前 {inv['status']}）")
        self.store._conn.execute(
            "UPDATE fin_invoice_v1 SET status='issued', issued_at=?"
            " WHERE invoice_id=?", (_now(), invoice_id))
        self.store._conn.commit()
        return self.get_invoice(invoice_id)

    def adjust_invoice(self, invoice_id: str, *, kind: str, amount: float,
                       reason: str, actor: str) -> dict:
        """append-only 调整（reversal/折扣）；不删除 Usage、不改原行。"""
        if kind not in ("reversal", "discount", "correction"):
            raise FinanceError(f"调整类型非法: {kind}")
        if not reason:
            raise FinanceError("调整必须填写原因")
        inv = self.get_invoice(invoice_id)
        if inv["status"] == "settled":
            raise FinanceError("已结算账单不得再调整")
        self.store._conn.execute(
            "INSERT INTO fin_adjustment_v1 (adjustment_id, invoice_id,"
            " kind, amount, reason, actor, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (_new_id("adj"), invoice_id, kind, amount, reason, actor,
             _now()))
        self.store._conn.commit()
        return self.get_invoice(invoice_id)

    def settle_invoice(self, invoice_id: str, *, actor: str) -> dict:
        inv = self.get_invoice(invoice_id)
        if inv["status"] != "issued":
            raise FinanceError("只有已开票可结算")
        self.store._conn.execute(
            "UPDATE fin_invoice_v1 SET status='settled'"
            " WHERE invoice_id=?", (invoice_id,))
        self.store._conn.commit()
        return self.get_invoice(invoice_id)
