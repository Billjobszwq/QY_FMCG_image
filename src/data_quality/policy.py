"""四级分流规则（版本化阈值，手册§八 / Gate Q0）。

规则（qpol_v1）：
- reject 仅当：存在"不可恢复"的强信号，或 ≥2 个强信号组合；
- 单一弱指标绝不 reject（至多 warn/manual_review）；
- 可恢复性强信号或可恢复性不确定 → manual_review；
- 弱信号 → warn 并打 hard_valid 标签（困难但有效的照片保留进训练抽样）;
- 无信号 → accept。
阈值校准必须使用独立校准集，禁用 diagnostic_v1（手册§一.5）。"""
from __future__ import annotations

from .contracts import Finding, QualityVerdict, VERDICTS

POLICY_VERSION = "qpol_v1"
ANALYZER_VERSION = "qa_v3"  # qa_v3: 无ROI blur 改 edge_sharp_p99<8（calibration_v1+合成模糊校准）


def decide(findings: list, metrics: dict, image_sha256: str,
           policy_version: str = POLICY_VERSION,
           analyzer_version: str = ANALYZER_VERSION,
           source_uri: str = "") -> QualityVerdict:
    strong = [f for f in findings if f.severity == "strong"]
    weak = [f for f in findings if f.severity == "weak"]
    unrecoverable = [f for f in strong if f.recoverable is False]
    uncertain = [f for f in findings if f.recoverable is None]
    strong_recoverable = [f for f in strong if f.recoverable is True]

    reasons = tuple(f.name for f in findings if f.severity != "info")
    tags = tuple(sorted({f.name for f in weak}))

    if unrecoverable:
        verdict = "reject"
    elif len(strong) >= 2:
        verdict = "reject"
    elif strong_recoverable or uncertain:
        verdict = "manual_review"
    elif weak:
        verdict = "warn"
        tags = tuple(sorted({"hard_valid"} | set(tags)))
    else:
        verdict = "accept"

    assert verdict in VERDICTS
    return QualityVerdict(
        verdict=verdict,
        reasons=reasons,
        metrics=dict(metrics),
        quality_tags=tags,
        policy_version=policy_version,
        analyzer_version=analyzer_version,
        image_sha256=image_sha256,
        source_uri=source_uri,
        keep_original=True,
    )
