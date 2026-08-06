"""VLM-005：级联风险校准路由（规格 §6）。

红线：
- 禁止跨模型原始置信度直连路由：没有校准器（calibrator=None）时
  一律抛 CalibrationUnavailable，raw score 不得当概率承诺；
- 硬属性冲突（ocr_conflicts / attribute_conflicts）强制升级到 S4；
  超出档位 max_stage 或已在 S4 时转人工；
- NaN/Inf/缺 top1 → route=human（fail-closed，不得 accepted）；
- 未识别 stage → RiskComputationError（受控错误）；
- 校准器只读取冻结 JSON 制品并验证 SHA256；bootstrap_rule_v1 是
  规则启发式，kind 明确标注，不得声称是概率校准。
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.modules.fmcg.cascade.contracts import RiskDecision
from src.modules.fmcg.cascade.policy import ResolvedPolicy

# 参与风险决策的阶段（S5 是人工审核，不产生校准路由）
RISK_STAGES = ("S1", "S2", "S3", "S4")
_NEXT_STAGE = {"S1": "S2", "S2": "S3", "S3": "S4"}
_STAGE_THRESHOLD = {
    "S1": "fast_accept_risk",
    "S2": "medium_accept_risk",
    "S3": "deep_accept_risk",
    "S4": "expert_accept_risk",
}


class CalibrationUnavailable(Exception):
    """缺少校准器（禁止用 raw confidence 路由）。"""


class CalibratorTamperedError(Exception):
    """校准器制品 SHA256 与冻结记录不一致。"""


class RiskComputationError(Exception):
    """受控错误：未识别 stage 等，不得静默降级为 accepted。"""


@dataclass(frozen=True)
class Calibrator:
    """校准器制品。kind=bootstrap_rule 表示规则启发式，不是概率校准。"""

    calibrator_version: str
    kind: str
    params: dict[str, float] = field(default_factory=dict)


def bootstrap_rule_v1() -> Calibrator:
    """初期规则启发式（明确标注，不得称为概率校准）。参数冻结。"""
    return Calibrator(
        calibrator_version="bootstrap_rule_v1",
        kind="bootstrap_rule",
        params={"w_top1": 0.60, "w_margin": 0.25, "w_entropy": 0.15,
                "entropy_norm": 2.0},
    )


def load_calibrator(path: Path | str, *, expected_sha256: str) -> Calibrator:
    """读取冻结校准器 JSON 制品并验证 SHA256（fail-closed）。"""
    p = Path(path)
    if not p.exists():
        raise CalibrationUnavailable(f"校准器制品不存在: {p}")
    blob = p.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    if digest != expected_sha256.lower():
        raise CalibratorTamperedError(
            f"校准器制品被篡改: {p}（sha256={digest}，期望 {expected_sha256}）"
        )
    data = json.loads(blob.decode("utf-8"))
    return Calibrator(
        calibrator_version=str(data["calibrator_version"]),
        kind=str(data["kind"]),
        params={k: float(v) for k, v in (data.get("params") or {}).items()},
    )


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def decide_risk(
    *,
    stage: str,
    signals: dict[str, Any],
    calibrator: Calibrator | None,
    policy: ResolvedPolicy,
) -> RiskDecision:
    """校准风险路由：只有 calibrated_risk 才能跨模型路由。"""
    if calibrator is None:
        raise CalibrationUnavailable(
            "缺少校准器：raw confidence 不得直接路由（fail-closed）"
        )
    if stage not in RISK_STAGES:
        raise RiskComputationError(f"未识别 stage: {stage!r}（合法: {RISK_STAGES}）")

    # NaN/Inf fail-closed：任何数值信号非有限 → 转人工
    bad = [
        k for k, v in signals.items()
        if isinstance(v, float) and not math.isfinite(v)
    ]
    if bad:
        return RiskDecision(
            route="human", risk=1.0, next_stage=None,
            calibrator_version=calibrator.calibrator_version,
            reasons=[f"non_finite_signals:{','.join(sorted(bad))}", "fail_closed"],
        )

    # 关键信号缺失 fail-closed
    if "top1" not in signals:
        return RiskDecision(
            route="human", risk=1.0, next_stage=None,
            calibrator_version=calibrator.calibrator_version,
            reasons=["missing_signal:top1", "fail_closed"],
        )

    # 硬属性冲突：强制升级 S4（超档或已在 S4 → 人工）
    conflicts = [
        c for key in ("ocr_conflicts", "attribute_conflicts")
        for c in (signals.get(key) or [])
    ]
    if conflicts:
        return _escalate_or_human(
            stage=stage, policy=policy,
            risk=1.0,
            calibrator_version=calibrator.calibrator_version,
            reasons=[f"hard_conflict:{c}" for c in conflicts],
        )

    # bootstrap 规则风险（不是概率校准）
    p = calibrator.params
    top1 = _clamp(float(signals["top1"]))
    margin = _clamp(float(signals.get("margin", 0.0)))
    entropy_norm = float(p.get("entropy_norm", 2.0))
    entropy = _clamp(float(signals.get("entropy", entropy_norm)) / entropy_norm)
    risk = (
        float(p.get("w_top1", 0.60)) * (1.0 - top1)
        + float(p.get("w_margin", 0.25)) * (1.0 - margin)
        + float(p.get("w_entropy", 0.15)) * entropy
    )
    reasons: list[str] = []

    # 辅助信号惩罚项（保守方向）
    risk += 0.10 * _clamp(float(signals.get("ood_score", 0.0)))
    risk += 0.10 * _clamp(float(signals.get("package_novelty", 0.0)))
    if float(signals.get("detection_stability", 1.0)) < 0.5:
        risk += 0.05
        reasons.append("low_detection_stability")
    if float(signals.get("sam_area_delta", 0.0)) > 0.5:
        risk += 0.05
        reasons.append("large_sam_area_delta")
    if float(signals.get("retrieval_margin", 1.0)) < 0.1:
        risk += 0.05
        reasons.append("low_retrieval_margin")
    if float(signals.get("quality_score", 1.0)) < 0.5:
        risk += 0.05
        reasons.append("low_quality_score")
    risk = _clamp(risk)

    threshold = float(getattr(policy.policy, _STAGE_THRESHOLD[stage]))
    if risk <= threshold:
        return RiskDecision(
            route="accept", risk=risk, next_stage=None,
            calibrator_version=calibrator.calibrator_version,
            reasons=[f"risk={risk:.4f}<=threshold={threshold:.4f}", *reasons],
        )
    return _escalate_or_human(
        stage=stage, policy=policy, risk=risk,
        calibrator_version=calibrator.calibrator_version,
        reasons=[f"risk={risk:.4f}>threshold={threshold:.4f}", *reasons],
    )


def _escalate_or_human(
    *,
    stage: str,
    policy: ResolvedPolicy,
    risk: float,
    calibrator_version: str,
    reasons: list[str],
) -> RiskDecision:
    """升级路由：下一阶段超出档位 max_stage 时转人工（fail-closed）。"""
    if stage not in _NEXT_STAGE:
        return RiskDecision(
            route="human", risk=risk, next_stage=None,
            calibrator_version=calibrator_version,
            reasons=[*reasons, "no_next_stage"],
        )
    nxt = _NEXT_STAGE[stage]
    if nxt > policy.max_stage:
        return RiskDecision(
            route="human", risk=risk, next_stage=None,
            calibrator_version=calibrator_version,
            reasons=[*reasons, f"next_stage_blocked_by_tier:{policy.tier}"],
        )
    return RiskDecision(
        route="escalate", risk=risk, next_stage=nxt,  # type: ignore[arg-type]
        calibrator_version=calibrator_version, reasons=reasons,
    )
