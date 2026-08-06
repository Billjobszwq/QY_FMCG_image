"""Task 13（VLM-013）：级联计费账本（cascade_usage）。

设计约束：
- 不建立第二套计费系统：账本落在平台 PlatformStore 的 cascade_usage 表（迁移 016），
  与既有 usage_event（保留、只读历史）并存，不覆盖不 rename。
- 每个 node attempt 一条账目：capability、model/model_version、photos/regions/tokens、
  compute_ms、customer tier、cold_start、cache_hit、rate_card_version、
  resource_cost、billed_cost 全字段留痕。
- 幂等：UNIQUE(run_id, billing_key)。billing_key 形如 'node#r{round}'，
  相同 key 重试不重复计费，返回首次账目。
- rate card 只做本地核算（影子阶段），金额单位是内部积分，不代表真实货币定价。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

RATE_CARD_VERSION = "rate-card.v1"

# capability -> (每次调用基础分, 每 token 分, 每 region 分)
RATE_CARD: dict[str, tuple[float, float, float]] = {
    "cap.quality.v1": (1.0, 0.0, 0.0),
    "cap.scene.v1": (1.0, 0.0, 0.0),
    "cap.detect.yolo11": (2.0, 0.0, 0.5),
    "cap.classify.resnet50": (2.0, 0.0, 0.5),
    "cap.segment.sam": (6.0, 0.0, 2.0),
    "cap.retrieve.sku": (2.0, 0.0, 0.0),
    "cap.vlm.qwen3vl4b": (10.0, 0.002, 0.0),
}
_DEFAULT_RATE = (1.0, 0.0, 0.0)

# tier 乘数：档位越高允许的级联深度越大，核算权重随之上浮
TIER_MULTIPLIER: dict[str, float] = {
    "fast": 1.0,
    "standard": 1.0,
    "deep": 1.2,
    "expert": 1.5,
}


class CascadeBillingError(Exception):
    """计费域错误（缺失 run、非法字段等）。"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cost(capability: str, *, regions: int, tokens: int, compute_ms: float) -> float:
    base, per_token, per_region = RATE_CARD.get(capability, _DEFAULT_RATE)
    return round(base + per_region * regions + per_token * tokens
                 + compute_ms / 1000.0, 6)


def bill_attempt(
    store,
    *,
    run_id: str,
    billing_key: str,
    capability: str,
    tier: str,
    model: str = "",
    model_version: str = "",
    photos: int = 1,
    regions: int = 0,
    tokens: int = 0,
    compute_ms: float = 0.0,
    cold_start: bool = False,
    cache_hit: bool = False,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """为一个 node attempt 记账（幂等）。

    相同 (run_id, billing_key) 重试时返回首次账目，不重复计费。
    """
    if tier not in TIER_MULTIPLIER:
        raise CascadeBillingError(f"未知客户档位: {tier}")
    # run 必须存在（fail-closed），避免孤儿账目
    try:
        store.get_run(run_id)
    except Exception as e:
        raise CascadeBillingError(f"run 不存在，拒绝记账: {run_id}") from e

    row = store._conn.execute(
        "SELECT * FROM cascade_usage WHERE run_id=? AND billing_key=?",
        (run_id, billing_key),
    ).fetchone()
    if row is not None:
        entry = dict(row)
        entry["cold_start"] = bool(entry["cold_start"])
        entry["cache_hit"] = bool(entry["cache_hit"])
        return entry  # 幂等：重复 attempt 不再计费

    resource_cost = _cost(capability, regions=regions, tokens=tokens,
                          compute_ms=compute_ms)
    billed_cost = round(resource_cost * TIER_MULTIPLIER[tier], 6)
    store._conn.execute(
        "INSERT INTO cascade_usage(ts, run_id, billing_key, capability, model,"
        " model_version, tier, photos, regions, tokens, compute_ms, cold_start,"
        " cache_hit, rate_card_version, resource_cost, billed_cost, detail_json)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            _utcnow(), run_id, billing_key, capability, model, model_version,
            tier, photos, regions, tokens, compute_ms,
            int(cold_start), int(cache_hit), RATE_CARD_VERSION,
            resource_cost, billed_cost,
            json.dumps(detail or {}, ensure_ascii=False),
        ),
    )
    store._conn.commit()
    return {
        "run_id": run_id,
        "billing_key": billing_key,
        "capability": capability,
        "model": model,
        "model_version": model_version,
        "tier": tier,
        "photos": photos,
        "regions": regions,
        "tokens": tokens,
        "compute_ms": compute_ms,
        "cold_start": cold_start,
        "cache_hit": cache_hit,
        "rate_card_version": RATE_CARD_VERSION,
        "resource_cost": resource_cost,
        "billed_cost": billed_cost,
    }


def list_billing(store, *, run_id: str, limit: int = 200) -> list[dict[str, Any]]:
    """列出某 run 的全部账目（按记账顺序）。"""
    rows = store._conn.execute(
        "SELECT * FROM cascade_usage WHERE run_id=? ORDER BY usage_id LIMIT ?",
        (run_id, limit),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["cold_start"] = bool(d["cold_start"])
        d["cache_hit"] = bool(d["cache_hit"])
        out.append(d)
    return out


def billing_total(store, *, run_id: str) -> dict[str, Any]:
    """汇总某 run 的计费（条目数、资源成本、账单成本、VLM tokens）。"""
    rows = store._conn.execute(
        "SELECT resource_cost, billed_cost, tokens FROM cascade_usage WHERE run_id=?",
        (run_id,),
    ).fetchall()
    return {
        "run_id": run_id,
        "rate_card_version": RATE_CARD_VERSION,
        "entries": len(rows),
        "resource_cost": round(sum(r["resource_cost"] for r in rows), 6),
        "billed_cost": round(sum(r["billed_cost"] for r in rows), 6),
        "tokens": int(sum(r["tokens"] for r in rows)),
    }
