"""历史 assisted 项目可见 SKU prediction 非破坏性回填。

红线（指令第七节）：
- 只处理 title 含 "[assisted]" 的项目；blind 项目永不回填；
- 不删除、不覆盖旧 prediction，不修改人工 annotation（纯追加）；
- 同一 task + model_version（<原版本>@visible-sku-v2）重复执行必须跳过；
- SKU 只在 Registry 映射成立时写入 taxonomy，否则仅保留方框并标记
  needs_manual_sku（与 src.modules.labeling.service 修复链路完全一致）；
- 每次执行产出审计报告与任务级错误账本。
"""
from __future__ import annotations

import time
from typing import Any

from ..modules.labeling.service import (
    load_default_registry,
    predictions_from_recognition,
)

BACKFILL_SUFFIX = "@visible-sku-v2"
DEFAULT_FALLBACK_BASE_VERSION = "legacy.recognition.v2@cascade_v3"


class BackfillGuardError(RuntimeError):
    """试图回填非 assisted（如 blind）项目时抛出。"""


def _iter_tasks(ls: Any, pid: int) -> list[dict]:
    """分页遍历项目全部 task（与 index_task_images 同策略）。"""
    out: list[dict] = []
    page = 1
    while True:
        d = ls.list_tasks(pid, page=page, page_size=100)
        tasks = d if isinstance(d, list) else d.get("tasks", d.get("results", []))
        out.extend(tasks)
        if isinstance(d, list) or "next" not in d or not d.get("next"):
            break
        page += 1
    return out


def _task_predictions(ls: Any, task_id: int) -> list[dict]:
    full = ls.get_task(task_id)
    return full.get("predictions", []) or []


def _is_assisted(project: dict) -> bool:
    title = project.get("title", "")
    return "[assisted]" in title and "[blind]" not in title


def scan_project(ls: Any, pid: int, registry: dict[str, dict]) -> dict:
    """dry-run 扫描单个项目：分类每个 task 的 prediction 现状。

    分类（互斥优先级）：
    - already_backfilled：已存在 @visible-sku-v2 prediction；
    - no_prediction：任务完全没有 prediction；
    - box_only：有 prediction 但无 taxonomy region（人工看不到建议 SKU）；
    - sku_out_of_registry：taxonomy 值不在 Registry（越界）；
    - ok：已有合法可见 SKU。"""
    project = ls.get_project(pid)
    if not _is_assisted(project):
        raise BackfillGuardError(
            f"项目 {pid}（{project.get('title')}）不是 assisted 项目，拒绝扫描回填")
    tasks = _iter_tasks(ls, pid)
    stats = {"tasks": len(tasks), "already_backfilled": 0,
             "no_prediction": 0, "box_only": 0,
             "sku_out_of_registry": 0, "ok": 0,
             "will_add_predictions": 0}
    detail: list[dict] = []
    for t in tasks:
        preds = _task_predictions(ls, t["id"])
        mvs = [p.get("model_version", "") for p in preds]
        has_tax = any(r.get("type") == "taxonomy"
                      for p in preds for r in p.get("result", []))
        oob: list[str] = []
        for p in preds:
            for r in p.get("result", []):
                if r.get("type") == "taxonomy":
                    for path in (r.get("value") or {}).get("taxonomy", []):
                        leaf = path[-1] if isinstance(path, list) and path else None
                        if leaf is not None and leaf not in registry:
                            oob.append(str(leaf))
        if any(mv.endswith(BACKFILL_SUFFIX) for mv in mvs):
            bucket = "already_backfilled"
        elif not preds:
            bucket = "no_prediction"
        elif oob:
            bucket = "sku_out_of_registry"
        elif not has_tax:
            bucket = "box_only"
        else:
            bucket = "ok"
        stats[bucket] += 1
        if bucket in ("no_prediction", "box_only", "sku_out_of_registry"):
            stats["will_add_predictions"] += 1
        detail.append({"task_id": t["id"], "bucket": bucket,
                       "model_versions": mvs, "out_of_registry": oob})
    return {"project_id": pid, "title": project.get("title"),
            "stats": stats, "detail": detail}


def backfill_project(
    ls: Any,
    recognition: Any,
    pid: int,
    *,
    registry: dict[str, dict] | None = None,
    apply: bool = False,
) -> dict:
    """对单个 assisted 项目执行回填（apply=False 时等价 dry-run）。

    对 no_prediction / box_only / sku_out_of_registry 的 task：
    下载原图 → 重跑识别 → 用修复后的 predictions_from_recognition 生成
    同 region id 的 rectanglelabels+taxonomy(+unreviewed) → 以
    <原model_version>@visible-sku-v2 追加新 prediction。
    旧 prediction / annotation 一律不动。"""
    report = scan_project(ls, pid, registry or load_default_registry())
    registry = registry or load_default_registry()
    report["apply"] = apply
    report["added"] = 0
    report["skipped_idempotent"] = 0
    report["errors"] = []  # 任务级错误账本
    if not apply:
        return report
    by_bucket = {d["task_id"]: d for d in report["detail"]}
    for d in report["detail"]:
        if d["bucket"] not in ("no_prediction", "box_only",
                               "sku_out_of_registry"):
            if d["bucket"] == "already_backfilled":
                report["skipped_idempotent"] += 1
            continue
        tid = d["task_id"]
        try:
            preds = _task_predictions(ls, tid)
            base_mv = (preds[0].get("model_version")
                       or DEFAULT_FALLBACK_BASE_VERSION) if preds \
                else DEFAULT_FALLBACK_BASE_VERSION
            # 原版本本身可能已是回填产物，防双后缀
            base_mv = base_mv.removesuffix(BACKFILL_SUFFIX)
            new_mv = f"{base_mv}{BACKFILL_SUFFIX}"
            full = ls.get_task(tid)
            img_path = (full.get("data") or {}).get("image")
            if not img_path:
                raise RuntimeError("task 无 data.image")
            img = ls.fetch_file(img_path)
            preds_new, failures = predictions_from_recognition(
                recognition, [(f"task_{tid}", img)],
                model_version=new_mv, registry=registry)
            if failures:
                raise RuntimeError("识别失败（recognize 异常）")
            written = 0
            for pred in preds_new.get(f"task_{tid}", []):
                ls.create_prediction(tid, pred["result"],
                                     score=float(pred.get("score", 0.5)),
                                     model_version=new_mv)
                written += 1
            report["added"] += written
            by_bucket[tid]["backfilled"] = written
        except Exception as e:  # noqa: BLE001 — 单任务失败记入账本不中断
            report["errors"].append({"task_id": tid,
                                     "error": f"{type(e).__name__}: {e}"})
    report["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    return report


def select_assisted_projects(ls: Any) -> list[dict]:
    """全部项目中筛出 assisted（blind 永不进入回填范围）。"""
    return [p for p in ls.list_projects() if _is_assisted(p)]
