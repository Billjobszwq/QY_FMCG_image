"""L1 current 投影（Blackboard 语义的新实现，Task 6）。

旧 `BlackboardService`（blackboard_event_v1）保持只读兼容不变；新认知
写入统一走 memory_l1_event，current card 视图由 supersession 推导：
被后续事件 supersedes 的事件不再出现在 current 视图中（02 §4.1）。
双读收敛到单一 L1 账本在 Task 13 迁移阶段完成。

评审 #31 修复：supersession 先全量收集（不受 limit 窗口影响），
再应用 LIMIT 输出，避免窗口外的 supersedes 让被取代卡片“复活”。
"""
from __future__ import annotations

from typing import Any

from ..repository import CognitionRepository


def current_cards_from_l1(store: Any, *, task_id: str = "",
                          limit: int = 500) -> list[dict[str, Any]]:
    repo = CognitionRepository(store)
    # 超集扫描：先取足够大的全集计算 supersession，再做输出 LIMIT。
    rows = repo.list_l1(task_id=task_id, limit=max(limit * 10, 5000))
    superseded = {r["supersedes"] for r in rows if r["supersedes"]}
    current = [r for r in rows if r["event_id"] not in superseded]
    return current[:limit]
