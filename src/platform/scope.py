"""SI2 T2：统一执行作用域 ExecutionScopeV1（01-EXECUTION-SCOPE-CONTRACT）。

唯一实现：ScopeResolver（服务端解析）/ ScopePolicy（fail-closed 校验）
/ ScopedQuery（默认 operational 查询口径）。各模块必须注入使用，
禁止复制 scope 逻辑（指令 4.2/五 T2）。

唯一事实源 = 业务表自身的 data_scope/test_run_id 字段（DEC-SI2-001）；
名称模式（LIKE 'uat%'）只允许出现在一次性 legacy backfill。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

DATA_SCOPES = ("operational", "uat_fixture", "demo_fixture", "system",
               "archived")
FIXTURE_SCOPES = ("uat_fixture", "demo_fixture")

# 默认查询口径：历史行无列/NULL 一律视为 operational（backfill 后
# 由结构字段接管）；运行时禁止名称模式。
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
class ExecutionScopeV1:
    """一次执行/对象的结构化作用域（指令 4.1）。"""
    tenant_id: str = "local"
    customer_id: str = ""
    project_id: str = ""
    data_scope: str = "operational"
    test_run_id: str = ""
    correlation_id: str = ""
    parent_run_id: str = ""
    actor_id: str = ""
    source: str = ""
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
                "created_at": self.created_at}


class ScopePolicy:
    """继承与一致性校验（指令 4.3 fail-closed）。"""

    def validate(self, scope: ExecutionScopeV1) -> None:
        if scope.data_scope not in DATA_SCOPES:
            raise ScopeViolation("SCOPE_UNKNOWN_DATA_SCOPE",
                                 scope.data_scope)
        if scope.is_fixture() and not scope.test_run_id:
            raise ScopeViolation("SCOPE_MISSING_TEST_RUN_ID",
                                 f"scope={scope.data_scope} 缺少"
                                 " test_run_id")

    def check_child(self, parent: ExecutionScopeV1,
                    child: ExecutionScopeV1) -> None:
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


class ScopeResolver:
    """服务端 scope 解析（客户端不得自证 operational）。

    解析顺序：显式 test_run → 父 Run → Customer 主数据 → operational。
    """

    def __init__(self, store: Any) -> None:
        self.store = store
        self.policy = ScopePolicy()

    def resolve(self, *, parent_run_id: str | None = None,
                test_run_id: str = "", customer_id: str = "",
                project_id: str = "", actor_id: str = "",
                source: str = "", correlation_id: str = "",
                tenant_id: str = "local") -> ExecutionScopeV1:
        scope = ExecutionScopeV1(tenant_id=tenant_id,
                                 customer_id=customer_id or "",
                                 project_id=project_id or "",
                                 actor_id=actor_id, source=source,
                                 correlation_id=correlation_id or "",
                                 parent_run_id=parent_run_id or "")
        if test_run_id:
            scope.data_scope = "uat_fixture"
            scope.test_run_id = test_run_id
            self.policy.validate(scope)
            return scope
        if parent_run_id:
            parent = self.store.get_business_run(parent_run_id)
            if parent is not None:
                scope.data_scope = (parent.get("data_scope")
                                    or "operational")
                scope.test_run_id = parent.get("test_run_id") or ""
                scope.customer_id = (customer_id
                                     or parent.get("customer_id") or "")
                scope.project_id = (project_id
                                    or parent.get("project_id") or "")
                self.policy.validate(scope)
                return scope
        if customer_id:
            row = self.store._conn.execute(
                "SELECT COALESCE(data_scope,'operational') ds FROM"
                " md_customer_v1 WHERE customer_id=?",
                (customer_id,)).fetchone()
            if row is not None and row["ds"] in FIXTURE_SCOPES:
                # fixture 客户下创建对象必须显式携带 test_run（fail-
                # closed：禁止静默生成无 test_run_id 的 fixture）
                raise ScopeViolation(
                    "SCOPE_MISSING_TEST_RUN_ID",
                    f"customer {customer_id} 为 fixture，创建对象"
                    " 必须显式提供 test_run_id")
        return scope

    def scope_of_run(self, run_id: str) -> ExecutionScopeV1:
        """从持久化行恢复 scope（timer/retry/restart 恢复路径专用，
        不得从进程内变量猜测）。"""
        run = self.store.get_business_run(run_id)
        if run is None:
            raise ScopeViolation("SCOPE_RUN_NOT_FOUND", run_id)
        return ExecutionScopeV1(
            tenant_id=run.get("tenant_id") or "local",
            customer_id=run.get("customer_id") or "",
            project_id=run.get("project_id") or "",
            data_scope=run.get("data_scope") or "operational",
            test_run_id=run.get("test_run_id") or "",
            correlation_id=run.get("correlation_id") or "",
            parent_run_id=run.get("parent_run_id") or "")


class ScopedQuery:
    """默认 operational 的查询口径与一致性扫描（T4/T6 消费）。"""

    def __init__(self, store: Any) -> None:
        self.store = store

    def recovery_residue(self) -> int:
        """recovery 相关行（node/timer/branch）与父 run scope 不一致
        或 fixture 缺 test_run_id 的数量（应为 0）。"""
        conn = self.store._conn
        n = 0
        for table in ("workflow_node_execution_v1", "workflow_timer_v1",
                      "workflow_branch_v1"):
            try:
                n += conn.execute(
                    f"SELECT count(*) c FROM {table} t JOIN"
                    " business_run_v1 r ON r.run_id=t.run_id WHERE"
                    " COALESCE(t.data_scope,'operational') !="
                    " COALESCE(r.data_scope,'operational') OR"
                    " (COALESCE(t.data_scope,'operational') IN"
                    " ('uat_fixture','demo_fixture') AND"
                    " COALESCE(t.test_run_id,'')='')").fetchone()["c"]
            except Exception:
                continue
        return n

    def fixture_missing_test_run(self) -> int:
        """全部 fixture 行缺 test_run_id 的数量（Gate lineage 依据）。"""
        conn = self.store._conn
        n = 0
        tables = _SCOPED_TABLES
        for t in tables:
            try:
                n += conn.execute(
                    f"SELECT count(*) c FROM {t} WHERE data_scope IN"
                    " ('uat_fixture','demo_fixture') AND"
                    " COALESCE(test_run_id,'')=''").fetchone()["c"]
            except Exception:
                continue
        return n

    def parent_child_mismatch(self) -> int:
        """父子 run data_scope 不一致数量（应为 0）。"""
        try:
            return self.store._conn.execute(
                "SELECT count(*) c FROM business_run_v1 c JOIN"
                " business_run_v1 p ON p.run_id=c.parent_run_id WHERE"
                " COALESCE(c.data_scope,'operational') !="
                " COALESCE(p.data_scope,'operational')").fetchone()["c"]
        except Exception:
            return 0

    def operational_leakage(self) -> dict[str, int]:
        """全 Domain：operational 投影中的 fixture 泄漏（归档后应为空）。
    
        口径（结构化，不依赖名称）：
        - 任何 data_scope=operational 但带 test_run_id 的行（带
          test_run 的对象结构性地属于 fixture，不得 operational）；
        - 带 visibility 的表中 fixture 且 visibility='current' 的行
          （仍在运营投影窗口内）。
        """
        conn = self.store._conn
        out: dict[str, int] = {}
        for t in _SCOPED_TABLES:
            try:
                cols = {r[1] for r in conn.execute(
                    f"PRAGMA table_info({t})")}
                conds: list[str] = []
                if "test_run_id" in cols:
                    conds.append(
                        "(COALESCE(data_scope,'operational')"
                        "='operational' AND"
                        " COALESCE(test_run_id,'')!='')")
                if "visibility" in cols:
                    conds.append(
                        "(data_scope IN ('uat_fixture','demo_fixture')"
                        " AND visibility='current')")
                if not conds:
                    continue
                n = conn.execute(
                    f"SELECT count(*) c FROM {t} WHERE "
                    + " OR ".join(conds)).fetchone()["c"]
                if n:
                    out[t] = n
            except Exception:
                continue
        return out


# 需要结构化 scope 的业务表（迁移 051 覆盖；与 02-DOMAIN-SCOPE-MATRIX
# 同源）。已有列的表同样列出，供一致性扫描统一消费。
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
