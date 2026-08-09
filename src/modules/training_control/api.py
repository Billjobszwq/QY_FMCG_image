"""GLTC Task 8：统一训练控制 API（01 §10）。

只读投影公开；写端点（数据集构建等）需本机登录 session+CSRF。
production legacy 与 nextgen 四 lane 分离展示，禁止视觉混淆。
旧 /api/v1/training/*（training_gov）保持只读兼容，不新增第二套写状态。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

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

    _mount_cycle_endpoints(router, store, auth)
    _mount_profile_endpoints(router, store)
    _mount_control_endpoints(router, store, auth)
    return router


# ---------- N2 Task 2：持久化 Cycle 控制面（写端点 session+CSRF） ----------

class CycleCreateBody(BaseModel):
    name: str


class CycleAdvanceBody(BaseModel):
    target: str
    expected_version: int
    idempotency_key: str
    waiting_for: str = ""





# ---------- N2 Task 2：真实控制 API（data-scope/quality/sam/snapshots/plans/runs） ----------

class PlanCreateBody(BaseModel):
    lane: str
    hypothesis: str = ""
    base_revision: str
    dataset_hash: str
    eval_set_hash: str = ""
    budget: dict = {}
    stop_lines: list[str] = []


class ApproveBody(BaseModel):
    approval_key: str


class LaunchBody(BaseModel):
    run_name: str
    args: list[str] = []
    dataset_dir: str


def _mount_control_endpoints(router: APIRouter, store: Any,
                             auth: AuthService | None) -> None:
    from pathlib import Path as _P
    from .cycle import CycleError, TrainingCycleService
    from .launchers import (ClassifierLauncher, DetectorLauncher,
                            LauncherError, SegmenterLauncher, VlmLauncher)

    def _svc() -> TrainingCycleService:
        return TrainingCycleService(store)

    def _launcher(lane: str):
        return {"detector": DetectorLauncher,
                "classifier": ClassifierLauncher,
                "segmenter": SegmenterLauncher,
                "vlm": VlmLauncher}[lane](store)

    @router.get("/api/v1/training/data-scope")
    def data_scope_get() -> dict:
        rep_dir = _P("reports/nextgen_v2")
        out: dict = {"reconciliations": []}
        for f in sorted(rep_dir.glob("data_scope_reconciliation*.json")):
            out["reconciliations"].append(json.loads(f.read_text()))
        return out

    @router.post("/api/v1/training/data-scope/freeze")
    def data_scope_freeze(request: Request) -> dict:
        require_principal(auth, request, csrf=True)
        svc = _svc()
        cycles = store._conn.execute(
            "SELECT cycle_id FROM training_cycle_v1 ORDER BY created_at"
        ).fetchall()
        if not cycles:
            raise HTTPException(404, "无 cycle；请先创建")
        cid = cycles[0]["cycle_id"]
        cur = svc.get_cycle(cid)
        try:
            svc.advance(cid, "ASSET_SCOPE_FROZEN", actor="session",
                        expected_version=cur["version"])
        except CycleError as e:
            raise HTTPException(409, str(e))
        return {"cycle_id": cid, "status": "ASSET_SCOPE_FROZEN"}

    @router.post("/api/v1/training/quality/run")
    def quality_run(request: Request) -> dict:
        require_principal(auth, request, csrf=True)
        stats_f = _P("reports/nextgen_v2/quality_scan_stats.json")
        if not stats_f.exists():
            raise HTTPException(
                409, "质量扫描未运行（scripts/run_nextgen_quality_scan.py）")
        return json.loads(stats_f.read_text(encoding="utf-8"))

    @router.post("/api/v1/training/sam/run")
    def sam_run(request: Request) -> dict:
        require_principal(auth, request, csrf=True)
        stats_f = _P("reports/nextgen_v2/sam_point_stats.json")
        if not stats_f.exists():
            raise HTTPException(
                409, "SAM 生成未运行（scripts/run_nextgen_sam_points.py）")
        return json.loads(stats_f.read_text(encoding="utf-8"))

    @router.post("/api/v1/training/snapshots/{lane}/build")
    def snapshot_build(lane: str, request: Request) -> dict:
        require_principal(auth, request, csrf=True)
        datasets = _P(".datasets_nextgen")
        found = [d.name for d in datasets.glob(f"{lane[:2]}_*")
                 if d.is_dir()] if datasets.exists() else []
        return {"lane": lane, "built_snapshots": found,
                "note": "物化经 scripts/build_d*_*.py（幂等、目录存在拒绝）"}

    @router.post("/api/v1/training/plans")
    def plans_create(body: PlanCreateBody, request: Request) -> dict:
        require_principal(auth, request, csrf=True)
        svc = _svc()
        cycles = store._conn.execute(
            "SELECT cycle_id FROM training_cycle_v1 ORDER BY created_at"
        ).fetchall()
        cid = cycles[0]["cycle_id"] if cycles else svc.create_cycle(
            name="nextgen_v2", actor="session")
        pid = svc.register_plan(
            cid, lane=body.lane, hypothesis=body.hypothesis,
            base_revision=body.base_revision, dataset_hash=body.dataset_hash,
            budget=body.budget, stop_lines=body.stop_lines,
            eval_set_hash=body.eval_set_hash, actor="session")
        return {"plan_id": pid, "cycle_id": cid, "status": "DRAFT"}

    @router.post("/api/v1/training/plans/{plan_id}/approve")
    def plans_approve(plan_id: str, body: ApproveBody,
                      request: Request) -> dict:
        require_principal(auth, request, csrf=True)
        _svc().approve_plan(plan_id, actor="session",
                            approval_key=body.approval_key)
        return {"plan_id": plan_id, "status": "APPROVED"}

    @router.post("/api/v1/training/runs/{run_id}/safe-stop")
    def runs_safe_stop(run_id: str, request: Request) -> dict:
        require_principal(auth, request, csrf=True)
        att = _svc().get_run_attempt(run_id)
        _svc().update_run_attempt(run_id, status="STOPPING")
        return {"run_id": run_id, "status": "STOPPING",
                "note": "需进程退出证据后 confirm_stopped；禁伪 cancelled"}

    @router.get("/api/v1/training/runs/{run_id}/artifacts")
    def run_artifacts(run_id: str) -> dict:
        rows = store._conn.execute(
            "SELECT * FROM training_artifact_v2 WHERE run_id=?",
            (run_id,)).fetchall()
        return {"run_id": run_id, "count": len(rows),
                "artifacts": [dict(r) for r in rows]}

    @router.post("/api/v1/training/resource-benchmarks")
    def resource_benchmarks(request: Request) -> dict:
        require_principal(auth, request, csrf=True)
        rows = store._conn.execute(
            "SELECT * FROM resource_benchmark_v1 ORDER BY id").fetchall()
        return {"count": len(rows),
                "benchmarks": [dict(r) for r in rows],
                "decision": "heavy_concurrency=1（未做组合并发实测，"
                            "保持 1；Qwen MLX 永远独占）"}


# ---------- N2 Task 11：Recognition Profiles ----------

def _mount_profile_endpoints(router: APIRouter, store: Any) -> None:
    from .profiles import ProfileRegistry

    @router.get("/api/v1/recognition/profiles")
    def profiles_list() -> dict:
        # 纠偏 Task 7：状态从 Artifact Registry 动态派生，不存过期文本
        from .profiles import derive_profiles
        ps = derive_profiles(store)
        return {"count": len(ps), "profiles": ps,
                "note": "识别只允许选择注册 profile_id，禁任意权重路径；"
                        "status 由 artifact registry 动态派生"}

def _mount_cycle_endpoints(router: APIRouter, store: Any,
                           auth: AuthService | None) -> None:
    from .cycle import CycleError, TrainingCycleService

    def _svc() -> TrainingCycleService:
        return TrainingCycleService(store)

    @router.get("/api/v1/training/cycles")
    def cycles_list() -> dict:
        rows = store._conn.execute(
            "SELECT * FROM training_cycle_v1 ORDER BY created_at"
        ).fetchall()
        return {"count": len(rows), "cycles": [dict(r) for r in rows]}

    @router.post("/api/v1/training/cycles")
    def cycles_create(body: CycleCreateBody, request: Request) -> dict:
        require_principal(auth, request, csrf=True)
        cid = _svc().create_cycle(name=body.name, actor="session")
        return {"cycle_id": cid, "status": "DRAFT"}

    @router.get("/api/v1/training/cycles/{cycle_id}")
    def cycle_get(cycle_id: str) -> dict:
        try:
            return _svc().get_cycle(cycle_id)
        except CycleError as e:
            raise HTTPException(404, str(e))

    @router.get("/api/v1/training/cycles/{cycle_id}/events")
    def cycle_events(cycle_id: str) -> dict:
        evs = _svc().events(cycle_id)
        return {"cycle_id": cycle_id, "count": len(evs), "events": evs}

    @router.post("/api/v1/training/cycles/{cycle_id}/advance")
    def cycle_advance(cycle_id: str, body: CycleAdvanceBody,
                      request: Request) -> dict:
        require_principal(auth, request, csrf=True)
        svc = _svc()
        # 幂等键：相同键的推进请求只执行一次（重复按钮/重放安全）
        seen = store._conn.execute(
            "SELECT 1 FROM training_cycle_node_v1 WHERE idempotency_key=?",
            (body.idempotency_key,)).fetchone()
        if seen is not None:
            return {"duplicate": True}
        try:
            svc.advance(cycle_id, body.target, actor="session",
                        expected_version=body.expected_version,
                        waiting_for=body.waiting_for)
            svc.record_node(cycle_id, node=f"advance:{body.target}",
                            status="completed",
                            idempotency_key=body.idempotency_key,
                            evidence={"target": body.target})
        except CycleError as e:
            msg = str(e)
            if "非法跃迁" in msg or "版本冲突" in msg:
                raise HTTPException(409, msg)
            raise HTTPException(404, msg)
        return {"duplicate": False,
                "status": svc.get_cycle(cycle_id)["status"]}

    @router.get("/api/v1/training/data-scope")
    def data_scope() -> dict:
        """三批数据范围投影（来自 ExactDedup/AssetIngest checkpoint）。"""
        svc = _svc()
        rows = store._conn.execute(
            "SELECT cycle_id FROM training_cycle_v1 ORDER BY created_at"
        ).fetchall()
        scope: dict = {"batches": {}, "exact_unique": None,
                       "canonical_points": None, "frozen": False}
        for r in rows:
            try:
                cp = svc.node_checkpoint(r["cycle_id"], "AssetScope")
                scope.update(cp["evidence"])
                scope["frozen"] = cp["status"] == "frozen"
            except CycleError:
                continue
        return scope
