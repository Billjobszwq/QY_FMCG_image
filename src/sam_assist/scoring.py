"""候选质量评分与自动选择原因（手册§六.5/§七：选择原因与规则版本必须留痕）。"""
from __future__ import annotations

from typing import Optional

from .contracts import SamCandidate

RULES_VERSION = "rules_v1"


def score_candidates(candidates: list,
                     rules_version: str = RULES_VERSION) -> tuple[Optional[SamCandidate], str, str]:
    """从已过滤候选中选出自动推荐。

    返回 (best, selection_reason, rules_version)。无合格候选时 best=None。
    只接受 reject_reasons 为空的候选；评分仅用于排序，不放宽硬约束。"""
    valid = [c for c in candidates if not c.reject_reasons]
    if not valid:
        return None, "no_valid_candidate", rules_version
    best = max(valid, key=lambda c: (c.iou_score, c.stability_score, c.area_px))
    return best, "highest_valid_score", rules_version
