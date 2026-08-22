"""cognition 测试共享工具：治理批准账本 + span 造数。"""
from __future__ import annotations

from typing import Any

from src.platform.cognition.repository import (
    CognitionRepository,
    UnitOfWork,
)
from src.platform.governance.policy_service import PolicyService


def approve(store: Any, *, kind: str, subject_ref: str,
            requested_by: str = "requester-agent",
            decider: str = "human-bill") -> str:
    """走真实治理批准账本：申请（requested_by）→ 人类决策（decider，
    maker≠checker），返回 approval_id。"""
    p = PolicyService(store)
    ap = p.request_generic_approval(kind=kind, subject_ref=subject_ref,
                                    requested_by=requested_by)
    p.decide_approval(ap["approval_id"], actor=decider,
                      decision="approved")
    return ap["approval_id"]


def mk_spans(store: Any, span_ids: list[str]) -> None:
    """为 knowledge 发布门造真实 span（不经 SourceService 的纯知识
    测试用）。幂等：已存在的 span 跳过。"""
    repo = CognitionRepository(store)
    existing = set()
    if span_ids:
        marks = ",".join("?" * len(span_ids))
        rows = store._conn.execute(
            f"SELECT span_id FROM cognition_evidence_span_v1 WHERE"
            f" span_id IN ({marks})", tuple(span_ids)).fetchall()
        existing = {r["span_id"] for r in rows}
    with UnitOfWork(store) as tx:
        for sid in span_ids:
            if sid in existing:
                continue
            repo.insert_span(tx, span_id=sid, chunk_id=sid,
                             quote_start=0, quote_end=1,
                             quote_hash="a" * 64, normalized_quote="x",
                             locator={"test": True},
                             created_at="2026-01-01T00:00:00+00:00")
