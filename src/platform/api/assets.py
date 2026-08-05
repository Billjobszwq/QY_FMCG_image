"""U2-2：数据中心 Asset API（真实台账 source_asset_inventory_v1）。

数据全部来自 U3 不可变台账 + SHA 去重 + 用途分流；只读；
禁止占位假状态。每行附 purposes（用途）、registered_at（血缘登记时间）。
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..assets.dedup import sha_dedupe
from ..assets.disposition import PURPOSES, assign_dispositions, \
    disposition_report


def create_assets_router(store) -> APIRouter:
    router = APIRouter(tags=["assets"])

    @router.get("/api/v1/assets/summary")
    def assets_summary() -> dict:
        exact = sha_dedupe(store)
        disp = disposition_report(store)
        sources = [r["source_id"] for r in store._conn.execute(
            "SELECT DISTINCT source_id FROM source_asset_inventory_v1"
            " ORDER BY source_id")]
        return {
            "total_refs": exact["total_refs"],
            "unique_sha": exact["unique_sha"],
            "exact_dup_groups": exact["exact_dup_groups"],
            "rows_without_sha": exact["rows_without_sha"],
            "purposes": disp["distribution"],
            "rows_without_purpose": disp["rows_without_purpose"],
            "leak_frozen_into_training": disp["leak_frozen_into_training"],
            "sources": sources,
            "immutable": True,
            "note": ("台账为追加式不可变（source_asset_inventory_v1）；"
                     "unique_sha 为 SHA 精确去重唯一数，"
                     "禁止把目录数量相加冒充唯一照片总数"),
        }

    @router.get("/api/v1/assets")
    def assets_list(
        source_id: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        count = store.count_inventory_assets(source_id=source_id)
        rows = store.list_inventory_assets(
            source_id=source_id, limit=limit, offset=offset)
        items = [
            {**r, "purposes": assign_dispositions(r["source_id"],
                                                  r["source_uri"])}
            for r in rows
        ]
        return {"count": count, "items": items,
                "purposes_vocab": list(PURPOSES)}

    return router
