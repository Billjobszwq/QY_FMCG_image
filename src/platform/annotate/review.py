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
# 双审区域一致判定：两框 one-to-one 几何匹配的 IoU 阈值（任务书§十一.3）
DOUBLE_REVIEW_IOU_THRESHOLD = 0.75


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
                  registry: dict[str, dict] | None = None,
                  width: float | None = None,
                  height: float | None = None) -> dict[str, Any]:
    """提交人工审核结论（唯一可产生 final_box / 区域 human_final 的途径）。

    regions 可选：区域级真值（region_id/box/sku 标签或 unknown/new_packaging/
    package_version_id/evidence/门店-session-近重复分组）。只有经人工提交
    的区域才可能进入 human_final/gold_verified，prediction 永不进入。

    原子性（任务书§十一.1）：先全量校验所有区域并收集，再单事务落账；
    任一区域非法或重复 → 整次提交零落账，review 事件也不记录。
    width/height 可选：提供时额外校验 region box 不越出图片边界。"""
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
        # 1) 先全量校验+收集（不写库）：任一失败 → 抛错零落账
        prepared = [_prepare_region(row, r, actor=actor, role=role,
                                    registry=reg, width=width, height=height)
                    for r in regions]
        # 2) 单事务原子落账：整批成功或整批回滚
        if not store.add_gold_regions_atomic(prepared):
            raise ValueError(
                f"{actor} 区域提交落账失败（疑似对同一 region 重复提交），"
                "整次提交零落账")
        n_regions = len(prepared)
    store.add_review_event(task_id=task_id, kind="review", actor=actor,
                           role=role, verdict=verdict, box=box)
    out = _finalize_result(store, row)
    if n_regions:
        out["regions_submitted"] = n_regions
    return out


def _prepare_region(row: dict[str, Any], r: dict[str, Any], *, actor: str,
                    role: str, registry: dict[str, dict],
                    width: float | None = None,
                    height: float | None = None) -> dict[str, Any]:
    """区域级真值校验（fail-closed，不允许猜测 SKU）；只校验不落账，
    返回可写入 gold_region_v1 的载荷，原子性由 add_gold_regions_atomic 保证。"""
    region_id = str(r.get("region_id") or "").strip()
    if not region_id:
        raise ValueError("region 缺少 region_id")
    box = _validate_box(r.get("box"), context=f"region {region_id} box",
                        width=width, height=height)
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
    return {"task_id": row["task_id"], "region_id": region_id,
            "photo_id": row["photo_id"], "sha256": row["sha256"],
            "box": box, "sku_id": sku_id, "sku_name": sku_name,
            "package_version_id": str(r.get("package_version_id") or ""),
            "review_status": "submitted", "actor": actor, "role": role,
            "evidence": r.get("evidence") or {},
            "group_store": str(r.get("group_store") or ""),
            "group_session": str(r.get("group_session") or ""),
            "near_dup_group": str(r.get("near_dup_group") or "")}


def _validate_box(box, *, context: str = "box",
                  width: float | None = None,
                  height: float | None = None) -> list[float]:
    """bbox 合法性（任务书§十一.2）：x1/y1=0 是合法坐标（图片左上角）。
    拒绝：长度≠4、非数字、负坐标、x2<=x1、y2<=y1；
    提供 width/height 时额外拒绝越出图片边界的坐标。"""
    if box is None or len(box) != 4:
        raise ValueError(f"{context} 必须是 4 元组 (x1,y1,x2,y2)")
    vals = _safe_floats(box)
    if len(vals) != 4:
        raise ValueError(f"{context} 含非数字坐标: {list(box)!r}")
    x1, y1, x2, y2 = vals
    if min(vals) < 0:
        raise ValueError(f"{context} 不得含负坐标: {vals}")
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"{context} 必须满足 x2>x1 且 y2>y1: {vals}")
    if width is not None and (x1 > width or x2 > width):
        raise ValueError(f"{context} 越出图片宽度 {width}: {vals}")
    if height is not None and (y1 > height or y2 > height):
        raise ValueError(f"{context} 越出图片高度 {height}: {vals}")
    return vals


def _safe_floats(box) -> list[float]:
    try:
        return [float(v) for v in box]
    except (TypeError, ValueError):
        return []


def _iou(b1, b2) -> float:
    """两个 (x1,y1,x2,y2) 框的交并比 IoU。"""
    ax1, ay1, ax2, ay2 = (float(v) for v in b1)
    bx1, by1, bx2, by2 = (float(v) for v in b2)
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / union if union > 0 else 0.0


