"""U5-2：第一条真实 Loop —— 照片→质量→识别→人工→数据集→评估→误差回流。

口径（手册 §七/U5）：
- 质量节点调用真实 qpol_v2（写不可变 quality_decision_v1），禁止伪造结论；
- 质量 fail 走 feedback 回跳 select（误差回流）：fail SHA 记入审计账本
  并永久排除出本 run 的候选池；
- 数据集只组装（不训练）：仅纳入非 fail 照片，且每条必须在
  quality_decision_v1 中可查到真实结论（完整性校验）；
- 人工门（review）未批准前不得继续；批准后全新引擎实例可续跑；
- 识别走真实识别能力（默认 8091 legacy.recognition.v2，可注入替换）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..data.store import PlatformStore
from ..kernel.loop import EdgeSpec, GraphV2, LoopNodeContext
from ..quality.qpol_v2 import evaluate_image

GRAPH_NAME = "photo_pipeline_v2"


def build_graph(max_rounds: int = 5) -> GraphV2:
    return GraphV2(
        name=GRAPH_NAME, version="v1", entry="select",
        nodes=("select", "quality", "review", "assemble", "recognize"),
        edges=(
            EdgeSpec(src="select", dst="quality", edge_type="next"),
            EdgeSpec(src="quality", dst="select", edge_type="feedback",
                     when="has_fails"),
            EdgeSpec(src="quality", dst="review", edge_type="next",
                     when="clean"),
            EdgeSpec(src="review", dst="assemble", edge_type="next"),
            EdgeSpec(src="assemble", dst="recognize", edge_type="next"),
        ),
        max_rounds=max_rounds,
    )


GRAPH = build_graph()


def _recognize_via_8091(path: Path) -> dict[str, Any]:
    """真实识别：转发 8091 /v2/recognize（失败即抛错，节点 fail-closed）。"""
    from ..adapters.legacy.recognition import RecognitionV2Adapter

    return RecognitionV2Adapter().recognize(path.read_bytes())


def _n_boxes(res: Any) -> int:
    b = (res or {}).get("boxes", res.get("detections") if isinstance(res, dict) else None)
    if isinstance(b, list):
        return len(b)
    try:
        return int(b or 0)
    except (TypeError, ValueError):
        return 0


def build_handlers(
    store: PlatformStore,
    *,
    root: Path,
    source_id: str,
    batch_size: int = 8,
    recognize_fn: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Callable[[LoopNodeContext], dict[str, Any]]]:
    if recognize_fn is None:
        recognize_fn = _recognize_via_8091

    def select(ctx: LoopNodeContext) -> dict[str, Any]:
        seen = set(ctx.shared_get("seen", []))
        pool = [
            a for a in store.list_inventory_assets(
                source_id=source_id, limit=100000)
            if a["sha256"] and a["sha256"] not in seen
            and (root / a["source_uri"]).is_file()
        ]
        pool.sort(key=lambda a: a["source_uri"])
        batch = pool[:batch_size]
        if not batch:
            raise RuntimeError("select: 候选池耗尽，无更多未评估照片")
        ctx.shared_set("seen", sorted(seen | {a["sha256"] for a in batch}))
        ctx.shared_set("batch", [
            {"sha256": a["sha256"], "uri": a["source_uri"]} for a in batch
        ])
        return {"n_selected": len(batch), "round": ctx.round}

    def quality(ctx: LoopNodeContext) -> dict[str, Any]:
        batch = ctx.shared_get("batch", [])
        n_pass = n_waiting = n_fail = 0
        accepted = ctx.shared_get("accepted", [])
        have = {it["sha256"] for it in accepted}
        for item in batch:
            rec = evaluate_image(store, sha256=item["sha256"],
                                 path=root / item["uri"])
            d = rec["auto_decision"]
            if d == "fail":
                n_fail += 1
                # 误差回流：fail 记入不可篡改审计账本
                store.append_audit(
                    actor="loop_v2", action="quality.fail",
                    subject_type="photo", subject_id=item["sha256"],
                    detail={"uri": item["uri"], "round": ctx.round,
                            "policy": rec["policy_version"]},
                )
            else:
                if d == "pass":
                    n_pass += 1
                else:
                    n_waiting += 1
                if item["sha256"] not in have:
                    accepted.append({**item, "auto_decision": d})
                    have.add(item["sha256"])
        ctx.shared_set("accepted", accepted)
        return {"n_pass": n_pass, "n_waiting": n_waiting,
                "n_fail": n_fail, "round": ctx.round}

    def review(ctx: LoopNodeContext) -> dict[str, Any]:
        if ctx.gate_approved():
            return {"human_approved": True, "round": ctx.round}
        accepted = ctx.shared_get("accepted", [])
        ctx.request_human(
            f"质量结论与数据集组装需人工确认：当前 {len(accepted)} 张"
            "非 fail 照片待组装，详见决策轨迹与质量账本")

    def assemble(ctx: LoopNodeContext) -> dict[str, Any]:
        accepted = ctx.shared_get("accepted", [])
        items = []
        for it in accepted:
            decs = store.list_quality_decisions(sha256=it["sha256"], limit=1)
            if not decs:
                raise RuntimeError(
                    f"assemble: {it['sha256']} 缺少真实质量结论，拒绝组装")
            items.append({"sha256": it["sha256"], "uri": it["uri"],
                          "auto_decision": decs[0]["auto_decision"]})
        ctx.shared_set("dataset", items)
        return {"n_items": len(items),
                "note": "仅组装不训练；waiting_human 不等于人工通过"}

    def recognize(ctx: LoopNodeContext) -> dict[str, Any]:
        ds = ctx.shared_get("dataset", [])
        total_boxes = 0
        errors = []
        for it in ds:
            try:
                res = recognize_fn(root / it["uri"])
                total_boxes += _n_boxes(res)
            except Exception as e:  # noqa: BLE001 — 识别失败如实记录
                errors.append({"uri": it["uri"],
                               "error": f"{type(e).__name__}: {e}"})
        if errors:
            raise RuntimeError(
                f"recognize: {len(errors)} 张识别失败（首个："
                f"{errors[0]['error']}）")
        return {"n_recognized": len(ds), "total_boxes": total_boxes}

    return {"select": select, "quality": quality, "review": review,
            "assemble": assemble, "recognize": recognize}


def build_routers() -> dict[str, Callable[[Any, dict], str]]:
    def quality_router(output, state):
        return "has_fails" if output.get("n_fail", 0) > 0 else "clean"

    return {"quality": quality_router}
