"""审核来源状态机（手册§七）：追加式事件日志，保留全部前版。

状态流：
  auto_proposed → annotator_accepted / annotator_corrected / annotator_manual
  annotator_*   → reviewer_accepted / reviewer_rejected
  reviewer_rejected → annotator_*（返工）或 adjudicated（仲裁）
终态：reviewer_accepted / adjudicated。
只有终态事件才能提供 final_box；SAM prediction（auto_proposed）永远不是最终标注。"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Optional

ALLOWED_TRANSITIONS = {
    None: {"auto_proposed", "annotator_manual"},
    "auto_proposed": {"annotator_accepted", "annotator_corrected",
                      "annotator_manual", "reviewer_rejected"},
    "annotator_accepted": {"reviewer_accepted", "reviewer_rejected"},
    "annotator_corrected": {"reviewer_accepted", "reviewer_rejected"},
    "annotator_manual": {"reviewer_accepted", "reviewer_rejected"},
    "reviewer_rejected": {"annotator_accepted", "annotator_corrected",
                          "annotator_manual", "adjudicated"},
    "reviewer_accepted": set(),
    "adjudicated": set(),
}

FINAL_STATES = {"reviewer_accepted", "adjudicated"}


@dataclass(frozen=True)
class AnnotationEvent:
    event_id: str
    instance_id: str
    state: str
    actor: str
    timestamp: float
    box: Optional[tuple]
    reason: str
    prev_event_id: Optional[str]


class ProvenanceLog:
    """内存版来源日志（持久化由 LS webhook/warehouse 承担，见 ls_platform）。"""

    def __init__(self):
        self._events: dict[str, list[AnnotationEvent]] = {}

    def append(self, instance_id: str, state: str, actor: str,
               box: tuple | None = None, reason: str = "") -> AnnotationEvent:
        if not actor:
            raise ValueError("actor 必填（真实人员/worker 标识）")
        if state not in ALLOWED_TRANSITIONS or state is None:
            raise ValueError(f"未知状态: {state}")
        cur = self.current_state(instance_id)
        allowed = ALLOWED_TRANSITIONS.get(cur, set())
        if state not in allowed:
            raise ValueError(f"非法状态迁移: {cur!r} → {state!r}")
        prev = self._events.get(instance_id, [])
        ev = AnnotationEvent(
            event_id=uuid.uuid4().hex,
            instance_id=instance_id,
            state=state,
            actor=actor,
            timestamp=time.time(),
            box=tuple(box) if box is not None else None,
            reason=reason,
            prev_event_id=prev[-1].event_id if prev else None,
        )
        self._events.setdefault(instance_id, []).append(ev)
        return ev

    def events(self, instance_id: str) -> list:
        return list(self._events.get(instance_id, []))

    def current_state(self, instance_id: str) -> Optional[str]:
        evs = self._events.get(instance_id)
        return evs[-1].state if evs else None

    def is_finalized(self, instance_id: str) -> bool:
        return self.current_state(instance_id) in FINAL_STATES

    def final_box(self, instance_id: str) -> Optional[tuple]:
        """仅终态（人工确认/仲裁）提供最终框；prediction 阶段恒为 None。"""
        if not self.is_finalized(instance_id):
            return None
        return self._events[instance_id][-1].box