def _sku_conclusion(r: dict[str, Any]) -> str:
    """SKU 结论的可比形式：有 sku_id 比 sku_id；弃权标签
    （unknown/new_packaging）sku_id 为空，按 sku_name 比。"""
    return r["sku_id"] if r["sku_id"] else r["sku_name"]


def _match_regions_one_to_one(list_a: list[dict], list_b: list[dict],
                              threshold: float):
    """贪心 one-to-one 几何匹配：IoU>=threshold 的区域对按 IoU 降序
    选取（同分按索引序，确定性）；返回 (匹配对, 已用a索引, 已用b索引)。"""
    cand = []
    for i, ra in enumerate(list_a):
        for j, rb in enumerate(list_b):
            v = _iou(ra["box"], rb["box"])
            if v >= threshold:
                cand.append((-v, i, j))
    cand.sort()
    used_a: set[int] = set()
    used_b: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for _, i, j in cand:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        pairs.append((i, j))
    return pairs, used_a, used_b


def gold_region_report(store) -> dict[str, Any]:
    """区域级 gold 汇总：只有双审一致/仲裁终结的区域才是 human_final/
    gold_verified；submitted 与 conflict 一律不得进入训练集。

    任务书§十一.3/4：双审一致按区域 one-to-one 几何匹配
    （IoU>=DOUBLE_REVIEW_IOU_THRESHOLD）后再比 SKU 结论，未匹配视为分歧；
    仲裁只作用于发生分歧的区域组，未分歧区域不受仲裁影响；
    gold 按 task_id 分组，不做跨任务合并（同图 assisted/blind 互不污染）。"""
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
        actors = sorted({r["actor"] for r in annot})
        # 分歧组（输出条目引用，供仲裁逐组 supersede）
        conflict_entries: list[list[dict[str, Any]]] = []
        if not requires_second:
            for r in annot:
                counts["human_final"] += 1  # 单审一次提交即终态
                photos_final.add(t["photo_id"])
                out_regions.append({**r, "final_status": "human_final",
                                    "n_agree": 1})
        elif len(actors) < 2:
            for r in annot:
                counts["submitted"] += 1  # 仅一人提交，等二审
                out_regions.append({**r, "final_status": "submitted",
                                    "n_agree": 1})
        else:
            ra = [r for r in annot if r["actor"] == actors[0]]
            rb = [r for r in annot if r["actor"] == actors[1]]
            pairs, used_a, used_b = _match_regions_one_to_one(
                ra, rb, DOUBLE_REVIEW_IOU_THRESHOLD)
            for i, j in pairs:
                if _sku_conclusion(ra[i]) == _sku_conclusion(rb[j]):
                    counts["human_final"] += 1  # 双人独立一致
                    photos_final.add(t["photo_id"])
                    out_regions.append({**ra[i],
                                        "final_status": "human_final",
                                        "n_agree": 2})
                else:
                    conflict_entries.append(
                        [{**ra[i], "final_status": "conflict", "n_agree": 1},
                         {**rb[j], "final_status": "conflict",
                          "n_agree": 1}])
                    counts["conflict"] += 2  # 几何匹配但 SKU 结论不一致
            for i, r in enumerate(ra):
                if i not in used_a:
                    conflict_entries.append(
                        [{**r, "final_status": "conflict", "n_agree": 1}])
                    counts["conflict"] += 1  # 未匹配 → 几何分歧
            for j, r in enumerate(rb):
                if j not in used_b:
                    conflict_entries.append(
                        [{**r, "final_status": "conflict", "n_agree": 1}])
                    counts["conflict"] += 1
            for entries in conflict_entries:
                out_regions.extend(entries)
        # 仲裁轨道：逐区域 gold_verified；仅把与仲裁框几何匹配
        # （IoU>=阈值）的分歧组 superseded，未分歧区域保持原状态
        for a in arbs:
            best_idx, best_iou = -1, 0.0
            for gi, entries in enumerate(conflict_entries):
                m = max((_iou(a["box"], e["box"]) for e in entries),
                        default=0.0)
                if m >= DOUBLE_REVIEW_IOU_THRESHOLD and m > best_iou:
                    best_idx, best_iou = gi, m
            if best_idx >= 0:
                for e in conflict_entries[best_idx]:
                    if e["final_status"] == "conflict":
                        e["final_status"] = "superseded"  # 原提交仅留痕
                        counts["conflict"] -= 1
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
