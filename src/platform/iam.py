"""ABOSV2 Phase D：IAM 与主数据服务层（03-DOMAIN-PACKS-SPEC §1/§2）。

- 账号开设：user / service_account / agent 三类独立身份（Agent 不借用
  管理员账号）；
- 内置角色仅作模板，自定义角色只能组合版本化 permission bundle；
- 成员关系带 tenant/customer/project scope；授权 fail-closed；
- 批准矩阵：高风险动作只能由矩阵指定角色批准；
- 审计 append-only；
- 主数据：客户库（test fixture 显式标记）/项目库/SKU 库（别名、
  客户显示名、有效期、新旧包装 supersede 链）。
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from .auth import hash_password, verify_password

# ---------- 兼容旧最小 IAM（W6/M2，training_gov 消费） ----------
# 红线：训练审批与模型发布审批是两个独立动作，不得合并。

ROLES = ("viewer", "operator", "admin")
_ROLE_RANK = {"viewer": 1, "operator": 2, "admin": 3}

ACTION_MIN_ROLE: dict[str, str] = {
    "view": "viewer",
    "run.execute": "operator",
    "gate.approve": "operator",
    "training.request": "operator",
    "training.approve": "admin",        # 独立审批动作 1
    "model.publish.approve": "admin",   # 独立审批动作 2（不得与上者合并）
    "system.admin": "admin",
}


def can(role: str, action: str) -> bool:
    """fail-closed：未知角色或未知动作一律拒绝。"""
    if role not in _ROLE_RANK or action not in ACTION_MIN_ROLE:
        return False
    return _ROLE_RANK[role] >= _ROLE_RANK[ACTION_MIN_ROLE[action]]


# ---------- ABOSV2 Phase D：统一 IAM + 主数据 ----------

# permission bundle（版本化 scope）
SCOPES = (
    "vision.read", "vision.manage",
    "workflow.read", "workflow.publish",
    "master.read", "master.manage",
    "iam.read", "iam.manage",
    "analytics.read", "survey.read", "geo.read", "finance.read",
    "agent.query",
)

# 内置角色模板（03 §1.2）
BUILTIN_ROLES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("owner", "租户所有者", ("iam.manage", "master.manage",
                             "vision.manage", "workflow.publish",
                             "finance.read", "analytics.read",
                             "master.read", "iam.read", "workflow.read",
                             "vision.read", "agent.query", "survey.read",
                             "geo.read")),
    ("platform_admin", "平台管理员", ("iam.manage", "master.manage",
                                      "master.read", "iam.read",
                                      "workflow.read", "workflow.publish",
                                      "vision.read", "vision.manage",
                                      "analytics.read", "agent.query",
                                      "survey.read", "geo.read",
                                      "finance.read")),
    ("customer_admin", "客户管理员", ("master.read", "master.manage",
                                      "vision.read", "workflow.read",
                                      "analytics.read", "agent.query")),
    ("project_manager", "项目经理", ("master.read", "vision.read",
                                     "workflow.read", "agent.query")),
    ("survey_designer", "问卷设计者", ("survey.read", "master.read")),
    ("field_manager", "外勤主管", ("geo.read", "master.read")),
    ("reviewer", "审核员", ("vision.read",)),
    ("analyst", "分析师", ("analytics.read", "master.read", "agent.query")),
    ("finance_operator", "财务操作员", ("finance.read", "master.read")),
    ("read_only", "只读", ("vision.read", "master.read", "workflow.read")),
    ("agent_service", "Agent 服务身份", ("agent.query", "master.read")),
)

# 批准矩阵（03 §1.2 / 01 §7：高风险动作的角色门）
APPROVAL_MATRIX: tuple[tuple[str, str, int], ...] = (
    ("production.switch", "platform_admin", 1),
    ("data.delete", "platform_admin", 1),
    ("publish.auto", "platform_admin", 1),
    ("finance.finalize", "finance_operator", 1),
    ("workflow.publish", "platform_admin", 1),
)


class IAMError(Exception):
    """IAM 错误（fail-closed）。"""


def _new_id(prefix: str) -> str:
    return f"{prefix}-" + uuid.uuid4().hex[:12]


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class IAMService:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.seed_builtins()

    # ---------- seed ----------

    def seed_builtins(self) -> None:
        conn = self.store._conn
        for name, desc, scopes in BUILTIN_ROLES:
            conn.execute(
                "INSERT OR IGNORE INTO iam_role_v1 (role_id, name, builtin,"
                " description, created_at) VALUES (?,?,1,?,?)",
                (f"role-{name}", name, desc, _now()))
        for scope in SCOPES:
            conn.execute(
                "INSERT OR IGNORE INTO iam_permission_bundle_v1"
                " (bundle_id, scope, version) VALUES (?,?, 'v1')",
                (f"pb-{scope}", scope))
        for name, _desc, scopes in BUILTIN_ROLES:
            for scope in scopes:
                conn.execute(
                    "INSERT OR IGNORE INTO iam_role_permission_v1"
                    " (role_id, bundle_id) VALUES (?,?)",
                    (f"role-{name}", f"pb-{scope}"))
        for action, role, n in APPROVAL_MATRIX:
            conn.execute(
                "INSERT OR IGNORE INTO iam_approval_matrix_v1"
                " (action, approver_role, min_approvers) VALUES (?,?,?)",
                (action, role, n))
        conn.commit()

    # ---------- 身份 ----------

    def create_principal(self, *, kind: str, username: str,
                         display_name: str = "", password: str = "",
                         created_by: str) -> dict:
        if kind not in ("user", "service_account", "agent"):
            raise IAMError(f"身份类型非法: {kind}")
        if not username:
            raise IAMError("username 必填")
        if kind == "user" and not password:
            raise IAMError("user 身份必须设置口令")
        pw_hash = hash_password(password) if password else ""
        pid = _new_id("pr")
        try:
            self.store._conn.execute(
                "INSERT INTO iam_principal_v1 (principal_id, kind, username,"
                " display_name, password_hash, created_by, created_at,"
                " updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (pid, kind, username, display_name or username, pw_hash,
                 created_by, _now(), _now()))
            self.store._conn.commit()
        except Exception:
            raise IAMError(f"username 已存在: {username}")
        self.audit(created_by, "iam.principal.created",
                   f"principal:{username}", {"kind": kind})
        return self.get_principal_by_username(username)

    def get_principal_by_username(self, username: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM iam_principal_v1 WHERE username=?",
            (username,)).fetchone()
        return dict(row) if row else None

    def list_principals(self) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT principal_id, kind, username, display_name, status,"
            " created_at FROM iam_principal_v1"
            " ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    def verify_login(self, username: str, password: str) -> dict | None:
        p = self.get_principal_by_username(username)
        if p is None or p["status"] != "active":
            return None
        if p["kind"] not in ("user", "service_account"):
            return None  # agent 身份不得走口令登录
        if not p["password_hash"]:
            return None
        if not verify_password(password, p["password_hash"]):
            return None
        return p

    # ---------- 授权 ----------

    def grant(self, *, username: str, role: str, customer_id: str = "",
              project_id: str = "", granted_by: str) -> dict:
        p = self.get_principal_by_username(username)
        if p is None:
            raise IAMError(f"身份不存在: {username}")
        role_row = self.store._conn.execute(
            "SELECT role_id FROM iam_role_v1 WHERE name=?",
            (role,)).fetchone()
        if role_row is None:
            raise IAMError(f"角色不存在: {role}")
        self.store._conn.execute(
            "INSERT OR IGNORE INTO iam_membership_v1 (principal_id,"
            " role_id, customer_id, project_id, granted_by, granted_at)"
            " VALUES (?,?,?,?,?,?)",
            (p["principal_id"], role_row["role_id"], customer_id,
             project_id, granted_by, _now()))
        self.store._conn.commit()
        self.audit(granted_by, "iam.membership.granted",
                   f"principal:{username}",
                   {"role": role, "customer_id": customer_id,
                    "project_id": project_id})
        return {"username": username, "role": role,
                "customer_id": customer_id, "project_id": project_id}

    def roles_of(self, username: str) -> list[str]:
        rows = self.store._conn.execute(
            "SELECT r.name FROM iam_membership_v1 m"
            " JOIN iam_principal_v1 p ON p.principal_id=m.principal_id"
            " JOIN iam_role_v1 r ON r.role_id=m.role_id"
            " WHERE p.username=?", (username,)).fetchall()
        return sorted({r["name"] for r in rows})

    def memberships_of(self, username: str) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT r.name AS role, m.customer_id, m.project_id,"
            " m.granted_by, m.granted_at FROM iam_membership_v1 m"
            " JOIN iam_principal_v1 p ON p.principal_id=m.principal_id"
            " JOIN iam_role_v1 r ON r.role_id=m.role_id"
            " WHERE p.username=?", (username,)).fetchall()
        return [dict(r) for r in rows]

    def scopes_of(self, username: str) -> list[str]:
        rows = self.store._conn.execute(
            "SELECT b.scope FROM iam_membership_v1 m"
            " JOIN iam_principal_v1 p ON p.principal_id=m.principal_id"
            " JOIN iam_role_permission_v1 rp ON rp.role_id=m.role_id"
            " JOIN iam_permission_bundle_v1 b ON b.bundle_id=rp.bundle_id"
            " WHERE p.username=?", (username,)).fetchall()
        return sorted({r["scope"] for r in rows})

    def authorize(self, username: str, scope: str, *,
                  customer_id: str = "", project_id: str = "") -> bool:
        """fail-closed：scope + customer/project 作用域必须同时满足。"""
        if scope not in SCOPES:
            return False
        roles = self.roles_of(username)
        if "owner" in roles or "platform_admin" in roles:
            return True
        rows = self.store._conn.execute(
            "SELECT m.customer_id, m.project_id FROM iam_membership_v1 m"
            " JOIN iam_principal_v1 p ON p.principal_id=m.principal_id"
            " JOIN iam_role_permission_v1 rp ON rp.role_id=m.role_id"
            " JOIN iam_permission_bundle_v1 b ON b.bundle_id=rp.bundle_id"
            " WHERE p.username=? AND b.scope=?", (username, scope)).fetchall()
        for r in rows:
            # customer_id 缺省 = 作用域级检查（列表类接口由调用方
            # 按自身作用域过滤）；指定时要求成员作用域匹配。
            cust_ok = (not customer_id) or (not r["customer_id"]) or (
                r["customer_id"] == customer_id)
            proj_ok = (not project_id) or (not r["project_id"]) or (
                r["project_id"] == project_id)
            if cust_ok and proj_ok:
                return True
        return False

    def visible_customers(self, username: str) -> str | None:
        """返回 None=全部可见（平台角色）；否则返回受限 customer_id
        （多客户受限取第一个，MVP 单客户作用域）。"""
        roles = self.roles_of(username)
        if "owner" in roles or "platform_admin" in roles:
            return None
        rows = self.store._conn.execute(
            "SELECT DISTINCT m.customer_id FROM iam_membership_v1 m"
            " JOIN iam_principal_v1 p ON p.principal_id=m.principal_id"
            " WHERE p.username=? AND m.customer_id != ''",
            (username,)).fetchall()
        if not rows:
            return "__none__"  # 无任何客户作用域 → 不可见任何客户数据
        return rows[0]["customer_id"]

    def check_approval(self, username: str, action: str) -> bool:
        """批准矩阵：矩阵未收录的动作 fail-closed 仅平台管理员。"""
        rows = self.store._conn.execute(
            "SELECT approver_role FROM iam_approval_matrix_v1"
            " WHERE action=?", (action,)).fetchall()
        roles = set(self.roles_of(username))
        if "platform_admin" in roles or "owner" in roles:
            return True
        if not rows:
            return False
        return any(r["approver_role"] in roles for r in rows)

    # ---------- 审计 ----------

    def audit(self, actor: str, action: str, resource: str = "",
              detail: dict | None = None, customer_id: str = "") -> None:
        self.store._conn.execute(
            "INSERT INTO iam_audit_event_v1 (occurred_at, actor_id, action,"
            " resource, detail_json, customer_id)"
            " VALUES (?,?,?,?,?,?)",
            (_now(), actor, action, resource,
             json.dumps(detail or {}, ensure_ascii=False), customer_id))
        self.store._conn.commit()

    def list_audit(self, *, limit: int = 200) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM iam_audit_event_v1 ORDER BY audit_id DESC"
            " LIMIT ?", (min(limit, 500),)).fetchall()
        return [dict(r) for r in rows]


class MasterDataError(Exception):
    pass


class MasterDataService:
    """客户库 / 项目库 / SKU 库（共享主数据，不从属于问卷）。"""

    def __init__(self, store: Any, iam: IAMService) -> None:
        self.store = store
        self.iam = iam

    # ---- 客户 ----

    def create_customer(self, *, customer_id: str, name: str,
                        is_test_fixture: bool = False,
                        retention_policy: str = "",
                        created_by: str) -> dict:
        try:
            self.store._conn.execute(
                "INSERT INTO md_customer_v1 (customer_id, name,"
                " is_test_fixture, retention_policy, created_by,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (customer_id, name, 1 if is_test_fixture else 0,
                 retention_policy, created_by, _now(), _now()))
            self.store._conn.commit()
        except Exception:
            raise MasterDataError(f"customer 已存在: {customer_id}")
        self.iam.audit(created_by, "master.customer.created",
                       f"customer:{customer_id}",
                       {"is_test_fixture": is_test_fixture},
                       customer_id=customer_id)
        return self.get_customer(customer_id)

    def get_customer(self, customer_id: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM md_customer_v1 WHERE customer_id=?",
            (customer_id,)).fetchone()
        d = dict(row) if row else None
        if d is not None:
            d["is_test_fixture"] = bool(d["is_test_fixture"])
        return d

    def list_customers(self, *, viewer: str | None = None) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM md_customer_v1 ORDER BY created_at").fetchall()
        out = []
        limit_to = self.iam.visible_customers(viewer) if viewer else None
        for r in rows:
            d = dict(r)
            d["is_test_fixture"] = bool(d["is_test_fixture"])
            if limit_to is not None and d["customer_id"] != limit_to:
                continue
            out.append(d)
        return out

    # ---- 项目 ----

    def create_project(self, *, project_id: str, customer_id: str,
                       name: str, sku_scope: list | None = None,
                       budget: dict | None = None,
                       created_by: str) -> dict:
        if self.get_customer(customer_id) is None:
            raise MasterDataError(f"customer 不存在: {customer_id}")
        try:
            self.store._conn.execute(
                "INSERT INTO md_project_v1 (project_id, customer_id, name,"
                " sku_scope_json, budget_json, created_by, created_at,"
                " updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (project_id, customer_id, name,
                 json.dumps(sku_scope or [], ensure_ascii=False),
                 json.dumps(budget or {}, ensure_ascii=False),
                 created_by, _now(), _now()))
            self.store._conn.commit()
        except Exception:
            raise MasterDataError(f"project 已存在: {project_id}")
        self.iam.audit(created_by, "master.project.created",
                       f"project:{project_id}", {},
                       customer_id=customer_id)
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM md_project_v1 WHERE project_id=?",
            (project_id,)).fetchone()
        return dict(row) if row else None

    def list_projects(self, *, customer_id: str) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM md_project_v1 WHERE customer_id=?"
            " ORDER BY created_at", (customer_id,)).fetchall()
        return [dict(r) for r in rows]

    # ---- SKU ----

    def create_sku(self, *, sku_id: str, canonical_name: str,
                   brand: str = "", category: str = "", volume: str = "",
                   barcode: str = "", package_version: str = "v1",
                   valid_from: str | None = None,
                   valid_to: str | None = None,
                   created_by: str) -> dict:
        try:
            self.store._conn.execute(
                "INSERT INTO md_sku_v1 (sku_id, canonical_name, brand,"
                " category, volume, barcode, package_version, valid_from,"
                " valid_to, created_by, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (sku_id, canonical_name, brand, category, volume, barcode,
                 package_version, valid_from, valid_to, created_by,
                 _now(), _now()))
            self.store._conn.commit()
        except Exception:
            raise MasterDataError(f"sku 已存在: {sku_id}")
        self.iam.audit(created_by, "master.sku.created", f"sku:{sku_id}",
                       {"package_version": package_version})
        return self.get_sku(sku_id)

    def get_sku(self, sku_id: str) -> dict | None:
        row = self.store._conn.execute(
            "SELECT * FROM md_sku_v1 WHERE sku_id=?",
            (sku_id,)).fetchone()
        return dict(row) if row else None

    def list_skus(self, *, include_superseded: bool = False) -> list[dict]:
        where = "" if include_superseded else "WHERE status != 'superseded'"
        rows = self.store._conn.execute(
            f"SELECT * FROM md_sku_v1 {where}"
            " ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    def supersede_sku(self, *, old_sku_id: str, new_sku_id: str,
                      actor: str) -> dict:
        """新旧包装：旧 SKU 追加式标记 superseded_by，不删除历史。"""
        old, new = self.get_sku(old_sku_id), self.get_sku(new_sku_id)
        if old is None or new is None:
            raise MasterDataError("新旧 SKU 必须均存在")
        if old["canonical_name"] != new["canonical_name"]:
            raise MasterDataError(
                "新旧包装必须同一 canonical_name（不得改变商品身份）")
        self.store._conn.execute(
            "UPDATE md_sku_v1 SET status='superseded', superseded_by=?,"
            " updated_at=? WHERE sku_id=?",
            (new_sku_id, _now(), old_sku_id))
        self.store._conn.commit()
        self.iam.audit(actor, "master.sku.superseded", f"sku:{old_sku_id}",
                       {"superseded_by": new_sku_id})
        return self.get_sku(old_sku_id)

    def add_alias(self, *, sku_id: str, alias: str,
                  kind: str = "alias", customer_id: str = "",
                  actor: str) -> dict:
        if kind not in ("alias", "customer_display_name"):
            raise MasterDataError("kind 只支持 alias/customer_display_name")
        if kind == "customer_display_name" and not customer_id:
            raise MasterDataError("客户显示名必须绑定 customer_id")
        if self.get_sku(sku_id) is None:
            raise MasterDataError(f"sku 不存在: {sku_id}")
        try:
            self.store._conn.execute(
                "INSERT INTO md_sku_alias_v1 (sku_id, alias, kind,"
                " customer_id, created_at) VALUES (?,?,?,?,?)",
                (sku_id, alias, kind, customer_id, _now()))
            self.store._conn.commit()
        except Exception:
            raise MasterDataError(f"别名已存在: {alias}")
        self.iam.audit(actor, "master.sku.alias_added", f"sku:{sku_id}",
                       {"alias": alias, "kind": kind},
                       customer_id=customer_id)
        return {"sku_id": sku_id, "alias": alias, "kind": kind,
                "customer_id": customer_id}

    def display_name_for(self, sku_id: str, customer_id: str = "") -> str:
        """客户显示名优先，其次别名，最后 canonical（不覆盖历史答案）。"""
        if customer_id:
            row = self.store._conn.execute(
                "SELECT alias FROM md_sku_alias_v1 WHERE sku_id=? AND"
                " customer_id=? AND kind='customer_display_name'",
                (sku_id, customer_id)).fetchone()
            if row:
                return row["alias"]
        sku = self.get_sku(sku_id)
        return sku["canonical_name"] if sku else sku_id

    def aliases_of(self, sku_id: str) -> list[dict]:
        rows = self.store._conn.execute(
            "SELECT * FROM md_sku_alias_v1 WHERE sku_id=?"
            " ORDER BY alias_id", (sku_id,)).fetchall()
        return [dict(r) for r in rows]

    # ---- 客户隔离概览（G4 证明端点） ----

    def customer_overview(self, customer_id: str) -> dict:
        conn = self.store._conn
        runs = conn.execute(
            "SELECT count(*) c FROM business_run_v1 WHERE customer_id=?",
            (customer_id,)).fetchone()["c"]
        tasks = conn.execute(
            "SELECT count(*) c FROM recognition_task t"
            " JOIN business_run_v1 r ON r.run_id=t.run_id"
            " WHERE r.customer_id=?", (customer_id,)).fetchone()["c"]
        usage_rows = conn.execute(
            "SELECT unit, sum(quantity) q, count(*) n FROM usage_event_v2"
            " WHERE customer_id=? GROUP BY unit",
            (customer_id,)).fetchall()
        events = conn.execute(
            "SELECT count(*) c FROM event_envelope_v1 WHERE customer_id=?",
            (customer_id,)).fetchone()["c"]
        works = conn.execute(
            "SELECT count(*) c FROM work_item_v2 w"
            " JOIN business_run_v1 r ON r.run_id=w.run_id"
            " WHERE r.customer_id=?", (customer_id,)).fetchone()["c"]
        return {"customer_id": customer_id, "runs": runs, "tasks": tasks,
                "work_items": works, "events": events,
                "usage": [{"unit": r["unit"], "quantity": r["q"],
                           "lines": r["n"]} for r in usage_rows]}
