"""SI3 T1：统一执行上下文 ExecutionContext / Scope Graph V3。

取代 SI2 的"行自身列 + 补丁式绑定"模型（00-LIVE-AUDIT §5 假阳性
根因）。V3 契约（01-SCOPE-GRAPH-CONTRACT）：

- 所有模块只消费唯一 ExecutionContext；禁止各自拼装 scope SQL；
- effective scope = 行自身列 ⊕ 父链推导（run/customer/response）；
- test_run_id 必须在 uat_test_run_v1 存在且 status=current
  （archived/不存在 fail-closed）；
- 父子一致性校验六维：tenant/customer/project/data_scope/
  test_run/correlation；
- 对象创建与 scope 写入同一事务；禁止"先 commit 再 bind"；
- Test Run namespace 不可覆盖（禁止 INSERT OR REPLACE）；
- scanner fail-fast：异常即上抛，禁止 except/continue 放行。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

DATA_SCOPES = ("operational", "uat_fixture", "demo_fixture", "system",
               "archived")
FIXTURE_SCOPES = ("uat_fixture", "demo_fixture")

# 自身列口径（仅用于无需父链的简单过滤；运营查询与 Gate 必须优先
# 使用 ScopedQuery 的 effective 口径）。
OPERATIONAL_FILTER = "COALESCE(data_scope,'operational')='operational'"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScopeViolation(Exception):
    """作用域违规（fail-closed）。code 为稳定错误码。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass
class ExecutionContext:
    """一次执行/对象的结构化作用域（SI3 唯一载体，指令四.1）。

    definition_id/artifact_id/version 记录触发定义（工作流/Agent/
    模型 bundle），供审计与 Gate 回查。
    """
    tenant_id: str = "local"
    customer_id: str = ""
    project_id: str = ""
    data_scope: str = "operational"
    test_run_id: str = ""
    correlation_id: str = ""
    parent_run_id: str = ""
    actor_id: str = ""
    source: str = ""
    definition_id: str = ""
    artifact_id: str = ""
    version: str = ""
    created_at: str = field(default_factory=_now)

    def is_fixture(self) -> bool:
        return self.data_scope in FIXTURE_SCOPES

    def as_dict(self) -> dict[str, Any]:
        return {"tenant_id": self.tenant_id,
                "customer_id": self.customer_id,
                "project_id": self.project_id,
                "data_scope": self.data_scope,
                "test_run_id": self.test_run_id,
                "correlation_id": self.correlation_id,
                "parent_run_id": self.parent_run_id,
                "actor_id": self.actor_id, "source": self.source,
                "definition_id": self.definition_id,
                "artifact_id": self.artifact_id,
                "version": self.version,
                "created_at": self.created_at}


# 兼容别名：SI2 代码引用 ExecutionScopeV1。
ExecutionScopeV1 = ExecutionContext


class ScopePolicy:
    """继承与一致性校验（SI3：六维 fail-closed，指令四.3）。"""

    def validate(self, scope: ExecutionContext) -> None:
        if scope.data_scope not in DATA_SCOPES:
            raise ScopeViolation("SCOPE_UNKNOWN_DATA_SCOPE",
                                 scope.data_scope)
        if scope.is_fixture() and not scope.test_run_id:
            raise ScopeViolation("SCOPE_MISSING_TEST_RUN_ID",
                                 f"scope={scope.data_scope} 缺少"
                                 " test_run_id")

    def check_child(self, parent: ExecutionContext,
                    child: ExecutionContext) -> None:
        self.validate(child)
        if parent.is_fixture() and child.data_scope == "operational":
            raise ScopeViolation(
                "SCOPE_CONFLICT_FIXTURE_TO_OPERATIONAL",
                f"父 {parent.data_scope}/{parent.test_run_id} 不得"
                " 产生 operational 子对象")
        if parent.data_scope != child.data_scope:
            raise ScopeViolation(
                "SCOPE_CONFLICT_PARENT_CHILD",
                f"父 {parent.data_scope} ≠ 子 {child.data_scope}")
        if parent.is_fixture() and child.test_run_id \
                and child.test_run_id != parent.test_run_id:
            raise ScopeViolation(
                "SCOPE_CONFLICT_PARENT_CHILD",
                f"test_run_id 不一致: {parent.test_run_id} →"
                f" {child.test_run_id}")
        # SI3：六维一致性（tenant/customer/project/correlation）。
        for name, pv, cv in (("tenant_id", parent.tenant_id,
                              child.tenant_id),
                             ("customer_id", parent.customer_id,
                              child.customer_id),
                             ("project_id", parent.project_id,
                              child.project_id),
                             ("correlation_id", parent.correlation_id,
                              child.correlation_id)):
            if pv and cv and pv != cv:
                raise ScopeViolation(
                    "SCOPE_CONFLICT_PARENT_CHILD",
                    f"{name} 不一致: {pv} → {cv}")


