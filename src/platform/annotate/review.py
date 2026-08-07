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
# 区域级真值的非 SKU 结论（unknown=无法识别；new_packaging=新包装未入 Registry）
REGION_ABSTAIN_LABELS = ("unknown", "new_packaging")


_DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "sku_registry.json"
)


def load_registry_for_review(path: Path | str | None = None) -> dict[str, dict]:
    """SKU Registry（区域 gold 校验用）；缺失时空 dict 不阻断。

    架构红线：src/platform 不得 import 领域包，因此直接读取
    Registry JSON 数据文件（与 modules.labeling 同一份数据源）。"""
    p = Path(path) if path else _DEFAULT_REGISTRY_PATH
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


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
                  role: str = "annotator",
                  regions: list[dict[str, Any]] | None = None,
                  registry: dict[str, dict] | None = None) -> dict[str, Any]:
    """提交人工审核结论（唯一可产生 final_box / 区域 human_final 的途径）。

    regions 可选：区域级真值（region_id/box/sku 标签或 unknown/new_packaging/
    package_version_id/evidence/门店-session-近重复分组）。只有经人工提交
    的区域才可能进入 human_final/gold_verified，prediction 永不进入。"""
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
    n_regions = 0
    if regions:
        reg = registry if registry is not None else load_registry_for_review()
        for r in regions:
            _validate_and_store_region(
                store, row, r, actor=actor, role=role, registry=reg)
            n_regions += 1
    store.add_review_event(task_id=task_id, kind="review", actor=actor,
                           role=role, verdict=verdict, box=box)
    out = _finalize_result(store, row)
    if n_regions:
        out["regions_submitted"] = n_regions
    return out


def _validate_and_store_region(store, row: dict[str, Any], r: dict[str, Any],
                               *, actor: str, role: str,
                               registry: dict[str, dict]) -> None:
    """区域级真值校验 + 追加落账（fail-closed，不允许猜测 SKU）。"""
    region_id = str(r.get("region_id") or "").strip()
    if not region_id:
        raise ValueError("region 缺少 region_id")
    box = r.get("box")
    if not box or len(box) != 4 or any(float(v) <= 0 for v in _safe_floats(box)):
        raise ValueError(f"region {region_id} box 非法（需 4 个正数）")
    label = str(r.get("sku_label") or "").strip()
    if not label:
        raise ValueError(f"region {region_id} 缺少 sku_label")
    if label in REGION_ABSTAIN_LABELS:
        sku_id, sku_name = "", label  # 人工显式弃权/新包装，不伪造 SKU
    else:
        entry = registry.get(label)
        if entry is None:
            raise ValueError(
                f"region {region_id} sku_label 不在 Registry：{label}"
                "（越界不得伪造，需改标 unknown/new_packaging 或先扩 Registry）")
        sku_id, sku_name = str(entry.get("sku_id") or ""), label
        if not sku_id:
            raise ValueError(f"Registry 条目缺 sku_id: {label}")
    ok = store.add_gold_region(
        task_id=row["task_id"], region_id=region_id,
        photo_id=row["photo_id"], sha256=row["sha256"],
        box=box, sku_id=sku_id, sku_name=sku_name,
        package_version_id=str(r.get("package_version_id") or ""),
        review_status="submitted", actor=actor, role=role,
        evidence=r.get("evidence") or {},
        group_store=str(r.get("group_store") or ""),
        group_session=str(r.get("group_session") or ""),
        near_dup_group=str(r.get("near_dup_group") or ""))
    if not ok:
        raise ValueError(
            f"{actor} 已对 region {region_id} 提交过，不得重复提交")


def _safe_floats(box) -> list[float]:
    try:
        return [float(v) for v in box]
    except (TypeError, ValueError):
        return []


def _region_key(r: dict[str, Any]) -> tuple:
    """双人一致性键：region_id + SKU 结论（框以同 region 提交为准）。"""
    return (r["region_id"], r["sku_id"], r["sku_name"])


def gold_region_report(store) -> dict[str, Any]:
    """区域级 gold 汇总：只有双审一致/仲裁终结的区域才是 human_final/
    gold_verified；submitted 与 conflict 一律不得进入训练集。"""
    tasks = {t["task_id"]: t for t in store.list_review_tasks()}
    by_task: dict[str, list[dict]] = {}
    for r in store.list_gold_regions():
        by_task.setdefault(r["task_id"], []).append(r)
    counts = {"submitted": 0, "human_final": 0, "gold_verified": 0,
              "conflict": 0}
    photos_final: set[str] = set()
    out_regions: list[dict[str, Any]] = []
    for tid, recs in by_task.items():
        t = tasks.get(tid)
        if t is None:
            continue
        requires_second = bool(t["requires_second_review"])
        annot = [r for r in recs if r["role"] != "arbiter"]
        arbs = [r for r in recs if r["role"] == "arbiter"]
        by_key: dict[tuple, list[dict]] = {}
        for r in annot:
            by_key.setdefault(_region_key(r), []).append(r)
        actors = {r["actor"] for r in annot}
        for key, group in by_key.items():
            r0 = group[0]
            if arbs:
                # 仲裁轨道：人工分歧已由仲裁终结，原提交记录仅留痕不计数
                out_regions.append({**r0, "final_status": "superseded",
                                    "n_agree": len(group)})
                continue
            if not requires_second:
                status = "human_final"
            elif len({g["actor"] for g in group}) >= 2:
                status = "human_final"  # 双人独立一致
            elif len(actors) >= 2:
                status = "conflict"  # 双人已审但结论不一致 → 待仲裁
            else:
                status = "submitted"  # 仅一人提交，等二审
            counts[status] += 1
            if status == "human_final":
                photos_final.add(t["photo_id"])
            out_regions.append({**r0, "final_status": status,
                                "n_agree": len(group)})
        for a in arbs:
            counts["gold_verified"] += 1
            photos_final.add(t["photo_id"])
            out_regions.append({**a, "final_status": "gold_verified",
                                "n_agree": 1})
    return {"counts": counts,
            "usable_for_training": counts["human_final"]
            + counts["gold_verified"],
            "photos_with_gold": len(photos_final),
            "regions": out_regions}


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


def review_progress(store) -> dict[str, Any]:
    """统一审核状态源（任务书§八）：完全由 review_task_v1 +
    review_event_v1 + 队列账本推导；静态队列 JSON 只是不可变导入
    制品，不作为运行状态。active/invalid 分开统计，失效队列不进
    默认进度、不阻断后续批次。"""
    tasks = store.list_review_tasks()
    active = store.list_review_tasks_active()
    active_ids = {t["task_id"] for t in active}
    invalid_tasks = [t for t in tasks if t["task_id"] not in active_ids]
    by_status: dict[str, int] = {}
    derived: list[dict[str, Any]] = []
    for row in active:
        st = _derive_status(store, row)
        by_status[st["status"]] = by_status.get(st["status"], 0) + 1
        derived.append({**st,
                        "queue_version": row.get("queue_version", ""),
                        "protocol": row.get("protocol", "")})
    return {
        "source": "db_events",
        "active": {
            "total": len(active),
            "by_status": by_status,
            "queue_versions": sorted({str(r.get("queue_version") or "")
                                      for r in active}),
            "tasks": derived,
        },
        "invalid": {
            "total": len(invalid_tasks),
            "queue_versions": sorted({str(r.get("queue_version") or "")
                                      for r in invalid_tasks}),
        },
    }


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
