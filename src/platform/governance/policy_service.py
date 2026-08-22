"""deterministic Policy Decision Point（Task 4 / G2）。

- 输入：CognitiveContext(dict)/action/resource/risk；
- 输出：{decision: allow|deny|human_gate, rule_refs, reason}，确定性；
- 缺上下文/未知动作 fail-closed（deny）；
- 已发布且在生效期内的规则：deny 优先于 allow；high 风险 allow 升级为
  human_gate；draft/superseded/revoked 规则不参与决策；
- 规则发布只能经 governance_approval_v1（maker≠checker）。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from . import GovernanceConflictError, GovernanceError, GovernanceRoleError

# 默认放行的平台级低风险动作（V1 静态清单；后续由规则版本化扩展）。
DEFAULT_ALLOW_ACTIONS = frozenset({
    "cognition.knowledge.search",
    "cognition.memory.search",
    "cognition.skills.search",
    "cognition.research.start",
    "cognition.research.read",
    "cognition.platform.health",
    "workflow.read",
})

# 高风险动作：默认 human_gate（02 §8.4 人工门清单）。
HIGH_RISK_ACTIONS = frozenset({
    "production.switch",
    "training.launch_unbounded",
    "data.delete",
    "finance.finalize",
    "cognition.knowledge.publish",
    "cognition.l3.publish",
    "cognition.skill.publish",
    "governance.rule.publish",
    "research.report.publish_external",
    "pause.resume",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


class PolicyService:
    def __init__(self, store: Any) -> None:
        self.store = store

    # ---------- 规则生命周期 ----------

    def draft_rule(self, *, actor: str, rule_id: str,
                   allow: list[str], deny: list[str],
                   risk_level: str = "medium", summary: str = "",
                   subjects: list[str] | None = None,
                   priority: int = 100,
                   effective_from: str | None = None,
                   effective_to: str | None = None) -> dict[str, Any]:
        if not rule_id or not actor:
            raise GovernanceError("rule_id/actor 必填")
        if risk_level not in ("low", "medium", "high", "critical"):
            raise GovernanceError(f"非法 risk_level: {risk_level}")
        conn = self.store._conn
        row = conn.execute(
            "SELECT max(version) v FROM policy_rule_version"
            " WHERE rule_id=?", (rule_id,)).fetchone()
        version = (row["v"] or 0) + 1
        conn.execute(
            "INSERT INTO policy_rule_version (rule_id, version, status,"
            " summary, subjects_json, allow_json, deny_json, risk_level,"
            " priority, effective_from, effective_to, created_by,"
            " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rule_id, version, "draft", summary,
             json.dumps(subjects or [], ensure_ascii=False),
             json.dumps(allow or [], ensure_ascii=False),
             json.dumps(deny or [], ensure_ascii=False),
             risk_level, int(priority), effective_from, effective_to,
             actor, _now()))
        conn.commit()
        return self.get_rule(rule_id, version)

    def get_rule(self, rule_id: str, version: int) -> dict[str, Any]:
        row = self.store._conn.execute(
            "SELECT * FROM policy_rule_version WHERE rule_id=? AND"
            " version=?", (rule_id, version)).fetchone()
        if row is None:
            raise GovernanceError(f"规则不存在: {rule_id}@v{version}")
        return dict(row)

    def request_publish(self, *, rule_id: str, version: int,
                        requested_by: str, kind: str = "policy.publish"
                        ) -> dict[str, Any]:
        rule = self.get_rule(rule_id, version)
        if rule["status"] != "draft":
            raise GovernanceError(
                f"只有 draft 可申请发布（当前 {rule['status']}）")
        approval_id = "apr-" + uuid.uuid4().hex[:12]
        self.store._conn.execute(
            "INSERT INTO governance_approval_v1 (approval_id, kind,"
            " subject_ref, requested_by, decision, requested_at)"
            " VALUES (?,?,?,?, 'pending', ?)",
            (approval_id, kind, f"{rule_id}@v{version}", requested_by,
             _now()))
        self.store._conn.commit()
        return self.get_approval(approval_id)

    def request_generic_approval(self, *, kind: str, subject_ref: str,
                                 requested_by: str) -> dict[str, Any]:
        """通用人工批准申请（认知层发布/废止复用同一账本，评审 #4/#12）。

        kind 如 cognition.knowledge.publish / cognition.skill.publish /
        cognition.l3.publish；subject_ref 形如 'kb-x@v1'。"""
        approval_id = "apr-" + uuid.uuid4().hex[:12]
        self.store._conn.execute(
            "INSERT INTO governance_approval_v1 (approval_id, kind,"
            " subject_ref, requested_by, decision, requested_at)"
            " VALUES (?,?,?,?, 'pending', ?)",
            (approval_id, kind, subject_ref, requested_by, _now()))
        self.store._conn.commit()
        return self.get_approval(approval_id)

    def verify_approved(self, approval_id: str, *, kind: str,
                        subject_ref: str, approver: str,
                        created_by: str = "") -> dict[str, Any]:
        """发布门校验（评审 #4/#12/#17）：approval 必须真实存在、已批准、
        kind/subject 匹配、批准人==approver；起草人不得自批（maker≠checker）。"""
        if not approval_id:
            raise GovernanceError(
                "发布必须提供 approval_id（人类批准账本）")
        ap = self.get_approval(approval_id)
        if ap["kind"] != kind:
            raise GovernanceError(
                f"approval kind 不匹配: {ap['kind']} != {kind}")
        if ap["subject_ref"] != subject_ref:
            raise GovernanceError(
                f"approval subject 不匹配: {ap['subject_ref']} !="
                f" {subject_ref}")
        if ap["decision"] != "approved":
            raise GovernanceError(
                f"approval 未获批准（decision={ap['decision']}）")
        if ap["decided_by"] != approver:
            raise GovernanceError(
                "approver 必须与批准决策人一致")
        # maker≠checker：批准申请人（maker）不得即批准人（checker）。
        # 单一管理员本机环境下，申请人应记为系统/起草身份，人类做决策，
        # 从而保持 maker≠checker（决策层分离，见 DECISIONS）。
        if ap["requested_by"] == approver:
            raise GovernanceRoleError(
                "maker=checker 禁止：批准申请人不得自批")
        return ap

    def get_approval(self, approval_id: str) -> dict[str, Any]:
        row = self.store._conn.execute(
            "SELECT * FROM governance_approval_v1 WHERE approval_id=?",
            (approval_id,)).fetchone()
        if row is None:
            raise GovernanceError(f"approval 不存在: {approval_id}")
        return dict(row)

    def decide_approval(self, approval_id: str, *, actor: str,
                        decision: str, reason: str = "") -> dict[str, Any]:
        """人类决策入口（maker≠checker；CAS pending→终态）。"""
        ap = self.get_approval(approval_id)
        if decision not in ("approved", "rejected"):
            raise GovernanceError(f"非法 decision: {decision}")
        if actor == ap["requested_by"]:
            raise GovernanceRoleError(
                "maker=checker 禁止：审批人不得与申请人相同")
        rc = self.store._conn.execute(
            "UPDATE governance_approval_v1 SET decision=?, decided_by=?,"
            " decided_at=?, reason=? WHERE approval_id=? AND"
            " decision='pending'",
            (decision, actor, _now(), reason, approval_id)).rowcount
        self.store._conn.commit()
        if rc == 0:
            raise GovernanceConflictError(
                f"approval {approval_id} 已被决策（迟到写拒绝）")
        if decision == "approved" and ap["kind"] == "policy.publish":
            self._publish_rule_ref(ap["subject_ref"], approval_id, actor)
        return self.get_approval(approval_id)

    def _publish_rule_ref(self, subject_ref: str, approval_id: str,
                          actor: str) -> None:
        rule_id, _, vtxt = subject_ref.partition("@v")
        version = int(vtxt)
        conn = self.store._conn
        rc = conn.execute(
            "UPDATE policy_rule_version SET status='published',"
            " approval_id=?, published_at=? WHERE rule_id=? AND"
            " version=? AND status='draft'",
            (approval_id, _now(), rule_id, version)).rowcount
        if rc == 0:
            raise GovernanceConflictError(
                f"规则 {subject_ref} 不是 draft，发布拒绝")
        conn.execute(
            "UPDATE policy_rule_version SET status='superseded'"
            " WHERE rule_id=? AND status='published' AND version!=?",
            (rule_id, version))
        conn.commit()

    # ---------- 决策 ----------

    def evaluate(self, context: Mapping[str, Any] | None, *,
                 action: str, resource: str = "",
                 risk: str = "") -> dict[str, Any]:
        """确定性 PDP。注入文本只作为匹配数据，绝不解释执行。"""
        if not isinstance(context, Mapping):
            return {"decision": "deny", "rule_refs": [],
                    "reason": "COGNITION_CONTEXT_MISSING（fail-closed）"}
        if not context.get("principal_id") or not context.get("tenant_id"):
            return {"decision": "deny", "rule_refs": [],
                    "reason": "context 缺 principal/tenant（fail-closed）"}
        if not action:
            return {"decision": "deny", "rule_refs": [],
                    "reason": "action 必填（fail-closed）"}
        as_of = _parse_ts(context.get("as_of")) or datetime.now(
            timezone.utc)
        deny_refs: list[str] = []
        allow_refs: list[str] = []
        gate_refs: list[str] = []
        for row in self.store._conn.execute(
                "SELECT * FROM policy_rule_version WHERE"
                " status='published' ORDER BY priority ASC, version DESC"):
            frm, to = _parse_ts(row["effective_from"]), _parse_ts(
                row["effective_to"])
            if frm is not None and as_of < frm:
                continue
            if to is not None and as_of >= to:
                continue
            deny = json.loads(row["deny_json"] or "[]")
            allow = json.loads(row["allow_json"] or "[]")
            if action in deny:
                deny_refs.append(row["rule_id"])
            elif action in allow:
                allow_refs.append(row["rule_id"])
                if row["risk_level"] in ("high", "critical"):
                    gate_refs.append(row["rule_id"])
        if deny_refs:
            return {"decision": "deny", "rule_refs": deny_refs,
                    "reason": "published deny rule"}
        if gate_refs:
            return {"decision": "human_gate", "rule_refs": gate_refs,
                    "reason": "high-risk allow rule requires human gate"}
        if allow_refs:
            return {"decision": "allow", "rule_refs": allow_refs,
                    "reason": "published allow rule"}
        # 默认策略（无规则命中）
        if risk in ("high", "critical") or action in HIGH_RISK_ACTIONS:
            return {"decision": "human_gate", "rule_refs": [],
                    "reason": "default high-risk human gate"}
        if action in DEFAULT_ALLOW_ACTIONS:
            return {"decision": "allow", "rule_refs": [],
                    "reason": "default platform allowlist"}
        return {"decision": "deny", "rule_refs": [],
                "reason": "unknown action（fail-closed）"}


class GovernancePolicyHook:
    """Research/Knowledge/Memory 写入点的 policy 钩子接口（Task 4 只
    提供接口；业务写入在后续 Task 接入）。"""

    def __init__(self, store: Any) -> None:
        self._pdp = PolicyService(store)

    def check(self, context: Any, *, action: str, resource: str = "",
              risk: str = "") -> dict[str, Any]:
        d = context.to_dict() if hasattr(context, "to_dict") else context
        return self._pdp.evaluate(d, action=action, resource=resource,
                                  risk=risk)
