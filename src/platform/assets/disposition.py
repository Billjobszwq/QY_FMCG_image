"""U3-4：用途与冻结角色分流（规则引擎，只读台账，可重放）。

手册 §5/§7/指令口径：所有源照片必须归入至少一种用途；
frozen protocol 只用于评估，禁止泄漏进 detector 训练；
坏样本只进质量模型与证据；标准商品图进 classifier/retrieval/包装版本。

用途枚举（7 种）：
- detector_training      detector 训练候选（仍须过质量/标签/冻结门禁）
- classifier_retrieval   classifier/retrieval
- packaging_unknown_sku  包装版本/未知 SKU
- quality_negative       质量负样本
- eval_frozen            评估冻结集（只评估，不训练）
- to_label               待标注
- rejection_evidence     拒绝证据
"""
from __future__ import annotations

from typing import Any

PURPOSES = (
    "detector_training",
    "classifier_retrieval",
    "packaging_unknown_sku",
    "quality_negative",
    "eval_frozen",
    "to_label",
    "rejection_evidence",
)

# 来源级规则（source_id → 用途列表）
_SOURCE_RULES: dict[str, tuple[str, ...]] = {
    "batch1_manifest": ("detector_training", "classifier_retrieval"),
    "batch2_manifest": ("detector_training", "classifier_retrieval"),
    "batch3_clean": ("detector_training", "classifier_retrieval"),
    # 灰区：难以判定 → 待标注 + 包装版本/未知 SKU 候选
    "batch3_gray": ("to_label", "packaging_unknown_sku"),
    # 未标注实拍货架照
    "photo1106": ("to_label",),
    "photo1107": ("to_label",),
    "pepsi_cola": ("to_label",),
    "field_blobs": ("to_label",),
    # 标准商品图（SKU 参考图）→ classifier/retrieval + 包装版本
    "p1_reference": ("classifier_retrieval", "packaging_unknown_sku"),
    # 坏样本：只进质量模型与证据，禁止进训练
    "bad_samples": ("quality_negative", "rejection_evidence"),
}


def assign_dispositions(source_id: str, source_uri: str) -> list[str]:
    """给一条台账引用分配用途（至少一种；规则确定性、可重放）。"""
    if source_id == "protocols":
        # 全部 frozen protocol（gold/calibration/dev/diagnostic/holdout）
        # 只用于评估，禁止进入任何训练用途。
        return ["eval_frozen"]
    return list(_SOURCE_RULES.get(source_id, ("to_label",)))


def disposition_report(store) -> dict[str, Any]:
    """遍历台账产出处置报告：分布、无用途行数、冻结→训练泄漏检查。"""
    rows = store._conn.execute(
        "SELECT asset_id, source_id, source_uri"
        " FROM source_asset_inventory_v1 ORDER BY asset_id").fetchall()
    dist = {p: 0 for p in PURPOSES}
    no_purpose = 0
    frozen: list[str] = []
    training: list[str] = []
    for r in rows:
        ps = assign_dispositions(r["source_id"], r["source_uri"])
        if not ps:
            no_purpose += 1
            continue
        for p in ps:
            dist[p] += 1
        if "eval_frozen" in ps:
            frozen.append(r["asset_id"])
        if "detector_training" in ps:
            training.append(r["asset_id"])
    leak = len(set(frozen) & set(training))
    return {
        "total_rows": len(rows),
        "rows_without_purpose": no_purpose,
        "distribution": dist,
        "assets_eval_frozen": frozen,
        "assets_detector_training": training,
        "leak_frozen_into_training": leak,
        "note": ("eval_frozen 与 detector_training 必须不相交；"
                 "detector_training 仅是候选用途，实际入选仍须过"
                 "质量/标签等级/冻结协议门禁（Snapshot builder）"),
    }