class ScopeResolver:
    """服务端 scope 解析（客户端不得自证 operational，指令四.7）。

    解析顺序（SI3）：显式 test_run（registry fail-closed）→ 父 Run
    继承 → fixture 客户推导 → operational。失败路径必须先解析 scope
    再查业务定义（指令四.10）。
    """

    def __init__(self, store: Any) -> None:
        self.store = store
        self.policy = ScopePolicy()

    # ---------- Test Run registry（指令四.5/6） ----------

    def test_run_row(self, test_run_id: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM uat_test_run_v1 WHERE test_run_id=?",
            (test_run_id,)).fetchone()
        return dict(row) if row else None

    def assert_test_run_current(self, test_run_id: str, *,
                                customer_id: str = "") -> dict:
        """fail-closed：必须存在、status=current、客户归属匹配。"""
        row = self.test_run_row(test_run_id)
        if row is None:
            raise ScopeViolation("SCOPE_TEST_RUN_NOT_FOUND", test_run_id)
        if row.get("status") != "current":
            raise ScopeViolation("SCOPE_TEST_RUN_ARCHIVED",
                                 f"{test_run_id} status="
                                 f"{row.get('status')}")
        if customer_id:
            cids = json.loads(row.get("customer_ids_json") or "[]")
            if cids and customer_id not in cids:
                raise ScopeViolation(
                    "SCOPE_TEST_RUN_CUSTOMER_MISMATCH",
                    f"customer {customer_id} 不在 test_run"
                    f" {test_run_id} 登记客户集")
        return row

    # ---------- 解析 ----------

    def resolve(self, *, parent_run_id: str | None = None,
                test_run_id: str = "", customer_id: str = "",
                project_id: str = "", actor_id: str = "",
                source: str = "", correlation_id: str = "",
                tenant_id: str = "local") -> ExecutionContext:
        scope = ExecutionContext(tenant_id=tenant_id,
                                 customer_id=customer_id or "",
                                 project_id=project_id or "",
                                 actor_id=actor_id, source=source,
                                 correlation_id=correlation_id or "",
                                 parent_run_id=parent_run_id or "")
        if test_run_id:
            self.assert_test_run_current(test_run_id,
                                         customer_id=customer_id or "")
            scope.data_scope = "uat_fixture"
            scope.test_run_id = test_run_id
            self.policy.validate(scope)
            return scope
        if parent_run_id:
            parent = self.store.get_business_run(parent_run_id)
            if parent is not None:
                pctx = ExecutionContext(
                    tenant_id=parent.get("tenant_id") or "local",
                    customer_id=parent.get("customer_id") or "",
                    project_id=parent.get("project_id") or "",
                    data_scope=(parent.get("data_scope")
                                or "operational"),
                    test_run_id=parent.get("test_run_id") or "",
                    correlation_id=parent.get("correlation_id") or "")
                scope.data_scope = pctx.data_scope
                scope.test_run_id = pctx.test_run_id
                scope.customer_id = (customer_id or pctx.customer_id)
                scope.project_id = (project_id or pctx.project_id)
                if not scope.correlation_id:
                    scope.correlation_id = pctx.correlation_id
                # SI3：显式入参不得与父链冲突（六维）。
                self.policy.check_child(pctx, scope)
                return scope
        if customer_id:
            row = self.store._conn.execute(
                "SELECT COALESCE(data_scope,'operational') ds,"
                " COALESCE(test_run_id,'') trid, is_test_fixture FROM"
                " md_customer_v1 WHERE customer_id=?",
                (customer_id,)).fetchone()
            if row is not None and (row["ds"] in FIXTURE_SCOPES
                                    or row["is_test_fixture"]):
                trid = row["trid"]
                if not trid:
                    # 兜底：该客户登记的 current 上下文
                    trid = self._current_test_run_of_customer(
                        customer_id)
                if not trid:
                    raise ScopeViolation(
                        "SCOPE_MISSING_TEST_RUN_ID",
                        f"customer {customer_id} 为 fixture，创建对象"
                        " 必须可解析 test_run_id")
                scope.data_scope = "uat_fixture"
                scope.test_run_id = trid
                self.policy.validate(scope)
        return scope

    def _current_test_run_of_customer(self, customer_id: str) -> str:
        rows = self.store._conn.execute(
            "SELECT test_run_id, customer_ids_json FROM uat_test_run_v1"
            " WHERE status='current' ORDER BY created_at DESC"
        ).fetchall()
        for r in rows:
            cids = json.loads(r["customer_ids_json"] or "[]")
            if customer_id in cids:
                return r["test_run_id"]
        return ""

    def scope_of_run(self, run_id: str) -> ExecutionContext:
        """从持久化行恢复 scope（timer/retry/restart 恢复路径专用，
        不得从进程内变量猜测）。"""
        run = self.store.get_business_run(run_id)
        if run is None:
            raise ScopeViolation("SCOPE_RUN_NOT_FOUND", run_id)
        return ExecutionContext(
            tenant_id=run.get("tenant_id") or "local",
            customer_id=run.get("customer_id") or "",
            project_id=run.get("project_id") or "",
            data_scope=run.get("data_scope") or "operational",
            test_run_id=run.get("test_run_id") or "",
            correlation_id=run.get("correlation_id") or "",
            parent_run_id=run.get("parent_run_id") or "")

    def scope_of_response(self, response_id: str) -> ExecutionContext:
        """问卷媒体/识别的父链：response → assignment（SI3：媒体必须
        继承 response scope，指令四.12）。"""
        row = self.store._conn.execute(
            "SELECT r.data_scope rds, r.test_run_id rtr,"
            " r.customer_id rc, a.data_scope ads, a.test_run_id atr,"
            " a.customer_id ac FROM survey_response_v1 r LEFT JOIN"
            " survey_assignment_v1 a ON a.assignment_id="
            " r.assignment_id WHERE r.response_id=?",
            (response_id,)).fetchone()
        if row is None:
            raise ScopeViolation("SCOPE_RESPONSE_NOT_FOUND", response_id)
        ds = row["rds"] or row["ads"] or "operational"
        tr = row["rtr"] or row["atr"] or ""
        cust = row["rc"] or row["ac"] or ""
        if ds not in FIXTURE_SCOPES and not tr and cust:
            return self.resolve(customer_id=cust)
        if ds in FIXTURE_SCOPES or tr:
            if not tr:
                raise ScopeViolation("SCOPE_MISSING_TEST_RUN_ID",
                                     f"response {response_id}")
            return ExecutionContext(data_scope="uat_fixture",
                                    test_run_id=tr, customer_id=cust)
        return ExecutionContext(customer_id=cust)


