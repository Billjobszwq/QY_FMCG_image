"""GLTC Task 10：通道评估口径与候选登记（02 计划 Task 10）。

- 四 lane 最低评估指标集冻结（不得用代理指标冒充）；
- 只有同口径冻结集（frozen_set_hash）+ 完整 error ledger 才能
  生成 Candidate；
- candidate 登记永不切换生产（production_switch 恒 False）。
"""
from __future__ import annotations

from typing import Any

from . import vocabulary as V


class EvaluationError(RuntimeError):
    """评估契约错误（fail-closed）。"""


# 各 lane 最低评估指标（冻结；新增需修订契约 + 测试）
LANE_MIN_METRICS: dict[str, tuple[str, ...]] = {
    "detector": ("recall_at_fp1", "recall_at_fp3", "iou_050", "iou_075",
                 "duplicate_fp", "background_fp", "localization_err"),
    "classifier": ("top1", "macro_f1", "unknown_far", "coverage_risk",
                   "package_version_acc"),
    "segmenter": ("mask_iou", "boundary_f", "instance_merge_rate",
                  "truncation_rate", "downstream_gain", "extra_latency_ms"),
    "vlm": ("candidate_recall_at_k", "accepted_precision", "coverage",
            "abstain_rate", "registry_escape", "p95_latency_ms",
            "tokens_per_region"),
}

# 默认晋级阈值（保守；正式实验以批准的计划为准，不得低于此）
_DEFAULT_THRESHOLDS: dict[str, dict[str, float]] = {
    "detector": {"recall_at_fp3": 0.3},
    "classifier": {"top1": 0.3, "macro_f1": 0.3},
    "segmenter": {"mask_iou": 0.3},
    "vlm": {"accepted_precision": 0.5, "coverage": 0.1},
}


def validate_evaluation_report(lane: str, report: dict[str, Any], *,
                               frozen_set_hash: str = "",
                               error_ledger: list[dict] | None = None
                               ) -> dict[str, Any]:
    """指标完整性校验：缺任何最低指标即拒绝。"""
    if lane not in V.TRAINING_LANES:
        raise EvaluationError(f"非法 lane: {lane}")
    missing = [k for k in LANE_MIN_METRICS[lane] if k not in report]
    if missing:
        raise EvaluationError(
            f"{lane} 评估报告缺最低指标: {missing}")
    return {"ok": True, "lane": lane,
            "metrics_checked": list(LANE_MIN_METRICS[lane]),
            "frozen_set_hash": frozen_set_hash,
            "ledger_entries": len(error_ledger or [])}


def default_gate(lane: str, report: dict[str, Any]) -> dict[str, Any]:
    """默认晋级门（阈值见 _DEFAULT_THRESHOLDS）。"""
    checks = []
    for metric, th in _DEFAULT_THRESHOLDS[lane].items():
        val = float(report.get(metric, 0.0))
        checks.append({"metric": metric, "value": val,
                       "threshold": th, "ok": val >= th})
    if lane == "vlm":
        esc = float(report.get("registry_escape", 1.0))
        checks.append({"metric": "registry_escape", "value": esc,
                       "threshold": 0.0, "ok": esc == 0.0})
    return {"pass": all(c["ok"] for c in checks), "checks": checks}


vlm_gate = lambda report: default_gate("vlm", report)  # noqa: E731


def register_candidate(run_id: str, lane: str, report: dict[str, Any], *,
                       frozen_set_hash: str,
                       error_ledger: list[dict],
                       gate: dict[str, Any] | None = None
                       ) -> dict[str, Any]:
    """Candidate 登记：冻结集 hash + error ledger + 晋级门缺一不可。

    production_switch 恒为 False：发布是独立审批，训练完成不切换生产。
    """
    validate_evaluation_report(lane, report,
                               frozen_set_hash=frozen_set_hash,
                               error_ledger=error_ledger)
    if not frozen_set_hash:
        raise EvaluationError("candidate 必须绑定同口径冻结集 hash")
    if not error_ledger:
        raise EvaluationError("candidate 必须附完整 error ledger")
    g = gate or default_gate(lane, report)
    if not g.get("pass"):
        failed = [c["metric"] for c in g.get("checks", [])
                  if not c.get("ok")]
        raise EvaluationError(f"晋级门未通过: {failed}")
    return {"run_id": run_id, "lane": lane,
            "status": "CANDIDATE_READY",
            "frozen_set_hash": frozen_set_hash,
            "gate": g, "production_switch": False,
            "note": "shadow 与发布需独立审批"}
