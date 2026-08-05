"""U2-1：统一任务中心 WorkItem API（角色首页数据源）。

聚合真实来源（禁止演示数据/伪造）：
- 人工审核队列：PLATFORM_REVIEW_QUEUE（默认 .review_queue/
  review_queue_diag_v1.json），pending 项逐条进入待办；
- 训练治理：training_run（计划待批准/已批准待提交/活动/历史）；
- 可恢复 Job：queued/running/failed；
- 标注批次：labeling_batch。

summary 默认业务语言（待办/活动/阻断/下一步）；M4/M5、hash 等
技术字段只进 detail。只读聚合端点，不需要登录。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter

REPO_ROOT = Path(__file__).resolve().parents[3]

_TRAIN_STATUS_CN = {
    "dry_run": "计划待批准",
    "approved": "已批准，待提交训练 Job",
    "queued": "已提交，等待执行",
    "running": "训练执行中",
    "completed": "已完成（candidate，未发布）",
    "failed": "失败",
    "cancelled": "已取消",
}


def _load_review_queue() -> dict[str, Any]:
    path = Path(os.environ.get(
        "PLATFORM_REVIEW_QUEUE",
        str(REPO_ROOT / ".review_queue" / "review_queue_diag_v1.json")))
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def collect_workitems(store: Any) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    blocked: list[str] = []
    next_steps: list[str] = []

    # ---- 人工审核队列（真实 pending，不得伪造完成） ----
    rq = _load_review_queue()
    rq_items = rq.get("items", []) if isinstance(rq, dict) else []
    pending_reviews = [it for it in rq_items
                       if it.get("status") == "pending"]
    for it in pending_reviews:
        items.append({
            "id": f"review:{it.get('photo_id', '?')}",
            "kind": "human_review",
            "status": "pending",
            "title": f"人工审核：{it.get('photo_id', '?')}",
            "owner": "标注审核员",
            "detail": {
                "photo_id": it.get("photo_id"),
                "review_mode": it.get("review_mode"),
                "protocol": rq.get("protocol") if isinstance(rq, dict) else None,
            },
        })
    if pending_reviews:
        next_steps.append(
            f"完成 {len(pending_reviews)} 张人工 truebox 审核"
            f"（协议 {rq.get('protocol', '?')}），训练晋级只认人工结论")

    # ---- 训练治理 ----
    authorized = store.get_flag("training_authorized") == "true"
    runs = store.list_training_runs()
    open_runs = 0
    for r in runs:
        status = r.get("status") or r.get("kind")
        title = _TRAIN_STATUS_CN.get(status, status)
        items.append({
            "id": f"training:{r['run_id']}",
            "kind": "training",
            "status": status,
            "title": f"训练任务：{title}",
            "owner": "admin" if status in ("approved", "queued", "running")
                     else "训练负责人",
            "detail": {
                "run_id": r["run_id"],
                "kind": r.get("kind"),
                "publish_status": r.get("publish_status"),
                "approved_by": r.get("approved_by"),
            },
        })
        if status in ("dry_run", "approved", "queued", "running"):
            open_runs += 1
    if not authorized:
        blocked.append("训练未获显式授权（training_authorized=false）；"
                       "批准计划与提交 Job 均需 admin 授权后操作")
    if open_runs == 0 and not pending_reviews:
        next_steps.append("无活动训练任务：平台处于 idle，未消耗训练算力")

    # ---- 可恢复 Job ----
    for j in store.list_jobs(limit=200):
        st = j.get("status")
        if st not in ("queued", "running", "failed"):
            continue
        if st == "failed":
            blocked.append(f"后台任务失败：{j.get('kind')}（{str(j.get('job_id'))[:8]}…）")
        items.append({
            "id": f"job:{j.get('job_id')}",
            "kind": "job",
            "status": st,
            "title": f"后台任务：{j.get('kind')}（{st}）",
            "owner": "系统",
            "detail": {"job_id": j.get("job_id"), "attempt_no": j.get("attempt_no")},
        })

    # ---- 标注批次 ----
    for b in store.list_labeling_batches():
        items.append({
            "id": f"labeling:{b.get('batch_id')}",
            "kind": "labeling",
            "status": b.get("status"),
            "title": f"标注批次：{b.get('name')}（{b.get('status')}）",
            "owner": "标注审核员",
            "detail": {"batch_id": b.get("batch_id"),
                       "task_count": b.get("task_count")},
        })

    todos = sum(1 for w in items if w["status"] in (
        "pending", "dry_run", "approved"))
    active = sum(1 for w in items if w["status"] in ("queued", "running"))
    if not next_steps:
        next_steps.append("按 IMPLEMENTATION-LIST 顺序推进下一任务")

    return {
        "count": len(items),
        "items": items,
        "summary": {
            "pending_review": len(pending_reviews),
            "todos": todos,
            "active": active,
            "blocked": blocked,
            "next_steps": next_steps,
        },
    }


def create_workitems_router(store: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/workitems")
    def workitems(limit: int = 100, offset: int = 0,
                  kind: str | None = None, status: str | None = None):
        """分页 + 筛选（UMT-109）：count 为筛选后总数。"""
        body = collect_workitems(store)
        items = body["items"]
        if kind:
            items = [w for w in items if w["kind"] == kind]
        if status:
            items = [w for w in items if w["status"] == status]
        total = len(items)
        page = items[max(offset, 0): max(offset, 0) + min(limit, 500)]
        return {**body, "count": total, "items": page}

    return router
