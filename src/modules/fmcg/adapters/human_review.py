"""VLM-012：人工审核交接适配器（S5）。

红线：
- 人工审核是唯一可覆盖 unknown/新包装/预算耗尽的终局裁决通道；
- 交接必须携带 run、阶段、原因与证据 ID（审计可回放），
  不得记录密钥或 prompt 内客户敏感数据；
- 人工裁决前系统只能保持 waiting_human，不得自动 accepted。
"""

from __future__ import annotations

from typing import Any

from src.modules.fmcg.cascade.manifest import CAP_HUMAN

REVIEW_REASONS = (
    "unknown_sku", "new_package", "budget_exhausted", "sla_expired",
    "vlm_unavailable", "quality_manual_review", "risk_human",
)


class HumanReviewAdapter:
    capability_id = CAP_HUMAN

    def handoff(
        self,
        *,
        run_id: str,
        stage: str,
        reason: str,
        policy_version: str,
        risk: float | None = None,
        evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """生成交接单（只写审计字段，不触发任何自动决策）。"""
        return {
            "capability_id": self.capability_id,
            "run_id": run_id,
            "stage": stage,
            "reason": reason,
            "policy_version": policy_version,
            "risk": risk,
            "evidence_ids": list(evidence_ids or []),
            "resolution": None,  # 待人工填写
        }

    def resolve(self, handoff: dict[str, Any], *,
                decision: str, sku_id: str | None = None,
                evidence_ids: list[str] | None = None) -> dict[str, Any]:
        """登记人工裁决（accepted 必须携带 sku_id 与证据）。"""
        if decision == "accepted" and (not sku_id or not evidence_ids):
            raise ValueError("人工 accepted 必须携带 sku_id 与证据 ID")
        return {**handoff,
                "resolution": {"decision": decision, "sku_id": sku_id,
                               "evidence_ids": list(evidence_ids or [])}}