def assert_test_run_for_api(store: Any, test_run_id: str) -> None:
    """SI3：受信创建端点的前置校验（先于对象创建）：test_run 必须
    在 uat_test_run_v1 且 status=current；archived/不存在 → 抛
    ScopeViolation（端点映射 409，fail-closed，指令四.5/6）。"""
    if test_run_id:
        ScopeResolver(store).assert_test_run_current(test_run_id)


# 允许经受信路径（迁移/一次性回填）直接绑定 fixture scope 的白名单；
# 运行时创建必须走“同事务写入”（create_scoped_* / insert 时带列）。
_BINDABLE_TABLES = {
    "md_customer_v1": "customer_id",
    "md_project_v1": "project_id",
    "md_sku_v1": "sku_id",
    "geo_employee_v1": "employee_id",
    "geo_address_v1": "address_id",
    "field_task_v1": "task_id",
    "route_plan_v1": "plan_id",
    "user_calendar_v1": "event_id",
    "survey_definition_v1": "survey_id",
    "survey_assignment_v1": "assignment_id",
    "survey_response_v1": "response_id",
    "survey_media_v1": "media_id",
    "workflow_definition_v1": "definition_id",
    "bi_report_spec_v1": "spec_id",
    "bi_dashboard_v1": "dashboard_id",
    "bi_anomaly_v1": "anomaly_id",
    "recognition_task": "task_id",
}


