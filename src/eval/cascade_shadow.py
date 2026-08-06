"""Cascade shadow 评估计算（计划 §Task 17，G-SHADOW 晋级门）。

职责（纯计算，不做任何模型推理）：
- truebox one-to-one 匹配（IoU 降序贪心，GT/pred 各至多一次）；
- 逐实例账本：重复框、背景误检、拒识、错分、新包装、unknown、
  人工路由、延迟、成本全部入账；
- accepted precision 与 coverage 必须同时报告；
- 四套对照 E0/E1/C1/C2 共享同一 frozen data、region matching、
  SKU Registry；
- 晋级门：precision≥线 且 coverage≥线 且 FP/p95/成本/人工率/
  unknown-new 不超批准线；无足够人工真值 → not_evaluable，不得造 pass；
- 真实执行门禁：存在活跃训练 → BLOCKED_BY_ACTIVE_TRAINING（fail-closed）。

记录 schema（shadow 运行产物，逐照片）：
    {"photo_id", "sha256", "human_routed": bool,
     "truths": [{"box":[x1,y1,x2,y2], "sku_id", "human_verified": bool}],
     "predictions": [{"box", "sku_id"|None,
                      "status": accepted|abstain|unknown|new_package|manual_review,
                      "latency_ms", "cost"}]}
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

EVAL_VERSION = "cascade_shadow_v1"

ARM_IDS = ("E0", "E1", "C1", "C2")

LEDGER_LABELS = (
    "correct_accepted",    # 配对成功且 SKU 正确的 accepted
    "misclassification",   # 配对成功但 SKU 错误
    "duplicate_box",       # 与已配对区域重叠的多余框
    "background_fp",       # 背景误检
    "missed_truth",        # 拒识/漏检（未配对的人工真值）
    "abstain",             # 拒答
    "unknown",             # unknown
    "new_package",         # 新包装判断
    "manual_review",       # 路由人工
)

_NON_ACCEPTED_STATUSES = ("abstain", "unknown", "new_package", "manual_review")

_CONFLICT_MARKERS = ("src.training.train_v1", "mlx_vlm.lora")

# 晋级批准线（默认值；正式晋级必须以独立审批后的阈值为准）
DEFAULT_THRESHOLDS: dict[str, float] = {
    "accepted_precision_min": 0.95,  # 专家档目标 ≥95%
    "coverage_min": 0.90,
    "fp_per_photo_max": 0.10,
    "p95_latency_ms_max": 12000.0,
    "total_cost_max": 1000.0,
    "human_rate_max": 0.20,
    "unknown_or_new_rate_max": 0.10,
}

DEFAULT_MIN_EVALUABLE_TRUTHS = 20


# ---------------------------------------------------------------- matching


def _iou(a: Sequence[float], b: Sequence[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def match_one_to_one(
    truths: Sequence[Mapping[str, Any]],
    preds: Sequence[Mapping[str, Any]],
    iou_threshold: float = 0.5,
) -> list[tuple[int, int, float]]:
    """one-to-one greedy：按 IoU 降序配对，truth/pred 各至多一次。

    返回 [(truth_idx, pred_idx, iou)]，确定性 tie-break (ti, pi)。
    """
    pairs = []
    for ti, t in enumerate(truths):
        for pi, p in enumerate(preds):
            v = _iou(t["box"], p["box"])
            if v >= iou_threshold:
                pairs.append((v, ti, pi))
    pairs.sort(key=lambda x: (-x[0], x[1], x[2]))
    used_t, used_p, out = set(), set(), []
    for v, ti, pi in pairs:
        if ti in used_t or pi in used_p:
            continue
        used_t.add(ti)
        used_p.add(pi)
        out.append((ti, pi, v))
    return out


# ---------------------------------------------------------------- ledger


def build_ledger(record: Mapping[str, Any],
                 iou_threshold: float = 0.5) -> list[dict[str, Any]]:
    """将单张照片的预测与人工真值展开为逐实例账本条目。"""
    truths = record.get("truths", [])
    preds = record.get("predictions", [])
    photo_id = record.get("photo_id")
    entries: list[dict[str, Any]] = []

    matches = match_one_to_one(truths, preds, iou_threshold)
    matched_t = {ti: (pi, v) for ti, pi, v in matches}
    matched_p = {pi: (ti, v) for ti, pi, v in matches}

    for pi, p in enumerate(preds):
        status = p.get("status", "accepted")
        base = {"photo_id": photo_id, "kind": "prediction", "index": pi,
                "status": status, "sku_id": p.get("sku_id"),
                "latency_ms": p.get("latency_ms"), "cost": p.get("cost")}
        if pi in matched_p:
            ti, v = matched_p[pi]
            gt_sku = truths[ti].get("sku_id")
            base.update(gt_sku_id=gt_sku, iou=v, matched=True,
                        human_verified=bool(truths[ti].get("human_verified")))
            if status == "accepted":
                base["label"] = ("correct_accepted"
                                 if p.get("sku_id") == gt_sku
                                 else "misclassification")
            else:
                base["label"] = status if status in _NON_ACCEPTED_STATUSES \
                    else "misclassification"
        else:
            base.update(gt_sku_id=None, iou=None)
            if status in _NON_ACCEPTED_STATUSES:
                base["label"] = status
            else:
                # accepted 但未配对：与任一真值重叠 → 重复框，否则背景误检
                overlap = any(_iou(p["box"], t["box"]) >= iou_threshold
                              for t in truths)
                base["label"] = "duplicate_box" if overlap else "background_fp"
        entries.append(base)

    for ti, t in enumerate(truths):
        if ti in matched_t:
            continue
        entries.append({"photo_id": photo_id, "kind": "truth", "index": ti,
                        "label": "missed_truth", "sku_id": t.get("sku_id"),
                        "gt_sku_id": t.get("sku_id"),
                        "human_verified": bool(t.get("human_verified"))})
    return entries


# ---------------------------------------------------------------- metrics


def _percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    vals = sorted(values)
    idx = max(0, min(len(vals) - 1, int(round(q / 100.0 * (len(vals) - 1)))))
    return vals[idx]


def evaluate_arm(arm: Mapping[str, Any],
                 records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """汇总一个对照臂的指标；precision 与 coverage 同时出现在结果中。"""
    threshold = float(arm.get("region_matching", {}).get("iou_threshold", 0.5))
    photos = len(records)
    counts = {label: 0 for label in LEDGER_LABELS}
    latencies: list[float] = []
    total_cost = 0.0
    evaluable_truths = 0
    matched_evaluable = 0
    accepted = 0
    human_photos = 0

    for rec in records:
        entries = build_ledger(rec, iou_threshold=threshold)
        routed = bool(rec.get("human_routed"))
        for e in entries:
            counts[e["label"]] += 1
            if e["kind"] == "prediction":
                if e.get("latency_ms") is not None:
                    latencies.append(float(e["latency_ms"]))
                if e.get("cost") is not None:
                    total_cost += float(e["cost"])
                if e["status"] == "accepted":
                    accepted += 1
                if e["status"] == "manual_review":
                    routed = True
        if routed:
            human_photos += 1
        for t in rec.get("truths", []):
            if t.get("human_verified"):
                evaluable_truths += 1
        for e in entries:
            # coverage：任何已配对的人工真值（含 abstain/unknown 配对）
            if e["kind"] == "prediction" and e.get("matched") \
                    and e.get("human_verified"):
                matched_evaluable += 1

    correct = counts["correct_accepted"]
    coverage = (matched_evaluable / evaluable_truths
                if evaluable_truths else None)
    precision = correct / accepted if accepted else None
    total_preds = sum(1 for rec in records
                      for _ in rec.get("predictions", ()))
    unknown_or_new = counts["unknown"] + counts["new_package"]

    return {
        "arm_id": arm.get("id"),
        "eval_version": EVAL_VERSION,
        "photos": photos,
        "evaluable": evaluable_truths > 0,
        "evaluable_truths": evaluable_truths,
        "accepted": accepted,
        # precision 与 coverage 必须同时报告（允许 None，但键必须存在）
        "accepted_precision": precision,
        "coverage": coverage,
        "label_counts": counts,
        "fp_per_photo": counts["background_fp"] / photos if photos else 0.0,
        "human_rate": human_photos / photos if photos else 0.0,
        "p95_latency_ms": _percentile(latencies, 95),
        "total_cost": round(total_cost, 6),
        "unknown_or_new_rate": (unknown_or_new / total_preds
                                if total_preds else None),
    }


# ---------------------------------------------------------------- arms


def define_arms(*, frozen_data_hash: str, registry_hash: str,
                iou_threshold: float = 0.5) -> dict[str, dict[str, Any]]:
    """四套对照：全部共享同一 frozen data、region matching 与 SKU Registry。

    E0: 当前生产 bundle；E1: sku_v7_sam experimental（不发布）；
    C1: S1–S3 级联（无 Qwen）；C2: S1–S4 级联（qwen3-vl:4b adapter）。
    """
    common = {
        "frozen_data_hash": frozen_data_hash,
        "registry_hash": registry_hash,
        "region_matching": {"method": "one_to_one_iou",
                            "iou_threshold": iou_threshold},
    }
    return {
        "E0": {**common, "id": "E0",
               "description": "当前生产 bundle",
               "publishable_baseline": True, "uses_qwen": False,
               "stages": ["legacy"]},
        "E1": {**common, "id": "E1",
               "description": "sku_v7_sam experimental，不发布",
               "publishable_baseline": False, "uses_qwen": False,
               "stages": ["legacy"]},
        "C1": {**common, "id": "C1",
               "description": "S1–S3 级联，无 Qwen",
               "publishable_baseline": False, "uses_qwen": False,
               "stages": ["S1", "S2", "S3"]},
        "C2": {**common, "id": "C2",
               "description": "S1–S4 级联，Qwen3-VL adapter",
               "publishable_baseline": False, "uses_qwen": True,
               "qwen_model": "qwen3-vl:4b",
               "stages": ["S1", "S2", "S3", "S4"]},
    }


def validate_arms(arms: Mapping[str, Mapping[str, Any]]) -> None:
    """对照臂必须四套齐全且共享同一 frozen 配置，否则拒绝评估。"""
    missing = [aid for aid in ARM_IDS if aid not in arms]
    if missing:
        raise ValueError(f"缺少对照臂: {missing}")
    ref = arms["E0"]
    for aid in ARM_IDS:
        arm = arms[aid]
        for key in ("frozen_data_hash", "registry_hash", "region_matching"):
            if arm.get(key) != ref.get(key):
                raise ValueError(
                    f"对照臂 {aid} 的 {key} 与 E0 不一致，禁止跨配置对比")


# ---------------------------------------------------------------- gate


def promotion_gate(
    metrics: Mapping[str, Any],
    thresholds: Mapping[str, float] | None = None,
    *,
    min_evaluable_truths: int = DEFAULT_MIN_EVALUABLE_TRUTHS,
) -> dict[str, Any]:
    """晋级门：precision 与 coverage 必须同时达标，其余指标不超批准线。

    无足够人工真值 → not_evaluable；绝不得造 pass。
    """
    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    truths = int(metrics.get("evaluable_truths", 0))
    if not metrics.get("evaluable") or truths < min_evaluable_truths:
        return {"status": "not_evaluable",
                "arm_id": metrics.get("arm_id"),
                "reasons": [
                    f"人工真值不足（{truths} < {min_evaluable_truths}），"
                    "无法评估，不得造 pass"],
                "checks": []}

    checks: list[dict[str, Any]] = []

    def _check(name: str, ok: bool, detail: str):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    precision = metrics.get("accepted_precision")
    coverage = metrics.get("coverage")
    _check("precision_and_coverage_present",
           precision is not None and coverage is not None,
           "accepted precision 与 coverage 必须同时报告")
    _check("accepted_precision_min",
           precision is not None and precision >= th["accepted_precision_min"],
           f"precision={precision} ≥ {th['accepted_precision_min']}")
    _check("coverage_min",
           coverage is not None and coverage >= th["coverage_min"],
           f"coverage={coverage} ≥ {th['coverage_min']}")
    _check("fp_per_photo_max",
           metrics.get("fp_per_photo", 0.0) <= th["fp_per_photo_max"],
           f"FP/photo={metrics.get('fp_per_photo')} ≤ {th['fp_per_photo_max']}")
    p95 = metrics.get("p95_latency_ms")
    _check("p95_latency_max",
           p95 is None or p95 <= th["p95_latency_ms_max"],
           f"p95={p95} ≤ {th['p95_latency_ms_max']}")
    _check("total_cost_max",
           metrics.get("total_cost", 0.0) <= th["total_cost_max"],
           f"cost={metrics.get('total_cost')} ≤ {th['total_cost_max']}")
    _check("human_rate_max",
           metrics.get("human_rate", 0.0) <= th["human_rate_max"],
           f"human_rate={metrics.get('human_rate')} ≤ {th['human_rate_max']}")
    un = metrics.get("unknown_or_new_rate")
    _check("unknown_or_new_rate_max",
           un is None or un <= th["unknown_or_new_rate_max"],
           f"unknown/new={un} ≤ {th['unknown_or_new_rate_max']}")

    failed = [c["name"] + ": " + c["detail"] for c in checks if not c["ok"]]
    return {"status": "pass" if not failed else "fail",
            "arm_id": metrics.get("arm_id"),
            "reasons": failed, "checks": checks}


# ---------------------------------------------------------------- execution gate


def shadow_execution_gate(
    *,
    processes: Sequence[str],
    active_training_leases: int,
) -> dict[str, Any]:
    """真实 shadow 运行门禁（G-CURRENT）：存在活跃训练 → fail-closed。"""
    blockers: list[str] = []
    conflicts = [c for c in processes
                 if any(m in c for m in _CONFLICT_MARKERS)]
    if conflicts or active_training_leases > 0:
        blockers.append("BLOCKED_BY_ACTIVE_TRAINING")
    return {"ok": not blockers, "blockers": blockers,
            "conflict_processes": conflicts}
