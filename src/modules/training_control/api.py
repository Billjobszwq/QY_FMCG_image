"""GLTC Task 8：统一训练控制 API（01 §10）。

只读投影公开；写端点（数据集构建等）需本机登录 session+CSRF。
production legacy 与 nextgen 四 lane 分离展示，禁止视觉混淆。
旧 /api/v1/training/*（training_gov）保持只读兼容，不新增第二套写状态。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.modules.dataset_factory import service as factory
from src.modules.training_control import legacy as legacy_mod
from src.modules.training_control import vocabulary as V
from src.modules.training_control.contracts import Blocker

from src.platform.auth import AuthService, require_principal

REPO_ROOT = Path(__file__).resolve().parents[3]

USABLE_GOLD_STATUSES = ("human_final", "gold_verified")


def _usable_gold(store: Any) -> list[dict[str, Any]]:
    return [r for r in store.list_gold_regions()
            if r.get("review_status") in USABLE_GOLD_STATUSES]


def lane_readiness(store: Any, lane: str) -> dict[str, Any]:
    """单 lane 就绪度：如实报告 blocker（fail-closed，不粉饰）。"""
    if lane not in V.TRAINING_LANES:
        raise KeyError(lane)
    blockers: list[Blocker] = []
    gold = _usable_gold(store)
    if not gold:
        blockers.append(Blocker(
            "BLOCKED_BY_GOLD",
            "无 human_final/gold_verified 区域真值（gold=0）"))
    if store.get_flag("training_authorized") != "true":
        blockers.append(Blocker(
            "BLOCKED_BY_AUTHORIZATION",
            "training_authorized=false：需用户显式授权具体计划"))
    if lane == "segmenter":
        blockers.append(Blocker(
            "BLOCKED_BY_MASK_GOLD",
            "无真实 mask gold：仅允许 prompt/阈值/裁剪校准"))
        blockers.append(Blocker(
            "CALIBRATION_ONLY", "T3 当前仅校准模式"))
    if lane == "vlm" and not (REPO_ROOT / ".venv_mlx_vlm").is_dir():
        blockers.append(Blocker(
            "BLOCKED_BY_ENVIRONMENT", "隔离环境 .venv_mlx_vlm 缺失"))
    hard = [b for b in blockers if b.code != "CALIBRATION_ONLY"]
    return {
        "lane": lane,
        "lineage_family": legacy_mod.C.LINEAGE_FAMILY,
        "ready": not hard,
        "blockers": [{"code": b.code, "detail": b.detail} for b in blockers],
        "gold_regions": len(gold),
    }


def create_training_control_router(store: Any,
                                 auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["training_control"])

    @router.get("/api/v1/training/lanes")
    def lanes() -> dict:
        proj = legacy_mod.training_overview_projection(store)
        out = {}
        for lane in V.TRAINING_LANES:
            r = lane_readiness(store, lane)
            out[lane] = {**proj["nextgen_lanes"][lane], **r}
        return {"production": proj["production"], "lanes": out,
                "note": "当前生产与正在训练/待训练不是同一 lineage"}

    @router.get("/api/v1/training/lanes/{lane}/readiness")
    def readiness(lane: str) -> dict:
        try:
            return lane_readiness(store, lane)
        except KeyError:
            raise HTTPException(404, f"未注册 lane: {lane}")

    @router.get("/api/v1/training/overview")
    def overview() -> dict:
        gold = _usable_gold(store)
        return {
            "production": legacy_mod.training_overview_projection(store)[
                "production"],
            "lanes": {l: lane_readiness(store, l)["ready"]
                      for l in V.TRAINING_LANES},
            "gold": {"usable_regions": len(gold),
                     "statuses": USABLE_GOLD_STATUSES},
            "leases": store.list_active_leases(),
            "training_authorized":
                store.get_flag("training_authorized") == "true",
        }

    @router.get("/api/v1/training/legacy-models")
    def legacy_models() -> dict:
        rows = store.list_legacy_models()
        return {"count": len(rows), "models": rows,
                "note": "只读登记；旧模型不移动、不删除、不作 nextgen parent"}

    @router.get("/api/v1/training/runs-v2")
    def runs_v2() -> dict:
        runs = store.list_training_runs_v2()
        return {"count": len(runs), "runs": runs}

    @router.get("/api/v1/training/runs-v2/{run_id}/events")
    def run_events(run_id: str) -> dict:
        evs = store.list_training_events(run_id)
        return {"run_id": run_id, "count": len(evs), "events": evs}

    @router.post("/api/v1/training/datasets/{lane}/build")
    def dataset_build(lane: str, request: Request) -> dict:
        require_principal(auth, request, csrf=True)
        if lane not in V.TRAINING_LANES:
            raise HTTPException(404, f"未注册 lane: {lane}")
        # 机器侧框架：只从事实源构建。当前 gold=0 → 诚实报告 admitted=0，
        # 不接受客户端自由 JSON 冒充审核结论。
        rows: list[dict[str, Any]] = []
        report = factory.build_snapshot(
            lane, rows=rows,
            out_root=REPO_ROOT / ".datasets_nextgen_staging",
            dataset_id=f"dryrun_{lane}_v1")
        return {"lane": lane, "report": report,
                "note": "正式构建需 human gold；0 条准入不写文件"}

    return router
