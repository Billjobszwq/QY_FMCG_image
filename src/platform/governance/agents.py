"""治理 Agent 受限角色（Task 4 / G2）。

角色“权力”由服务层方法可见性强制：
- RulesAgentRole：draft_rule / request_publish / list_rules —— 没有
  publish/decide_approval 方法（发布必须走人类批准账本）；
- SilentAgentRole：raise_alert / snapshot / request_pause —— 没有
  resolve_alert/resume 方法（闭环与恢复属于人类）。
"""
from __future__ import annotations

from typing import Any

from .alert_service import AlertService
from .pause_service import PauseService
from .policy_service import PolicyService


class RulesAgentRole:
    """Rules Agent：只起草与申请；不发布、不审批。"""

    def __init__(self, store: Any) -> None:
        self._svc = PolicyService(store)

    def draft_rule(self, *, actor: str, rule_id: str, allow: list[str],
                   deny: list[str], risk_level: str = "medium",
                   summary: str = "", **kw: Any) -> dict[str, Any]:
        return self._svc.draft_rule(actor=actor, rule_id=rule_id,
                                    allow=allow, deny=deny,
                                    risk_level=risk_level, summary=summary,
                                    **kw)

    def request_publish(self, *, rule_id: str, version: int,
                        requested_by: str) -> dict[str, Any]:
        return self._svc.request_publish(rule_id=rule_id, version=version,
                                         requested_by=requested_by)

    def list_rules(self) -> list[dict[str, Any]]:
        rows = self._svc.store._conn.execute(
            "SELECT * FROM policy_rule_version ORDER BY rule_id, version"
        ).fetchall()
        return [dict(r) for r in rows]


class SilentAgentRole:
    """Silent Agent：只告警/快照/暂停请求；不闭环、不恢复。"""

    def __init__(self, store: Any) -> None:
        self._alerts = AlertService(store)
        self._pauses = PauseService(store)

    def raise_alert(self, *, actor: str, severity: str, content: str,
                    rule_id: str = "", **kw: Any) -> dict[str, Any]:
        return self._alerts.raise_alert(actor=actor, role="silent_agent",
                                        severity=severity, content=content,
                                        rule_id=rule_id, **kw)

    def snapshot(self, *, actor: str, subject_type: str, subject_id: str,
                 state: dict[str, Any], alert_id: str = "") -> dict:
        return self._alerts.snapshot(actor=actor, role="silent_agent",
                                     subject_type=subject_type,
                                     subject_id=subject_id, state=state,
                                     alert_id=alert_id)

    def request_pause(self, *, actor: str, subject_type: str,
                      subject_id: str, reason: str,
                      alert_id: str = "") -> dict[str, Any]:
        return self._pauses.request_pause(actor=actor,
                                          subject_type=subject_type,
                                          subject_id=subject_id,
                                          reason=reason, alert_id=alert_id)
