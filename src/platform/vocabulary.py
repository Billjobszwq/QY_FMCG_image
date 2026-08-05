"""U2-4：统一任务状态词汇（业务语言默认，技术字段折叠）。

手册 §4：标注、审核、训练、识别、Graph Run 使用统一任务状态；
默认使用业务语言，M4/M5、hash 和 raw JSON 放到高级详情。

UNIFIED_STATUS：业务语言 → 阶段分组（todo/active/done/blocked），
前端据此选配色。status_text(kind, raw)：把各子系统的英文技术状态
翻译成统一业务语言；未知状态回显原文（fail-closed，不伪造）。
"""
from __future__ import annotations

UNIFIED_STATUS: dict[str, str] = {
    "待批准": "todo",
    "已批准": "todo",
    "待人工审核": "todo",
    "待认领": "todo",
    "等待人工": "todo",
    "等待执行": "active",
    "执行中": "active",
    "审核中": "active",
    "已完成": "done",
    "已取消": "done",
    "失败": "blocked",
}

_KIND_STATUS: dict[str, dict[str, str]] = {
    "training": {
        "dry_run": "待批准",
        "approved": "已批准",
        "queued": "等待执行",
        "running": "执行中",
        "completed": "已完成",
        "failed": "失败",
        "cancelled": "已取消",
    },
    "job": {
        "queued": "等待执行",
        "running": "执行中",
        "succeeded": "已完成",
        "failed": "失败",
        "cancelled": "已取消",
    },
    "human_review": {
        "pending": "待人工审核",
        "in_review": "审核中",
        "accepted": "已完成",
        "rejected": "失败",
    },
    "recognition": {
        "completed": "已完成",
        "failed": "失败",
    },
    "labeling": {
        "pending": "待认领",
        "open": "待认领",
        "running": "执行中",
        "in_progress": "审核中",
        "completed": "已完成",
        "failed": "失败",
    },
    "graph_run": {
        "pending": "等待执行",
        "running": "执行中",
        "waiting_human": "等待人工",
        "completed": "已完成",
        "failed": "失败",
        "cancelled": "已取消",
    },
}


def status_text(kind: str, status: str | None) -> str:
    """统一业务语言：未知状态回显原文（fail-closed，不伪造）。"""
    if not status:
        return "未知"
    return _KIND_STATUS.get(kind, {}).get(status, status)


def status_stage(business_text: str) -> str:
    """业务语言 → 阶段分组（todo/active/done/blocked），未知归 active。"""
    return UNIFIED_STATUS.get(business_text, "active")
