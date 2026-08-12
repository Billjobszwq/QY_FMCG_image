"""UATCC：最终 Gate 判定器（fail-closed）。

存在任一 P0/P1、必填场景缺失、限流未实现、并行未证明时，
必须拒绝 READY_FOR_REAL_DATA_UAT。不得人工改名绕过。
"""
from __future__ import annotations

READY = "READY_FOR_REAL_DATA_UAT"


def evaluate_gate(*, p0_open: int, p1_open: int, rate_limit_ok: bool,
                  scenarios_ok: bool, parallel_ok: bool,
                  storefront_contract_ok: bool = True,
                  usage_lineage_ok: bool = True,
                  uat_v2_ok: bool = True,
                  v4_honesty_ok: bool = True) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if p0_open > 0:
        reasons.append(f"存在 {p0_open} 个未关闭 P0")
    if p1_open > 0:
        reasons.append(f"存在 {p1_open} 个未关闭 P1")
    if not rate_limit_ok:
        reasons.append("rate limit 未真实实现/未验证（BLOCKED_BY_RATE_LIMIT）")
    if not scenarios_ok:
        reasons.append("UAT 必填场景缺失（BLOCKED_BY_UAT_EVIDENCE）")
    if not parallel_ok:
        reasons.append("parallel 无真实并发证明（BLOCKED_BY_WORKFLOW_RUNTIME）")
    if not storefront_contract_ok:
        reasons.append("门头必拍契约未通过（BLOCKED_BY_PHOTO_CONTRACT）")
    if not usage_lineage_ok:
        reasons.append("Agent Usage 链路不完整（BLOCKED_BY_USAGE_LINEAGE）")
    if not uat_v2_ok:
        reasons.append("UAT V2 未完整执行（BLOCKED_BY_UAT_EVIDENCE）")
    if not v4_honesty_ok:
        reasons.append("V4 证据口径不诚实（BLOCKED_BY_UAT_EVIDENCE）")
    if reasons:
        gate = "BLOCKED_BY_" + (
            "P0" if p0_open else "P1" if p1_open else "CONTRACT")
        return gate, reasons
    return READY, []
