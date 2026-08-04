"""diagnostic_v1 人工双审队列（手册§七 / 用户要求#12/#13/#26）。

规则：
- diagnostic 前 n_double（默认200）张全部进入 double_review；
- 固定 seed 从全池盲抽 ≥ n_blind（默认50）张 blind_manual：第一标注者
  看不到 SAM 结果，独立画框，用于估计 SAM anchoring bias 与真实提效；
- 全部队列项初始 status=pending，本模块从不生成框、从不伪造结果；
- 队列文件不可覆盖（证据链不可变）。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

PROTOCOL = "diagnostic_v1"
QUEUE_VERSION = "rq_v1"


def build_review_queue(photos: list[dict], *, seed: int,
                       n_double: int = 200, n_blind: int = 50) -> dict:
    """构建审核队列。photos 按 diagnostic_v1.json 顺序（前200张双审）。"""
    if len(photos) < n_blind:
        raise ValueError(
            f"照片池 {len(photos)} 张不足盲抽最低 {n_blind} 张，"
            f"fail-closed：不允许静默缩减盲审规模（手册§七）")
    n_double_eff = min(n_double, len(photos))

    items = []
    for p in photos[:n_double_eff]:
        items.append({
            "photo_id": str(p["photo_id"]),
            "sha256": p["sha256"],
            "review_mode": "double_review",
            "requires_second_review": True,
            "status": "pending",
            "annotator_1": None, "annotator_2": None, "arbiter": None,
            "final_box": None,
        })

    rng = random.Random(seed)
    pool = sorted(str(p["photo_id"]) for p in photos)
    blind_ids = rng.sample(pool, n_blind)
    by_id = {str(p["photo_id"]): p for p in photos}
    for pid in sorted(blind_ids):
        p = by_id[pid]
        items.append({
            "photo_id": pid,
            "sha256": p["sha256"],
            "review_mode": "blind_manual",
            "requires_second_review": True,
            "status": "pending",
            "annotator_1": None, "annotator_2": None, "arbiter": None,
            "final_box": None,
        })

    return {
        "queue_version": QUEUE_VERSION,
        "protocol": PROTOCOL,
        "seed": seed,
        "n_double": n_double_eff,
        "n_blind": n_blind,
        "status": "awaiting_human_review",
        "items": items,
    }


def queue_status(queue: dict) -> dict:
    items = queue["items"]
    done = sum(1 for i in items if i["status"] == "done")
    pending = [i for i in items if i["status"] != "done"]
    n_double_pend = sum(1 for i in pending
                        if i["review_mode"] == "double_review")
    n_blind_pend = sum(1 for i in pending
                       if i["review_mode"] == "blind_manual")
    blockers = []
    if n_double_pend:
        blockers.append(f"双审未开始/未完成：{n_double_pend} 张待双审")
    if n_blind_pend:
        blockers.append(f"盲抽对照未完成：{n_blind_pend} 张待盲标")
    return {
        "status": ("ready_for_truebox_export" if not pending
                   else "awaiting_human_review"),
        "total": len(items),
        "done": done,
        "pending": len(pending),
        "pending_double_review": n_double_pend,
        "pending_blind_manual": n_blind_pend,
        "blockers": blockers,
    }


def write_queue(queue: dict, path: Path) -> None:
    """原子写队列；已存在则拒绝覆盖（不可变证据链）。"""
    path = Path(path)
    if path.exists() and path.stat().st_size > 0:
        raise FileExistsError(
            f"审核队列已存在，禁止覆盖: {path}（如需新版请换文件名）")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(queue, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)
