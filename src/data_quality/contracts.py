"""四级质量结果与指标契约（手册§八）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

VERDICTS = ("accept", "warn", "manual_review", "reject")

SEVERITIES = ("info", "weak", "strong")


@dataclass(frozen=True)
class Finding:
    """单个分析器产出的问题信号。

    severity: info（仅记录）/ weak（弱指标）/ strong（强证据）
    recoverable: True=可恢复, False=不可恢复, None=不确定（→人工）"""
    name: str
    severity: str
    recoverable: Optional[bool] = True
    detail: str = ""


@dataclass(frozen=True)
class QualityVerdict:
    verdict: str                       # VERDICTS 之一
    reasons: tuple                     # 触发规则/信号名
    metrics: dict                      # 原始指标
    quality_tags: tuple                # 如 hard_valid、reflection
    policy_version: str                # 阈值与规则版本
    analyzer_version: str              # 分析器算法版本
    image_sha256: str                  # 原图哈希（证据锚点）
    source_uri: str = ""
    keep_original: bool = True         # 恒 True：原图永不删除/移动