def bind_fixture_scope(store: Any, table: str, object_id: str,
                       test_run_id: str) -> None:
    """受信绑定（迁移/回填专用）：原子执行——失败即回滚，不得留下
    半提交状态（SI3：禁止先 commit 再校验，指令四.8）。"""
    if table not in _BINDABLE_TABLES:
        raise ScopeViolation("SCOPE_BIND_TABLE_NOT_ALLOWED", table)
    if not test_run_id:
        raise ScopeViolation("SCOPE_MISSING_TEST_RUN_ID", table)
    id_col = _BINDABLE_TABLES[table]
    conn = store._conn
    n = conn.execute(
        f"UPDATE {table} SET data_scope='uat_fixture', test_run_id=?"
        f" WHERE {id_col}=?", (test_run_id, object_id))
    if n.rowcount != 1:
        conn.rollback()
        raise ScopeViolation("SCOPE_BIND_OBJECT_NOT_FOUND",
                             f"{table}:{object_id}")
    conn.commit()


def create_scoped_customer(store: Any, *, customer_id: str, name: str,
                           test_run_id: str = "",
                           is_test_fixture: bool = False,
                           actor: str = "system",
                           retention_policy: str = "") -> dict:
    """SI3 原子创建：对象与 scope 同一事务（指令四.8）。

    - test_run_id 非空 → registry fail-closed（存在且 current）；
    - is_test_fixture 而无 test_run → 拒绝（禁止静默 operational
      测试客户，指令三.7）；
    - 任一校验失败 → 整笔回滚，对象根本不得落库。
    """
    conn = store._conn
    if is_test_fixture and not test_run_id:
        raise ScopeViolation("SCOPE_MISSING_TEST_RUN_ID",
                             "is_test_fixture 客户必须绑定 test_run")
    if test_run_id:
        ScopeResolver(store).assert_test_run_current(test_run_id,
                                                     customer_id="")
        ds, tr = "uat_fixture", test_run_id
    else:
        ds, tr = "operational", ""
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO md_customer_v1 (customer_id, name,"
            " is_test_fixture, retention_policy, created_by,"
            " created_at, updated_at, data_scope, test_run_id)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (customer_id, name, 1 if is_test_fixture or tr else 0,
             retention_policy, actor, _now(), _now(), ds, tr))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return dict(conn.execute(
        "SELECT * FROM md_customer_v1 WHERE customer_id=?",
        (customer_id,)).fetchone())


