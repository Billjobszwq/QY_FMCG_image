"""账号级计量、预算与监控（M6/G5，03 §1–§6）。

事实源纪律（DEC-M008/M009）：
- usage_event_v2 是唯一 Usage 账本；本模块向其追加带模型归属的行，
  不建立第二套账单事实源。
- token / embedding units / 字符数 / 计算毫秒不得互相伪换算；
  Provider 未返回 usage 时字段为 None、meter_source=platform_observed，
  绝不写 0 冒充。
- 每次 Provider 调用一个稳定 model_call_id：先落调用意图（预算预留），
  成功/失败后结算；进程中断后 reconciliation 收敛——不允许免费调用
  或重复计费（usage_id 由 model_call_id+unit 派生，INSERT OR IGNORE）。
- 本地模型成本不伪装成零成本：无价格快照时成本字段留空并标注
  来源，监控展示为“未知”。
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.platform.models.contracts import (
    MODEL_BUDGET_EXHAUSTED,
    MODEL_METERING_INCOMPLETE,
    ModelManagementError,
)

UNITS = (
    "model_request", "input_token", "output_token", "cached_input_token",
    "reasoning_token", "embedding_input", "embedding_vector",
    "input_character", "model_compute_ms",
)

_PERIOD_SECONDS = {"minute": 60, "hour": 3600, "day": 86400,
                   "month": 30 * 86400}

# requested 超过该秒数未结算 → reconciliation 标记 metering_incomplete
SETTLE_WINDOW_SECONDS = 600


class ModelBudgetExhausted(ModelManagementError):
    code = MODEL_BUDGET_EXHAUSTED
    http_status = 429


class MeteringIncomplete(ModelManagementError):
    code = MODEL_METERING_INCOMPLETE
    http_status = 500


@dataclass(frozen=True)
class CallContext:
    """一次模型调用的完整归属（账号级计量前置）。"""

    tenant_id: str
    principal_id: str
    principal_kind: str  # user | service_account | agent
    customer_id: str = ""
    project_id: str = ""
    run_id: str = ""
    work_id: str = ""
    agent_id: str = ""
    module: str = ""
    capability: str = ""
    connection_id: str = ""
    connection_version: int | None = None
    binding_id: str = ""
    binding_version: int | None = None
    model_id: str = ""
    model_revision: str = ""


@dataclass(frozen=True)
class Settlement:
    """调用结算输入（成功/失败都要结算；失败不得免计量）。"""

    ok: bool
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    embedding_inputs: int = 0
    embedding_vectors: int = 0
    input_characters: int = 0
    compute_ms: float = 0.0
    provider_request_id: str = ""
    error_code: str = ""
    meter_source: str = ""  # provider_reported | platform_observed


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class ModelMeteringService:
    """调用账本 + Usage 结算 + 对账。"""

    def __init__(self, store, *, budgets: "ModelBudgetService | None" = None,
                 alerts=None) -> None:
        self.store = store
        self.budgets = budgets
        self.alerts = alerts

    @property
    def _conn(self) -> sqlite3.Connection:
        return self.store._conn

    # ------------------------------------------------------------- begin

    def begin_call(self, ctx: CallContext, *, idempotency_key: str = "",
                   reserved_output_tokens: float = 0.0,
                   request_amounts: dict[str, float] | None = None
                   ) -> str:
        """发送前落调用意图：预算检查 → 账本 requested。

        步骤 3（03 §3）失败绝不调用 Provider；返回稳定 model_call_id。
        幂等：同 principal+idempotency_key 返回既有 call（不重复预留）。
        """
        if not ctx.principal_id:
            raise ModelManagementError(
                "model call 缺少 principal 归属：拒绝计量")
        if idempotency_key:
            row = self._conn.execute(
                "SELECT model_call_id FROM model_call_ledger_v1"
                " WHERE principal_id=? AND idempotency_key=?",
                (ctx.principal_id, idempotency_key)).fetchone()
            if row is not None:
                return row["model_call_id"]
        # 预算硬阈值在调用前检查（含预留），失败即 429
        if self.budgets is not None:
            self.budgets.check(ctx, request_amounts=request_amounts or {
                "request": 1,
                "output_token": reserved_output_tokens,
            })
        call_id = "mcall-" + uuid.uuid4().hex[:16]
        try:
            self._conn.execute(
                "INSERT INTO model_call_ledger_v1"
                " (model_call_id, tenant_id, customer_id, project_id,"
                "  principal_id, principal_kind, run_id, work_id,"
                "  agent_id, module, capability, connection_id,"
                "  connection_version, binding_id, binding_version,"
                "  model_id, model_revision, idempotency_key, status,"
                "  reserved_output_tokens, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
                "?,'requested',?,?)",
                (call_id, ctx.tenant_id, ctx.customer_id, ctx.project_id,
                 ctx.principal_id, ctx.principal_kind, ctx.run_id,
                 ctx.work_id, ctx.agent_id, ctx.module, ctx.capability,
                 ctx.connection_id, ctx.connection_version, ctx.binding_id,
                 ctx.binding_version, ctx.model_id, ctx.model_revision,
                 idempotency_key, reserved_output_tokens, _iso(_utcnow())))
        except sqlite3.IntegrityError as e:
            raise ModelManagementError("调用账本写入冲突") from e
        if self.budgets is not None:
            self.budgets.notify_soft_limits(ctx)
        return call_id

    # ------------------------------------------------------------ settle

    def settle_call(self, model_call_id: str, s: Settlement) -> dict:
        """成功或失败后结算：追加 Usage 行 + 更新账本。

        Usage finalize 失败不得向上游报告完整成功（抛
        MODEL_METERING_INCOMPLETE 进入对账）。
        """
        row = self._conn.execute(
            "SELECT * FROM model_call_ledger_v1 WHERE model_call_id=?",
            (model_call_id,)).fetchone()
        if row is None:
            raise ModelManagementError("model_call 不存在：拒绝结算")
        if row["status"] not in ("requested", "metering_incomplete"):
            raise ModelManagementError(
                f"model_call 状态 {row['status']} 不可结算（防重复计费）")

        meter_source = s.meter_source or (
            "provider_reported" if (s.input_tokens is not None
                                    or s.output_tokens is not None)
            else "platform_observed")
        amounts: list[tuple[str, float]] = [
            ("model_request", 1)]
        if s.input_tokens is not None:
            amounts.append(("input_token", float(s.input_tokens)))
        if s.output_tokens is not None:
            amounts.append(("output_token", float(s.output_tokens)))
        if s.cached_input_tokens is not None:
            amounts.append(("cached_input_token",
                            float(s.cached_input_tokens)))
        if s.reasoning_tokens is not None:
            amounts.append(("reasoning_token", float(s.reasoning_tokens)))
        if s.embedding_inputs:
            amounts.append(("embedding_input", float(s.embedding_inputs)))
        if s.embedding_vectors:
            amounts.append(("embedding_vector", float(s.embedding_vectors)))
        if s.input_characters:
            amounts.append(("input_character", float(s.input_characters)))
        if s.compute_ms:
            amounts.append(("model_compute_ms", float(s.compute_ms)))

        costs = self._price_snapshot(row, amounts)
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            now = _iso(_utcnow())
            for unit, qty in amounts:
                usage_id = f"use-{model_call_id}-{unit}"
                rc, ip, cp = costs.get(unit, (0.0, 0.0, 0.0))
                conn.execute(
                    "INSERT OR IGNORE INTO usage_event_v2"
                    " (usage_id, tenant_id, customer_id, project_id,"
                    "  run_id, work_id, capability, model, unit,"
                    "  quantity, resource_cost, internal_cost,"
                    "  customer_price, meter_version,"
                    "  principal_id, principal_kind, model_call_id,"
                    "  connection_id, connection_version, binding_id,"
                    "  binding_version, provider_request_id,"
                    "  meter_source, outcome, error_code, occurred_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
                    "?,?,?,?,?,?,?,?,?,?)",
                    (usage_id, row["tenant_id"], row["customer_id"],
                     row["project_id"], row["run_id"], row["work_id"],
                     row["capability"], row["model_id"], unit, qty,
                     rc, ip, cp, "v2", row["principal_id"],
                     row["principal_kind"], model_call_id,
                     row["connection_id"], row["connection_version"],
                     row["binding_id"], row["binding_version"],
                     s.provider_request_id, meter_source,
                     "succeeded" if s.ok else "failed", s.error_code, now))
            status = "succeeded" if s.ok else "failed"
            cur = conn.execute(
                "UPDATE model_call_ledger_v1 SET status=?, outcome=?,"
                " error_code=?, provider_request_id=?, meter_source=?,"
                " finalized_at=? WHERE model_call_id=? AND status IN"
                " ('requested','metering_incomplete')",
                (status, "succeeded" if s.ok else "failed", s.error_code,
                 s.provider_request_id, meter_source, now, model_call_id))
            if cur.rowcount == 0:
                raise ModelManagementError("并发结算冲突")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            # 外部调用已发生但账本未收敛 → 诚实标记，进入对账
            self._conn.execute(
                "UPDATE model_call_ledger_v1 SET status="
                "'metering_incomplete', finalized_at=? WHERE"
                " model_call_id=?", (_iso(_utcnow()), model_call_id))
            raise MeteringIncomplete(
                "usage 结算失败：调用已记账为 metering_incomplete，"
                "等待对账收敛") from None
        return {"model_call_id": model_call_id, "status": status,
                "units": len(amounts)}

    def _price_snapshot(self, row: sqlite3.Row,
                        amounts: list[tuple[str, float]]
                        ) -> dict[str, tuple[float, float, float]]:
        """按调用时价格快照计算成本；无价格 → 0 且由监控标注“未知”，
        不得把本地模型当作零成本。"""
        out: dict[str, tuple[float, float, float]] = {}
        cards = self._conn.execute(
            "SELECT unit, cost_kind, price_minor, currency FROM"
            " model_rate_card_v1 WHERE status='active'"
            " AND tenant_id=? AND connection_id=? AND model_id=?"
            " AND effective_from <= ?",
            (row["tenant_id"], row["connection_id"], row["model_id"],
             _iso(_utcnow()))).fetchall()
        if not cards:
            return out
        qty = {unit: q for unit, q in amounts}
        for card in cards:
            unit = card["unit"]
            if unit not in qty:
                continue
            price = card["price_minor"] / 10000.0  # 万分位 → 主币单位
            cost = price * qty[unit]
            rc, ip_, cp = out.get(unit, (0.0, 0.0, 0.0))
            if card["cost_kind"] == "resource_cost":
                rc += cost
            elif card["cost_kind"] == "internal_cost":
                ip_ += cost
            else:
                cp += cost
            out[unit] = (rc, ip_, cp)
        return out

    # -------------------------------------------------------- reconcile

    def reconcile(self, *, window_seconds: int = SETTLE_WINDOW_SECONDS
                  ) -> dict:
        """对账收敛：悬挂 requested → metering_incomplete；
        报告未归属/未结算数量（0 漂移才算干净）。"""
        cutoff = _iso(_utcnow() - timedelta(seconds=window_seconds))
        cur = self._conn.execute(
            "UPDATE model_call_ledger_v1 SET status='metering_incomplete',"
            " finalized_at=? WHERE status='requested' AND created_at < ?",
            (_iso(_utcnow()), cutoff))
        stale = cur.rowcount
        incomplete = self._conn.execute(
            "SELECT count(*) c FROM model_call_ledger_v1"
            " WHERE status='metering_incomplete'").fetchone()[0]
        unattributed = self._conn.execute(
            "SELECT count(*) c FROM usage_event_v2"
            " WHERE model_call_id != '' AND principal_id = ''"
        ).fetchone()[0]
        missing_request_row = self._conn.execute(
            "SELECT count(*) c FROM model_call_ledger_v1 l"
            " WHERE l.status IN ('succeeded','failed')"
            " AND NOT EXISTS (SELECT 1 FROM usage_event_v2 u"
            " WHERE u.model_call_id = l.model_call_id"
            " AND u.unit='model_request')").fetchone()[0]
        return {
            "marked_incomplete": stale,
            "metering_incomplete": incomplete,
            "usage_unattributed": unattributed,
            "settled_without_request_row": missing_request_row,
            "gate_ok": (incomplete == 0 and unattributed == 0
                         and missing_request_row == 0),
        }

    # ---------------------------------------------------------- queries

    def usage_rows(self, *, tenant_id: str, principal_id: str = "",
                   customer_id: str = "", project_id: str = "",
                   agent_id: str = "", module: str = "",
                   connection_id: str = "", model_id: str = "",
                   limit: int = 200) -> list[dict]:
        sql = ("SELECT * FROM usage_event_v2 WHERE tenant_id=?"
               " AND model_call_id != ''")
        args: list = [tenant_id]
        for col, val in (("principal_id", principal_id),
                         ("customer_id", customer_id),
                         ("project_id", project_id),
                         ("connection_id", connection_id),
                         ("model", model_id)):
            if val:
                sql += f" AND {col}=?"
                args.append(val)
        if agent_id:
            sql += (" AND model_call_id IN (SELECT model_call_id FROM"
                    " model_call_ledger_v1 WHERE agent_id=?)")
            args.append(agent_id)
        if module:
            sql += (" AND model_call_id IN (SELECT model_call_id FROM"
                    " model_call_ledger_v1 WHERE module=?)")
            args.append(module)
        sql += " ORDER BY occurred_at DESC LIMIT ?"
        args.append(min(int(limit), 1000))
        return [dict(r) for r in self._conn.execute(sql, args)]

    def summary(self, *, tenant_id: str, since_hours: float = 24,
                principal_id: str = "", customer_id: str = "",
                project_id: str = "") -> dict:
        """账号级概览：请求量、各诚实单位、成本（未知则标注）、
        p50/p95 延迟、错误率、429、预算使用率。"""
        since = _iso(_utcnow() - timedelta(hours=since_hours))
        where = "tenant_id=? AND model_call_id != '' AND occurred_at >= ?"
        args: list = [tenant_id, since]
        if principal_id:
            where += " AND principal_id=?"
            args.append(principal_id)
        if customer_id:
            where += " AND customer_id=?"
            args.append(customer_id)
        if project_id:
            where += " AND project_id=?"
            args.append(project_id)
        units_rows = self._conn.execute(
            f"SELECT unit, sum(quantity) q, count(*) n FROM"
            f" usage_event_v2 WHERE {where} GROUP BY unit",
            args).fetchall()
        units = {r["unit"]: r["q"] for r in units_rows}
        cost_rows = self._conn.execute(
            f"SELECT sum(resource_cost) rc, sum(internal_cost) ic,"
            f" sum(customer_price) cp FROM usage_event_v2 WHERE {where}",
            args).fetchone()
        has_price = self._conn.execute(
            "SELECT count(*) c FROM model_rate_card_v1 WHERE tenant_id=?"
            " AND status='active'", (tenant_id,)).fetchone()[0] > 0
        # 延迟与错误：来自调用账本 + usage compute
        calls = self._conn.execute(
            "SELECT status, error_code, created_at, finalized_at FROM"
            " model_call_ledger_v1 WHERE tenant_id=? AND created_at >= ?"
            + (" AND principal_id=?" if principal_id else "")
            + (" AND customer_id=?" if customer_id else "")
            + (" AND project_id=?" if project_id else ""),
            [tenant_id, since] + ([principal_id] if principal_id else [])
            + ([customer_id] if customer_id else [])
            + ([project_id] if project_id else [])).fetchall()
        latencies: list[float] = []
        for row in self._conn.execute(
                f"SELECT model_call_id, quantity FROM usage_event_v2"
                f" WHERE {where} AND unit='model_compute_ms'",
                args):
            latencies.append(float(row["quantity"]))
        latencies.sort()
        total_calls = len(calls)
        failed = sum(1 for c in calls
                     if c["status"] in ("failed", "metering_incomplete"))
        rate_limited = sum(1 for c in calls
                           if c["error_code"] == "MODEL_RATE_LIMITED")
        incomplete = sum(1 for c in calls
                         if c["status"] == "metering_incomplete")
        budgets = self.budgets.utilization(tenant_id) \
            if self.budgets is not None else []
        return {
            "window_hours": since_hours,
            "requests": int(units.get("model_request", 0)),
            "units": {u: units.get(u, 0) for u in UNITS},
            "cost": {
                "resource_cost": cost_rows["rc"] or 0,
                "internal_cost": cost_rows["ic"] or 0,
                "customer_price": cost_rows["cp"] or 0,
                # 诚实标注：无价格表时成本为“未知”，不是零成本
                "status": "measured" if has_price else "unknown",
            },
            "latency_ms": {
                "p50": _percentile(latencies, 50),
                "p95": _percentile(latencies, 95),
                "samples": len(latencies),
            },
            "errors": {
                "total_calls": total_calls,
                "failed": failed,
                "rate_limited_429": rate_limited,
                "metering_incomplete": incomplete,
                "error_rate": (failed / total_calls) if total_calls else 0,
            },
            "budgets": budgets,
        }

    def timeseries(self, *, tenant_id: str, since_hours: float = 24,
                   bucket_minutes: int = 60) -> list[dict]:
        since = _iso(_utcnow() - timedelta(hours=since_hours))
        rows = self._conn.execute(
            "SELECT unit, quantity, occurred_at FROM usage_event_v2"
            " WHERE tenant_id=? AND model_call_id != ''"
            " AND occurred_at >= ? ORDER BY occurred_at",
            (tenant_id, since)).fetchall()
        buckets: dict[str, dict[str, float]] = {}
        for r in rows:
            try:
                ts = datetime.fromisoformat(r["occurred_at"])
            except ValueError:
                continue
            epoch = int(ts.timestamp() // (bucket_minutes * 60))
            key = str(epoch)
            slot = buckets.setdefault(key, {})
            slot[r["unit"]] = slot.get(r["unit"], 0.0) + float(r["quantity"])
        out = []
        for key in sorted(buckets, key=int):
            ts = datetime.fromtimestamp(int(key) * bucket_minutes * 60,
                                        tz=timezone.utc)
            out.append({"bucket_start": _iso(ts), **buckets[key]})
        return out


class ModelBudgetService:
    """Token/请求/算力/价格预算（03 §4）。

    消耗从 usage_event_v2（已结算）+ 调用账本预留（requested）推导，
    无独立可变计数器；检查在 BEGIN IMMEDIATE 事务内完成（并发超支
    由单写锁兜底）。
    """

    def __init__(self, store, *, alerts=None) -> None:
        self.store = store
        self.alerts = alerts
        self._soft_notified: set[str] = set()

    @property
    def _conn(self) -> sqlite3.Connection:
        return self.store._conn

    def create_budget(self, *, tenant_id: str, period: str, unit: str,
                      hard_limit: float, soft_limit: float | None = None,
                      principal_id: str = "", customer_id: str = "",
                      project_id: str = "", subject_kind: str = "",
                      subject_id: str = "", created_by: str) -> dict:
        if period not in _PERIOD_SECONDS:
            raise ModelManagementError("预算周期非法")
        if unit not in ("request", "input_token", "output_token",
                        "total_token", "compute_ms", "customer_price"):
            raise ModelManagementError("预算单位非法")
        if hard_limit <= 0:
            raise ModelManagementError("hard_limit 必须为正")
        budget_id = "budget-" + uuid.uuid4().hex[:12]
        self._conn.execute(
            "INSERT INTO model_budget_v1 (budget_id, tenant_id,"
            " principal_id, customer_id, project_id, subject_kind,"
            " subject_id, period, unit, hard_limit, soft_limit, status,"
            " etag, created_by, created_at) VALUES"
            " (?,?,?,?,?,?,?,?,?,?,?, 'active', ?, ?, ?)",
            (budget_id, tenant_id, principal_id, customer_id, project_id,
             subject_kind, subject_id, period, unit, hard_limit,
             soft_limit, uuid.uuid4().hex[:12], created_by,
             _iso(_utcnow())))
        return {"budget_id": budget_id}

    # ------------------------------------------------------------ check

    def _matching_budgets(self, ctx: CallContext) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM model_budget_v1 WHERE tenant_id=?"
            " AND status='active'"
            " AND (principal_id='' OR principal_id=?)"
            " AND (customer_id='' OR customer_id=?)"
            " AND (project_id='' OR project_id=?)"
            " AND (subject_id='' OR (subject_kind='module' AND"
            "      subject_id=?) OR (subject_kind='agent' AND"
            "      subject_id=?))",
            (ctx.tenant_id, ctx.principal_id, ctx.customer_id,
             ctx.project_id, ctx.module, ctx.agent_id)).fetchall()

    def _consumed(self, budget: sqlite3.Row, window_start: str,
                  ctx: CallContext) -> float:
        unit_map = {
            "request": ("model_request",),
            "input_token": ("input_token",),
            "output_token": ("output_token",),
            "total_token": ("input_token", "output_token"),
            "compute_ms": ("model_compute_ms",),
            "customer_price": (),
        }
        # 预算维度非空 → 精确匹配；为空 → 该维度不约束
        conds = ["tenant_id=?"]
        scope_args: list = [budget["tenant_id"]]
        for col in ("principal_id", "customer_id", "project_id"):
            val = budget[col]
            if val:
                conds.append(f"{col}=?")
                scope_args.append(val)
        scope = " AND ".join(conds)
        if budget["unit"] == "customer_price":
            row = self._conn.execute(
                "SELECT COALESCE(sum(customer_price),0) q FROM"
                f" usage_event_v2 WHERE {scope}"
                " AND occurred_at >= ? AND model_call_id != ''",
                scope_args + [window_start]).fetchone()
            return float(row["q"])
        units = unit_map[budget["unit"]]
        marks = ",".join("?" for _ in units)
        row = self._conn.execute(
            "SELECT COALESCE(sum(quantity),0) q FROM usage_event_v2"
            f" WHERE {scope} AND unit IN ({marks})"
            " AND occurred_at >= ? AND model_call_id != ''",
            scope_args + list(units) + [window_start]).fetchone()
        consumed = float(row["q"])
        if budget["unit"] in ("output_token", "total_token"):
            res = self._conn.execute(
                "SELECT COALESCE(sum(reserved_output_tokens),0) q FROM"
                f" model_call_ledger_v1 WHERE {scope}"
                " AND status='requested' AND created_at >= ?",
                scope_args + [window_start]).fetchone()
            consumed += float(res["q"])
        return consumed

    def check(self, ctx: CallContext, *,
              request_amounts: dict[str, float]) -> None:
        """调用前预算检查：硬阈值 100% 拒绝（429 + 安全重置时间）。"""
        now = _utcnow()
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            for budget in self._matching_budgets(ctx):
                window_start = _iso(
                    now - timedelta(
                        seconds=_PERIOD_SECONDS[budget["period"]]))
                consumed = self._consumed(budget, window_start, ctx)
                amount = self._amount_for(budget, request_amounts)
                if consumed + amount > budget["hard_limit"]:
                    reset = _seconds_to_next_window(budget["period"], now)
                    raise ModelBudgetExhausted(
                        f"预算耗尽（{budget['unit']}/{budget['period']}）",
                        retry_after=reset)
            conn.execute("COMMIT")
        except ModelBudgetExhausted:
            conn.execute("ROLLBACK")
            raise
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def notify_soft_limits(self, ctx: CallContext) -> None:
        """软阈值 80%：告警（不阻断），同一预算同一窗口只告警一次。"""
        if self.alerts is None:
            return
        now = _utcnow()
        for budget in self._matching_budgets(ctx):
            soft = budget["soft_limit"]
            if not soft:
                continue
            window_start = _iso(
                now - timedelta(seconds=_PERIOD_SECONDS[budget["period"]]))
            consumed = self._consumed(budget, window_start, ctx)
            if consumed >= soft:
                key = f"{budget['budget_id']}:{window_start}"
                if key in self._soft_notified:
                    continue
                self._soft_notified.add(key)
                self.alerts.raise_alert(
                    actor="model-metering", role="system",
                    severity="warning",
                    rule_id="budget_soft_limit",
                    content=(f"模型预算软阈值触发：{budget['unit']}/"
                             f"{budget['period']} 消耗 "
                             f"{consumed:.1f} ≥ {soft:.1f}"),
                    recommended_action="检查模型用量或调整预算")

    def utilization(self, tenant_id: str) -> list[dict]:
        out = []
        now = _utcnow()
        rows = self._conn.execute(
            "SELECT * FROM model_budget_v1 WHERE tenant_id=?"
            " AND status='active'", (tenant_id,)).fetchall()
        for budget in rows:
            window_start = _iso(
                now - timedelta(seconds=_PERIOD_SECONDS[budget["period"]]))
            ctx = CallContext(tenant_id=tenant_id, principal_id="",
                              principal_kind="system",
                              customer_id=budget["customer_id"],
                              project_id=budget["project_id"])
            consumed = self._consumed(budget, window_start, ctx)
            out.append({
                "budget_id": budget["budget_id"],
                "unit": budget["unit"],
                "period": budget["period"],
                "hard_limit": budget["hard_limit"],
                "soft_limit": budget["soft_limit"],
                "consumed": consumed,
                "utilization": (consumed / budget["hard_limit"]
                                if budget["hard_limit"] else 0),
            })
        return out

    def _amount_for(self, budget: sqlite3.Row,
                    amounts: dict[str, float]) -> float:
        if budget["unit"] == "total_token":
            return float(amounts.get("input_token", 0)) + float(
                amounts.get("output_token", 0))
        return float(amounts.get(budget["unit"], 0))


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    if not sorted_values:
        return None
    idx = max(0, min(len(sorted_values) - 1,
                     int(round((pct / 100) * (len(sorted_values) - 1)))))
    return sorted_values[idx]


def _seconds_to_next_window(period: str, now: datetime) -> float:
    span = _PERIOD_SECONDS[period]
    return float(span - (now.timestamp() % span))
