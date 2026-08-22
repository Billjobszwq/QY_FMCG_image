"""旧记忆表只读适配与层级映射（Task 6）。

`memory_entry_v1`（MemoryService）与 `agent_memory_v1`
（AgentRuntime.remember，L0-L4）仅提供只读迭代；任何迁移决策由
scripts/cognition_migrate_legacy.py 的 dry-run 输出，live 写入需另行
授权。迁移期间旧表禁止新增写入口（新代码一律写 memory_l1/l2/l3）。
"""
from __future__ import annotations

from typing import Any, Iterator


def iter_agent_memory(store: Any) -> Iterator[dict[str, Any]]:
    rows = store._conn.execute(
        "SELECT * FROM agent_memory_v1 ORDER BY created_at").fetchall()
    for r in rows:
        yield dict(r)


def iter_memory_entries(store: Any) -> Iterator[dict[str, Any]]:
    rows = store._conn.execute(
        "SELECT * FROM memory_entry_v1 ORDER BY valid_from").fetchall()
    for r in rows:
        yield dict(r)


def map_agent_memory_level(level: str) -> tuple[str, str]:
    """旧 L0-L4 → 新三层映射决策（L4/未知不强制映射为 L3）。"""
    lvl = (level or "").upper()
    if lvl in ("L0", "L1"):
        return "memory_l1_event", "原始事件层（append-only）"
    if lvl == "L2":
        return "memory_l2_candidate", "业务事件 candidate（需人工发布）"
    if lvl == "L3":
        return "memory_l3_candidate", "方法论 candidate（需人工发布）"
    return "quarantine_candidate", (
        f"无法确定含义的层级 {level!r}：进入 quarantine/candidate，"
        "不强制映射为 L3")