class ScopedQuery:
    """effective scope 查询口径与一致性扫描（SI3：父链推导 +
    fail-fast；任何 SQL 异常上抛，Gate 侧记为 BLOCKED，禁止吞）。"""

    # 父链边：子表 → (子 FK 列, 父表, 父 PK 列)
    _PARENT_EDGES: dict[str, tuple[str, str, str]] = {
        "work_item_v2": ("run_id", "business_run_v1", "run_id"),
        "usage_event_v2": ("run_id", "business_run_v1", "run_id"),
        "evidence_bundle_v1": ("run_id", "business_run_v1", "run_id"),
        "recognition_task": ("run_id", "business_run_v1", "run_id"),
        "workflow_node_execution_v1": ("run_id", "business_run_v1",
                                       "run_id"),
        "workflow_timer_v1": ("run_id", "business_run_v1", "run_id"),
        "workflow_branch_v1": ("run_id", "business_run_v1", "run_id"),
        "agent_run_v1": ("business_run_id", "business_run_v1",
                         "run_id"),
        "survey_media_v1": ("response_id", "survey_response_v1",
                            "response_id"),
        "survey_response_v1": ("assignment_id", "survey_assignment_v1",
                               "assignment_id"),
    }
    # 不可变账本：纠偏走 attribution ledger，不改原行（DEC-SI3-003）。
    _IMMUTABLE_TABLES = ("usage_event_v2", "evidence_bundle_v1")

    def __init__(self, store: Any) -> None:
        self.store = store

    # ---------- 基础扫描（fail-fast） ----------

    def recovery_residue(self) -> int:
        """recovery 相关行（node/timer/branch）与父 run scope 不一致
        或 fixture 缺 test_run_id 的数量（应为 0）。"""
        conn = self.store._conn
        n = 0
        for table in ("workflow_node_execution_v1", "workflow_timer_v1",
                      "workflow_branch_v1"):
            n += conn.execute(
                f"SELECT count(*) c FROM {table} t JOIN"
                " business_run_v1 r ON r.run_id=t.run_id WHERE"
                " COALESCE(t.data_scope,'operational') !="
                " COALESCE(r.data_scope,'operational') OR"
                " (COALESCE(t.data_scope,'operational') IN"
                " ('uat_fixture','demo_fixture') AND"
                " COALESCE(t.test_run_id,'')='')").fetchone()["c"]
        return n

    def fixture_missing_test_run(self) -> int:
        """全部 fixture 行缺 test_run_id 的数量（Gate lineage 依据；
        SI3：fail-fast，异常上抛）。"""
        conn = self.store._conn
        n = 0
        for t in _SCOPED_TABLES:
            n += conn.execute(
                f"SELECT count(*) c FROM {t} WHERE data_scope IN"
                " ('uat_fixture','demo_fixture') AND"
                " COALESCE(test_run_id,'')=''").fetchone()["c"]
        return n

    def parent_child_mismatch(self) -> int:
        """父子 run scope/customer/project 不一致数量（应为 0；
        SI3：六维中的结构可比维度）。"""
        conn = self.store._conn
        n = conn.execute(
            "SELECT count(*) c FROM business_run_v1 c JOIN"
            " business_run_v1 p ON p.run_id=c.parent_run_id WHERE"
            " COALESCE(c.data_scope,'operational') !="
            " COALESCE(p.data_scope,'operational')").fetchone()["c"]
        n += conn.execute(
            "SELECT count(*) c FROM business_run_v1 c JOIN"
            " business_run_v1 p ON p.run_id=c.parent_run_id WHERE"
            " COALESCE(c.test_run_id,'')!='' AND"
            " COALESCE(p.test_run_id,'')!='' AND"
            " c.test_run_id != p.test_run_id").fetchone()["c"]
        n += conn.execute(
            "SELECT count(*) c FROM business_run_v1 c JOIN"
            " business_run_v1 p ON p.run_id=c.parent_run_id WHERE"
            " COALESCE(c.customer_id,'')!='' AND"
            " COALESCE(p.customer_id,'')!='' AND"
            " c.customer_id != p.customer_id").fetchone()["c"]
        return n

    # ---------- effective scope 泄漏（SI3 核心） ----------

    def operational_leakage(self) -> dict[str, int]:
        """全 Domain effective fixture 泄漏（归档/纠偏后应为空）。

        口径（结构化，不依赖名称）：
        1) 自身列：operational 但带 test_run_id；
        2) 自身列：fixture 且 visibility='current'；
        3) 父链：自身 operational 但父对象（run/response/
           assignment）effective fixture —— SI2 假阳性漏掉的形态；
        4) 不可变账本（usage/evidence）若已有 attribution 绑定为
           fixture，则视为已纠偏，不计泄漏。
        """
        conn = self.store._conn
        out: dict[str, int] = {}
        for t in _SCOPED_TABLES:
            cols = {r[1] for r in conn.execute(
                f"PRAGMA table_info({t})")}
            conds: list[str] = []
            if "test_run_id" in cols:
                conds.append(
                    "(COALESCE(data_scope,'operational')='operational'"
                    " AND COALESCE(test_run_id,'')!='')")
            if "visibility" in cols:
                conds.append(
                    "(data_scope IN ('uat_fixture','demo_fixture')"
                    " AND visibility='current')")
            edge = self._PARENT_EDGES.get(t)
            if edge and "data_scope" in cols:
                fk, pt, pk = edge
                if fk in cols:
                    conds.append(
                        f"(COALESCE({t}.data_scope,'operational')"
                        f"='operational' AND {t}.{fk}!='' AND EXISTS"
                        f" (SELECT 1 FROM {pt} p WHERE p.{pk}="
                        f"{t}.{fk} AND (COALESCE(p.data_scope,"
                        f"'operational') IN ('uat_fixture',"
                        f"'demo_fixture') OR COALESCE(p.test_run_id,"
                        f"'')!='')))")
            if not conds:
                continue
            sql = (f"SELECT count(*) c FROM {t} WHERE "
                   + " OR ".join(conds))
            # 不可变账本：已 attribution 绑定 fixture 的行不算泄漏
            if t in self._IMMUTABLE_TABLES:
                id_col = "usage_id" if t == "usage_event_v2" \
                    else "evidence_id"
                sql = (f"SELECT count(*) c FROM {t} WHERE ("
                       + " OR ".join(conds) + ") AND NOT EXISTS"
                       " (SELECT 1 FROM scope_attribution_ledger_v1 a"
                       f" WHERE a.subject_table='{t}' AND"
                       f" a.subject_id={t}.{id_col} AND"
                       " a.effective_scope IN ('uat_fixture',"
                       "'demo_fixture'))")
            n = conn.execute(sql).fetchone()["c"]
            if n:
                out[t] = n
        return out

    def attribution_pending(self) -> int:
        """不可变账本中 effective fixture 但尚未 attribution 的行数
        （回填进度指标；完成后应为 0）。"""
        conn = self.store._conn
        leak = self.operational_leakage()
        return sum(v for k, v in leak.items()
                   if k in self._IMMUTABLE_TABLES)


# 需要结构化 scope 的业务表（迁移 051 覆盖；与 02-DOMAIN-SCOPE-MATRIX
# 同源）。已有列的表同样列出，供一致性扫描统一消费。SI3 T3 将由
# scope_registry.py 的全表登记接管覆盖率检查。
_SCOPED_TABLES = (
    "md_customer_v1", "md_project_v1", "md_sku_v1",
    "business_run_v1", "work_item_v2",
    "field_task_v1", "route_plan_v1", "geofence_event_v1",
    "user_calendar_v1",
    "survey_definition_v1", "survey_assignment_v1", "survey_response_v1",
    "survey_media_v1",
    "workflow_definition_v1", "workflow_node_execution_v1",
    "workflow_timer_v1", "workflow_branch_v1",
    "agent_run_v1", "recognition_task",
    "usage_event_v2", "evidence_bundle_v1",
    "bi_report_spec_v1", "bi_anomaly_v1",
)
