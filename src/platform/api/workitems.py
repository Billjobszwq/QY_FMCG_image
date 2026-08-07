"""U2-1：统一任务中心 WorkItem API（角色首页数据源）。

聚合真实来源（禁止演示数据/伪造）：
- 人工审核：review_task_v1 + review_event_v1 + 队列账本（DB 事件推导，
  任务书§八唯一事实源）；队列 JSON 只是不可变导入制品，不作运行状态；
- 训练治理：training_run（计划待批准/已批准待提交/活动/历史）；
- 可恢复 Job：queued/running/failed；
- 标注批次：labeling_batch。

summary 默认业务语言（待办/活动/阻断/下一步）；M4/M5、hash 等
技术字段只进 detail。只读聚合端点，不需要登录。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from src.platform.annotate.review import review_progress
from src.platform.vocabulary import status_stage, status_text

_TRAIN_STATUS_CN = {
    "dry_run": "计划待批准",
    "approved": "已批准，待提交训练 Job",
    "queued": "已提交，等待执行",
    "running": "训练执行中",
    "completed": "已完成（candidate，未发布）",
    "failed": "失败",
    "cancelled": "已取消",
}


def collect_workitems(store: Any) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    blocked: list[str] = []
    next_steps: list[str] = []

    # ---- 人工审核（唯一事实源 = DB 事件推导，不得伪造完成） ----
    progress = review_progress(store)
    review_tasks = progress["active"]["tasks"]
    open_reviews = [tk for tk in review_tasks
                    if tk["status"] != "finalized"]
    for tk in review_tasks:
        items.append({
            "id": f"review:{tk['task_id']}",
            "kind": "human_review",
            "status": tk["status"],
            "status_text": status_text("human_review", tk["status"]),
            "stage": status_stage(
                status_text("human_review", tk["status"])),
            "title": f"人工审核：{tk['photo_id']}",
            "owner": "标注审核员",
            "detail": {
                "photo_id": tk["photo_id"],
                "review_mode": tk["review_mode"],
                "queue_version": tk["queue_version"],
                "protocol": tk.get("protocol") or None,
            },
        })
    if open_reviews:
        next_steps.append(
            f"完成 {len(open_reviews)} 项人工 truebox 审核"
            f"，训练晋级只认人工结论")

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
            "status_text": status_text("training", status),
            "stage": status_stage(status_text("training", status)),
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
    if open_runs == 0 and not open_reviews:
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
            "status_text": status_text("job", st),
            "stage": status_stage(status_text("job", st)),
            "title": f"后台任务：{j.get('kind')}（{status_text('job', st)}）",
            "owner": "系统",
            "detail": {"job_id": j.get("job_id"), "attempt_no": j.get("attempt_no")},
        })

    # ---- 标注批次 ----
    for b in store.list_labeling_batches():
        items.append({
            "id": f"labeling:{b.get('batch_id')}",
            "kind": "labeling",
            "status": b.get("status"),
            "status_text": status_text("labeling", b.get("status")),
            "stage": status_stage(
                status_text("labeling", b.get("status"))),
            "title": (f"标注批次：{b.get('name')}"
                      f"（{status_text('labeling', b.get('status'))}）"),
            "owner": "标注审核员",
            "detail": {"batch_id": b.get("batch_id"),
                       "task_count": b.get("task_count")},
        })

    todos = sum(1 for w in items if w["status"] in (
        "pending", "claimed", "awaiting_second", "awaiting_arbitration",
        "dry_run", "approved"))
    active = sum(1 for w in items if w["status"] in ("queued", "running"))
    if not next_steps:
        next_steps.append("按 IMPLEMENTATION-LIST 顺序推进下一任务")

    return {
        "count": len(items),
        "items": items,
        "summary": {
            "pending_review": sum(
                1 for tk in review_tasks if tk["status"] == "pending"),
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
