"""U4-2：标注审核闭环状态机（链接派发/认领/单审/盲抽/双审/仲裁/导出）。

口径（手册 §七/U4 指令）：
- 任务表 review_task_v1 不可变（导入即冻结），一切状态迁移走
  追加式 review_event_v1（claim/review/blind_sample 事件）；
- SAM prediction 永远不是最终标注：final_box 只能来自人工终态；
- 单审（blind_review）一次提交即终态；双审（double_review）需两人，
  框完全一致即终态，分歧升级仲裁（role=arbiter）一锤定音；
- 同一 actor 不得对同一任务二次提交；已认领任务不得二次认领；
- 10% 盲抽按 seed 可复现；导出 JSON 不可变并附 SHA256。
"""
from __future__ import annotations

import hashlib
import json
import random
import secrets
from pathlib import Path
from typing import Any

REVIEW_MODES = ("double_review", "blind_review", "blind_manual")
VERDICTS = ("accepted", "rejected", "adjudicated")


def import_review_queue(store, path: Path | str,
                       seed: int | None = None) -> dict[str, Any]:
    """导入 rq_v1 队列文件；(photo_id, sha256, review_mode) 幂等，
    重复导入不新增（真实队列盲抽项可与双审项同照片）。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("items", [])
    imported = 0
    for it in items:
        photo_id, sha = str(it["photo_id"]), str(it["sha256"])
        mode = it.get("review_mode", "double_review")
        if mode not in REVIEW_MODES:
            raise ValueError(f"非法 review_mode: {mode}")
        if store.find_review_task(photo_id=photo_id, sha256=sha,
                                  review_mode=mode) is not None:
            continue
        task_id = f"rt_{mode[:5]}_{photo_id}_{sha[:16]}"
        ok = store.add_review_task(
            task_id=task_id, claim_token=secrets.token_urlsafe(12),
            photo_id=photo_id, sha256=sha, review_mode=mode,
            requires_second_review=bool(
                it.get("requires_second_review",
                       mode in ("double_review", "blind_manual"))),
            queue_version=data.get("queue_version", "rq_v1"),
            protocol=data.get("protocol", ""), import_seed=seed)
        imported += 1 if ok else 0
    return {"imported": imported,
            "total": len(store.list_review_tasks())}


def blind_sample(store, *, ratio: float = 0.1,
                 seed: int | None = None) -> dict[str, Any]:
    """10% 盲抽：按 seed 确定性抽样，同 seed 必须可复现。"""
    if not 0.0 < ratio <= 1.0:
        raise ValueError("ratio 必须在 (0, 1] 区间")
    ids = sorted(t["task_id"] for t in store.list_review_tasks())
    k = min(len(ids), int(len(ids) * ratio))
    rng = random.Random(seed)
    picked = rng.sample(ids, k) if k else []
    for tid in picked:
        store.add_review_event(task_id=tid, kind="blind_sampled",
                               actor="system", role="system")
    return {"selected": len(picked), "task_ids": picked,
            "ratio": ratio, "seed": seed}


def _reviews_of(store, task_id: str) -> list[dict[str, Any]]:
    return [e for e in store.list_review_events(task_id)
            if e["kind"] == "review"]


def _claim_of(store, task_id: str) -> dict[str, Any] | None:
    return next((e for e in store.list_review_events(task_id)
                 if e["kind"] == "claim"), None)


def claim_task(store, claim_token: str,
               actor: str) -> dict[str, Any]:
    """链接认领：凭 claim_token 认领；已认领不得二次认领。"""
    if not actor or not str(actor).strip():
        raise ValueError("actor 不得为空")
    row = store.find_review_task_by_token(claim_token)
    if row is None:
        raise ValueError(f"claim_token 不存在: {claim_token}")
    if _claim_of(store, row["task_id"]) is not None:
        return {"claimed": False, "task_id": row["task_id"],
                "reason": "already_claimed"}
    store.add_review_event(task_id=row["task_id"], kind="claim",
                           actor=str(actor))
    return {"claimed": True, "task_id": row["task_id"]}


def _derive_status(store, row: dict[str, Any]) -> dict[str, Any]:
    tid = row["task_id"]
    claim = _claim_of(store, tid)
    reviews = _reviews_of(store, tid)
    arb = next((r for r in reviews if r["role"] == "arbiter"), None)
    if arb is not None:
        status, final = "finalized", arb["box"]
    elif not row["requires_second_review"] and len(reviews) >= 1:
        status, final = "finalized", reviews[0]["box"]
    elif row["requires_second_review"] and len(reviews) >= 2:
        b1, b2 = reviews[0]["box"], reviews[1]["box"]
        if b1 == b2:
            status, final = "finalized", b1
        else:
            status, final = "awaiting_arbitration", None
    elif len(reviews) == 1:
        status, final = "awaiting_second", None
    elif claim is not None:
        status, final = "claimed", None
    else:
        status, final = "pending", None
    return {"task_id": tid, "photo_id": row["photo_id"],
            "sha256": row["sha256"], "review_mode": row["review_mode"],
            "status": status,
            "claimed_by": claim["actor"] if claim else None,
            "n_reviews": len(reviews), "final_box": final}


def task_view(store, claim_token: str) -> dict[str, Any]:
    """认领链接视图（审核员从链接进入后看到的任务状态）。"""
    row = store.find_review_task_by_token(claim_token)
    if row is None:
        raise ValueError(f"claim_token 不存在: {claim_token}")
    return _derive_status(store, row)


def submit_review(store, *, task_id: str, actor: str, verdict: str,
                  box: tuple | list,
                  role: str = "annotator") -> dict[str, Any]:
    """提交人工审核结论（唯一可产生 final_box 的途径）。"""
    row = store.find_review_task_by_id(task_id)
    if row is None:
        raise ValueError(f"task_id 不存在: {task_id}")
    if not actor or not str(actor).strip():
        raise ValueError("actor 不得为空")
    if verdict not in VERDICTS:
        raise ValueError(f"非法 verdict: {verdict}")
    box = [float(v) for v in box]
    if len(box) != 4:
        raise ValueError("box 必须是 4 元组 (x1,y1,x2,y2)")
    prior = _reviews_of(store, task_id)
    if any(e["actor"] == actor for e in prior):
        raise ValueError(f"{actor} 已对该任务提交过审核，不得二次提交")
    if role == "arbiter" and len(prior) < 2:
        raise ValueError("仲裁前必须已有两次独立审核")
    store.add_review_event(task_id=task_id, kind="review", actor=actor,
                           role=role, verdict=verdict, box=box)
    return _finalize_result(store, row)


def _finalize_result(store, row: dict[str, Any]) -> dict[str, Any]:
    st = _derive_status(store, row)
    out: dict[str, Any] = {"task_id": row["task_id"],
                           "finalized": st["status"] == "finalized",
                           "status": st["status"]}
    if st["status"] == "awaiting_second":
        out["needs_second"] = True
    if st["status"] == "awaiting_arbitration":
        out["needs_arbitration"] = True
    if st["status"] == "finalized":
        out["final_box"] = st["final_box"]
    return out


def final_box(store, task_id: str) -> list[float] | None:
    """仅终态任务返回 final_box；否则恒为 None（禁止自动框冒充）。"""
    row = store.find_review_task_by_id(task_id)
    if row is None:
        raise ValueError(f"task_id 不存在: {task_id}")
    return _derive_status(store, row)["final_box"]


def export_review(store, path: Path | str) -> dict[str, Any]:
    """不可变导出：全部任务 + 终态 final_box + 事件账，附 SHA256。"""
    tasks = store.list_review_tasks()
    items, n_fin = [], 0
    for t in tasks:
        st = _derive_status(store, t)
        if st["status"] == "finalized":
            n_fin += 1
        items.append({
            "task_id": t["task_id"], "photo_id": t["photo_id"],
            "sha256": t["sha256"], "review_mode": t["review_mode"],
            "requires_second_review": bool(t["requires_second_review"]),
            "status": st["status"], "claimed_by": st["claimed_by"],
            "final_box": st["final_box"],
            "events": store.list_review_events(t["task_id"]),
        })
    payload = {
        "export_version": "review_export_v1",
        "n_tasks": len(items), "n_finalized": n_fin,
        "tasks": items,
    }
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return {"path": str(p),
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "n_tasks": len(items), "n_finalized": n_fin}
