"""VLM-008：Canonical Sample → HF Dataset 行（images + messages）。

红线（计划 §Task 8 Step 6）：消息由 processor/chat template 处理，
禁止手工硬编码 <|vision_start|>；图像作为结构化 content 引用传入。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Iterable

from src.training.vlm.contracts import VlmSample

QUESTION_TEMPLATE = (
    "请对该区域做闭集 SKU 裁决：若属于候选内的已知 SKU 输出 accepted 并给出 "
    "sku_id；若证据不足输出 insufficient_evidence；若无法识别输出 unknown；"
    "若为同 SKU 新包装输出 same_sku_new_package；若疑似全新 SKU 输出 "
    "possible_new_sku。只输出 qwen-sku-decision.v1 JSON。"
)


def _answer(sample: VlmSample) -> dict[str, Any]:
    """金标准答案（来自人工裁决的 label，不是模型输出）。"""
    if sample.target_type == "closed_set" or sample.target_type == "hard_negative":
        return {"schema_version": "qwen-sku-decision.v1", "decision": "accepted",
                "sku_id": sample.sku_id,
                "package_version_id": sample.package_version_id,
                "evidence": list(sample.evidence_ids), "abstain_reason": None}
    if sample.target_type == "new_package":
        return {"schema_version": "qwen-sku-decision.v1",
                "decision": "same_sku_new_package",
                "sku_id": sample.sku_id,
                "package_version_id": None,
                "evidence": list(sample.evidence_ids), "abstain_reason": None}
    # unknown
    return {"schema_version": "qwen-sku-decision.v1", "decision": "unknown",
            "sku_id": None, "package_version_id": None,
            "evidence": list(sample.evidence_ids),
            "abstain_reason": "outside_closed_set"}


def build_hf_rows(
    samples: Iterable[VlmSample],
    *,
    load_image: Callable[[str], Any],
) -> list[dict[str, Any]]:
    """每条 sample → {"images": [...], "messages": [...]}。

    load_image(image_uri) 由调用方注入（真实读取被训练门禁阻断，
    测试使用 fake）。不插入任何手工 vision token。
    """
    rows: list[dict[str, Any]] = []
    for s in samples:
        image = load_image(s.image_uri)
        context = json.dumps(
            {"region": {"bbox_1000": list(s.bbox_1000)},
             "image_width": s.image_width, "image_height": s.image_height,
             "registry_version": s.registry_version},
            ensure_ascii=False, sort_keys=True)
        rows.append({
            "images": [image],
            "messages": [
                {"role": "user",
                 "content": [
                     {"type": "image", "image": image},
                     {"type": "text",
                      "text": f"{QUESTION_TEMPLATE}\n{context}"},
                 ]},
                {"role": "assistant",
                 "content": [
                     {"type": "text",
                      "text": json.dumps(_answer(s), ensure_ascii=False)},
                 ]},
            ],
        })
    return rows
