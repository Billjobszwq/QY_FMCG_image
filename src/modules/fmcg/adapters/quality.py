"""VLM-006：照片质量评估适配器（S0 质量/证据检查）。

红线：
- 四级结论词汇冻结：pass / warn / manual_review / reject；
- 未知结论或后端异常一律 fail-closed 为 manual_review，不得伪造 pass；
- 每个判定保留原图 SHA、规则版本与证据引用（不可变）。
"""

from __future__ import annotations

from typing import Any, Callable

from src.modules.fmcg.cascade.manifest import CAP_QUALITY

QUALITY_VERDICTS = ("pass", "warn", "manual_review", "reject")


class QualityAdapter:
    capability_id = CAP_QUALITY

    def __init__(self, assess: Callable[[dict], dict], *, rule_version: str) -> None:
        self._assess = assess
        self._rule_version = rule_version

    def assess(self, image_ref: dict[str, Any]) -> dict[str, Any]:
        sha = image_ref.get("sha256")
        if not sha:
            from src.modules.fmcg.adapters import CapabilityAdapterError

            raise CapabilityAdapterError("image_ref 缺少 sha256（fail-closed）")
        evidence: dict[str, Any] = {"sha256": sha, "rule_version": self._rule_version}
        try:
            raw = self._assess(image_ref) or {}
        except Exception as e:  # 后端异常 → manual_review，不得伪造 pass
            evidence["error"] = str(e)
            return {"verdict": "manual_review", "scores": {}, "evidence": evidence}
        verdict = raw.get("verdict")
        if verdict not in QUALITY_VERDICTS:
            evidence["error"] = f"unknown_verdict:{raw.get('verdict')!r}"
            verdict = "manual_review"
        return {
            "verdict": verdict,
            "scores": dict(raw.get("scores") or {}),
            "evidence": evidence,
        }
