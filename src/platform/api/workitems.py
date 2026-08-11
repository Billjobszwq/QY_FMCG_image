"""U2-1：统一任务中心 WorkItem API（角色首页数据源）。

聚合真实来源（禁止演示数据/伪造）：
- 人工审核：review_task_v1 + review_event_v1 + 队列账本（DB 事件推导，
  任务书§八唯一事实源）；队列 JSON 只是不可变导入制品，不作运行状态；
- 训练治理：training_run（计划待批准/已批准待提交/活动/历史）；
- 可恢复 Job：queued/running/failed；
- 标注批次：labeling_batch。

ABOSV2-P0-001：统一 current task projection。
work_item_supersession_v1 账本记录被取代的工作族（旧审核队列、
legacy dry-run 等）；默认 projection=current 不含被取代项，
projection=history 只返回被取代历史，projection=all 全量。
历史行永不删除。

summary 默认业务语言（待办/活动/阻断/下一步）；M4/M5、hash 等
技术字段只进 detail。只读聚合端点，不需要登录。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from src.platform.annotate.review import review_progress
from src.platform.vocabulary import status_stage, status_text

PROJECTIONS = ("current", "history", "all")

_TRAIN_STATUS_CN = {
    "dry_run": "计划待批准",
    "approved": "已批准，待提交训练 Job",
    "queued": "已提交，等待执行",
    "running": "训练执行中",
    "completed": "已完成（candidate，未发布）",
    "failed": "失败",
    "cancelled": "已取消",
}


def _match_supersession(item: dict[str, Any],
                        sups: list[dict[str, Any]]) -> bool:
    """item 是否命中任一 supersession：family 相等且 match 中每个
    字段的 detail 值均在允许值列表内。"""
    for s in sups:
        if s.get("family") != item.get("kind"):
            continue
        match = s.get("match") or {}
        if not match:
            continue
        detail = item.get("detail") or {}
        if all(detail.get(k) in v for k, v in match.items()):
            return True
    return False


def ensure_documented_supersessions(store: Any) -> None:
    """幂等登记已有文档决定的 supersession（不改写历史；在投影聚合
    前调用，读端点自愈）。

    依据：
    - docs/README.md 2026-08-09：5+5+250 人工门 =
      SUPERSEDED_FOR_DEMO_TRAINING（不删除）；rq_v2 队列由 LS22
      micro-gold v2 取代（docs/implementation/micro-gold-v2-leakage-rebuild/
      STATUS：LS22 唯一有效人工入口）；
    - CODEX 手册 §5.6-6：4 个历史 dry-run 含当前 CLI 不支持的参数，
      必须标记 legacy/superseded，禁止批准或入队。
    """
    store.add_work_item_supersession(
        family="human_review",
        match={"queue_version": ["rq_v2"]},
        superseded_by="ls22_micro_gold_v2",
        reason=("rq_v2 250 人工审核门已被 micro-gold v2（LS22）取代；"
                "SUPERSEDED_FOR_DEMO_TRAINING，历史保留不删除"),
        decided_by="docs:README#2026-08-09;micro-gold-v2-leakage-rebuild")
    # legacy dry-run：仅当命令含当前 CLI 不支持的参数（如
    # --dataset/--budget-minutes）时登记，以现场 DB 事实逐条幂等处理；
    # 新建合法 dry-run 不受影响。
    for r in store.list_training_runs():
        cmd = r.get("command_json") or ""
        if (r.get("kind") == "dry_run" and r.get("status") == "dry_run"
                and r.get("publish_status") in (None, "", "none")
                and ("--budget-minutes" in cmd or '"--dataset"' in cmd)):
            store.add_work_item_supersession(
                family="training",
                match={"run_id": [r["run_id"]]},
                superseded_by="training_control_v2",
                reason=("历史 dry-run 含当前 CLI 不支持的参数（如"
                        " --dataset/--budget-minutes），标记 legacy，"
                        "禁止批准或入队"),
                decided_by="docs:CODEX-PROJECT-HANDBOOK#5.6-6")


def collect_workitems(store: Any,
                      projection: str = "current") -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    blocked: list[str] = []
    next_steps: list[str] = []

    # ---- ABOSV3-P0-002：WorkItemV2 控制平面主线（统一 current 真相）
    # 首页/主管/任务板必须消费同一投影；不得另建平行任务源。
    proj = store.rebuild_work_projection()
    _V2_STAGE = {"todo": "todo", "running": "active", "waiting": "todo",
                 "approval": "approval", "blocked": "blocked",
                 "done": "done", "cancelled": "done"}
    _V2_TEXT = {"todo": "待处理", "running": "运行中",
                "waiting": "等待人工", "approval": "待批准",
                "blocked": "阻断", "done": "已完成",
                "cancelled": "已取消"}
    for it in proj["items"]:
        st = it["status"]
        items.append({
            "id": it["work_id"],
            "kind": "work_item_v2",
            "status": st,
            "status_text": _V2_TEXT.get(st, st),
            "stage": _V2_STAGE.get(st, "todo"),
            "title": it.get("title") or f"控制平面工作：{it['work_id'][:16]}",
            "owner": it.get("owner_id") or "系统",
            "detail": {"run_id": it.get("run_id", ""),
                       "subject_type": it.get("subject_type", ""),
                       "subject_id": it.get("subject_id", ""),
                       "blockers": it.get("blockers", [])},
        })

    # ---- 人工审核（唯一事实源 = DB 事件推导，不得伪造完成） ----
    progress = review_progress(store)
    review_tasks = progress["active"]["tasks"]
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

    # ---- 训练治理 ----
    authorized = store.get_flag("training_authorized") == "true"
    runs = store.list_training_runs()
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
    if not authorized:
        blocked.append("训练未获显式授权（training_authorized=false）；"
                       "批准计划与提交 Job 均需 admin 授权后操作")

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

    if not next_steps:
        next_steps.append("按 IMPLEMENTATION-LIST 顺序推进下一任务")

    # ---- ABOSV2-P0-001：supersession 账本驱动 current/history 分离 ----
    ensure_documented_supersessions(store)
    sups = store.list_work_item_supersessions()
    for w in items:
        w["superseded"] = _match_supersession(w, sups)
    superseded_count = sum(1 for w in items if w["superseded"])
    if projection == "current":
        visible = [w for w in items if not w["superseded"]]
    elif projection == "history":
        visible = [w for w in items if w["superseded"]]
    else:
        visible = items

    # next_steps 只对可见（未被取代）工作诚实生成
    if projection in ("current", "all"):
        cur_open_reviews = [w for w in visible
                            if w["kind"] == "human_review"
                            and w["status"] != "finalized"]
        cur_open_runs = [w for w in visible
                         if w["kind"] == "training" and w["status"] in
                         ("dry_run", "approved", "queued", "running")]
        if cur_open_reviews:
            next_steps.insert(0,
                              f"完成 {len(cur_open_reviews)} 项人工 truebox 审核"
                              f"，训练晋级只认人工结论")
        if not cur_open_runs and not cur_open_reviews:
            next_steps.insert(
                0, "无活动训练任务：平台处于 idle，未消耗训练算力")

    return {
        "count": len(visible),
        "items": visible,
        "projection": projection,
        "summary": {
            "pending_review": sum(
                1 for w in visible
                if w["kind"] == "human_review" and w["status"] == "pending"),
            "todos": sum(1 for w in visible if w["status"] in (
                "pending", "claimed", "awaiting_second",
                "awaiting_arbitration", "dry_run", "approved")),
            "active": sum(1 for w in visible
                           if w["status"] in ("queued", "running")),
            "superseded": superseded_count,
            "blocked": blocked,
            "next_steps": next_steps,
        },
    }


def create_workitems_router(store: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/workitems")
    def workitems(limit: int = 100, offset: int = 0,
                  kind: str | None = None, status: str | None = None,
                  projection: str = "current"):
        """分页 + 筛选（UMT-109）；projection=current 为唯一默认当前视图：
        被 supersession 取代的工作族只进 history，不进当前待办。"""
        if projection not in PROJECTIONS:
            raise HTTPException(
                422, f"projection 只支持 {PROJECTIONS}，收到 {projection!r}")
        body = collect_workitems(store, projection=projection)
        items = body["items"]
        if kind:
            items = [w for w in items if w["kind"] == kind]
        if status:
            items = [w for w in items if w["status"] == status]
        total = len(items)
        page = items[max(offset, 0): max(offset, 0) + min(limit, 500)]
        return {**body, "count": total, "items": page}

    return router
