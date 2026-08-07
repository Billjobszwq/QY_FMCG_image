"""U4-4：分批扩展阶梯与质量门（100→500→2,000→全 eligible）。

口径（手册 §七/U4）：
- 诊断批（diagnostic_v1，250 条）先行；通过后按 BATCH_LADDER
  逐批扩展；任何批次质量不达标立即停止；
- 批次未完成（存在非终态任务）→ waiting_human，禁止伪造通过；
- 质量门：双审一致率 = 未经仲裁终态的双审任务 / 全部双审终态任务，
  低于 GATE_AGREEMENT → gate_failed，扩展拒绝（需人工整改）；
- 批次标签使用 review_task_v1.protocol 列（不可变），不新增表。
"""
from __future__ import annotations

import secrets
from typing import Any

from .review import _derive_status

# 阶梯：诊断批通过后依次扩展 100 / 500 / 2,000 / 全 eligible(-1)
BATCH_LADDER: tuple[int, ...] = (100, 500, 2000, -1)
GATE_AGREEMENT = 0.8

DIAGNOSTIC = "diagnostic_v1"
_BATCH_ORDER = (DIAGNOSTIC, "batch1_v1", "batch2_v1", "batch3_v1",
                "batch4_v1")


def _tasks_by_protocol(store) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for t in store.list_review_tasks():
        out.setdefault(t["protocol"] or DIAGNOSTIC, []).append(t)
    return out


def batch_report(store, protocol: str) -> dict[str, Any]:
    """单批质量报告：完成度 + 双审一致率（只统计真实终态事件）。

    统一状态源（任务书§八）：只统计 active 队列任务；失效队列
    （如 rq_v1 invalid_id_sha_mapping）的历史行保留但不计入，
    不得阻断 active 批次的进度与后续阶梯。"""
    tasks = [t for t in store.list_review_tasks_active()
             if (t["protocol"] or DIAGNOSTIC) == protocol]
    n_total = len(tasks)
    n_finalized = 0
    dbl_fin = dbl_agreed = 0
    for t in tasks:
        st = _derive_status(store, t)
        if st["status"] != "finalized":
            continue
        n_finalized += 1
        if t["requires_second_review"]:
            dbl_fin += 1
            has_arbiter = any(e["role"] == "arbiter"
                              for e in store.list_review_events(
                                  t["task_id"])
                              if e["kind"] == "review")
            dbl_agreed += 0 if has_arbiter else 1
    agreement = (dbl_agreed / dbl_fin) if dbl_fin else None
    return {
        "protocol": protocol,
        "n_total": n_total,
        "n_finalized": n_finalized,
        "complete": n_total > 0 and n_finalized == n_total,
        "double_finalized": dbl_fin,
        "agreement_rate": agreement,
    }


def _current_stage(store) -> str:
    by_proto = _tasks_by_protocol(store)
    stage = None
    for p in _BATCH_ORDER:
        if p in by_proto:
            stage = p
    if stage is None:
        raise ValueError("审核队列为空，无法规划批次")
    return stage


def next_batch_plan(store) -> dict[str, Any]:
    """规划下一批：未完成→waiting_human；不达标→gate_failed；
    达标→ready + 阶梯 next_size。"""
    stage = _current_stage(store)
    rep = batch_report(store, stage)
    plan: dict[str, Any] = {"stage": stage, **rep}
    if not rep["complete"]:
        plan.update(status="waiting_human", next_size=None)
        plan["note"] = "人工未完成只能 waiting_human，禁止伪造通过"
        return plan
    rate = rep["agreement_rate"]
    if rate is not None and rate < GATE_AGREEMENT:
        plan.update(status="gate_failed", next_size=None)
        plan["note"] = (f"双审一致率 {rate:.2f} < {GATE_AGREEMENT}，"
                        "任何批次质量不达标立即停止")
        return plan
    idx = _BATCH_ORDER.index(stage) - 1  # 诊断批 idx=-1 → 阶梯 0
    if idx + 1 >= len(BATCH_LADDER):
        plan.update(status="done", next_size=None)
        plan["note"] = "全 eligible 批次已完成，无后续阶梯"
        return plan
    plan.update(status="ready", next_size=BATCH_LADDER[idx + 1])
    return plan


def expand_review_batch(store, *, items: list[dict[str, Any]],
                        protocol: str) -> dict[str, Any]:
    """扩展新批：前置门必须 ready；幂等键同 review 导入；
    对已存在批次的重复导入（幂等重入）不受门控阻止。"""
    if protocol not in _BATCH_ORDER:
        raise ValueError(f"非法批次 protocol: {protocol}")
    existing = any((t["protocol"] or DIAGNOSTIC) == protocol
                   for t in store.list_review_tasks())
    if not existing:
        plan = next_batch_plan(store)
        if plan["status"] != "ready":
            raise ValueError(
                f"当前批次 {plan['stage']} 状态 {plan['status']}，禁止扩展")
        if protocol != _BATCH_ORDER[
                _BATCH_ORDER.index(plan["stage"]) + 1]:
            nxt = _BATCH_ORDER[_BATCH_ORDER.index(plan["stage"]) + 1]
            raise ValueError(f"必须按阶梯顺序扩展：当前 "
                             f"{plan['stage']} → 期望 {nxt}")
    imported = 0
    for it in items:
        photo_id, sha = str(it["photo_id"]), str(it["sha256"])
        mode = it.get("review_mode", "double_review")
        if store.find_review_task(photo_id=photo_id, sha256=sha,
                                  review_mode=mode) is not None:
            continue
        task_id = f"rt_{protocol[:5]}_{photo_id}_{sha[:16]}"
        ok = store.add_review_task(
            task_id=task_id, claim_token=secrets.token_urlsafe(12),
            photo_id=photo_id, sha256=sha, review_mode=mode,
            requires_second_review=bool(
                it.get("requires_second_review", True)),
            queue_version="rq_v1", protocol=protocol)
        imported += 1 if ok else 0
    return {"protocol": protocol, "imported": imported,
            "total": len(store.list_review_tasks())}
