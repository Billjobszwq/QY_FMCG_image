"""可见 SKU prediction 契约（回归）：

红线：
- prediction / unreviewed / manual_pending 一律不得进入 human_final 训练导出；
- exporter 只接受人工 annotation 中显式 status=matched 且 SKU 在 Registry 的 region；
- SAM prediction 结构不得携带 matched 语义。
"""
from __future__ import annotations

from src.ls_platform.exporter import _parse_regions, _region_lines
from src.sam_assist.prediction import to_ls_prediction

CLASSMAP = {"可口可乐500ml": 1, "雪碧500ml": 2}

BOX = {"x": 10.0, "y": 10.0, "width": 20.0, "height": 30.0, "rotation": 0}


def _region(status: str, sku: str | None = "可口可乐500ml") -> list[dict]:
    result = [{
        "id": "r1", "from_name": "box", "to_name": "image",
        "type": "rectanglelabels",
        "value": {**BOX, "rectanglelabels": ["product"]},
    }]
    if sku is not None:
        result.append({
            "id": "r1", "from_name": "sku", "to_name": "image",
            "type": "taxonomy", "value": {**BOX, "taxonomy": [[sku]]},
        })
    if status is not None:
        result.append({
            "id": "r1", "from_name": "status", "to_name": "image",
            "type": "choices", "value": {**BOX, "choices": [status]},
        })
    return result


def test_unreviewed_region_never_enters_training_export() -> None:
    regions = _parse_regions(_region("unreviewed"))
    counters = {"skipped_status": 0, "skipped_sku": 0, "skipped_box": 0}
    lines = _region_lines(regions, CLASSMAP, only_matched=True,
                          counters=counters)
    assert lines == []
    assert counters["skipped_status"] == 1


def test_matched_region_with_registry_sku_exports() -> None:
    regions = _parse_regions(_region("matched"))
    lines = _region_lines(regions, CLASSMAP, only_matched=True)
    assert len(lines) == 1 and lines[0].startswith("1 ")


def test_matched_but_sku_out_of_registry_skipped() -> None:
    regions = _parse_regions(_region("matched", sku="不存在SKU"))
    counters = {"skipped_status": 0, "skipped_sku": 0, "skipped_box": 0}
    lines = _region_lines(regions, CLASSMAP, only_matched=True,
                          counters=counters)
    assert lines == [] and counters["skipped_sku"] == 1


def test_sam_prediction_never_carries_matched_semantics() -> None:
    pred = to_ls_prediction(
        width=1500, height=2000,
        visible_tight_box=(480.0, 700.0, 520.0, 900.0),
        model_version="sam2.1_hiera_small@" + "0" * 16, score=0.87)
    for r in pred["result"]:
        assert r["type"] == "rectanglelabels", \
            "SAM prediction 只能有框，不得写 taxonomy/状态"
    meta = pred.get("metadata", {})
    assert meta.get("is_final_annotation") is False


def test_label_config_contains_unreviewed_and_human_statuses() -> None:
    """label_config 必须提供 unreviewed 初始态 + 4 个人工裁决状态。"""
    from src.ls_platform.gen_label_config import build_config

    registry = {"可口可乐500ml": {"sku_id": "QY_KK_000001",
                               "name": "可口可乐500ml", "class_id": 1}}
    xml = build_config(registry)
    for choice in ("unreviewed", "matched", "unknown", "conflict",
                   "unreadable"):
        assert f'value="{choice}"' in xml
    assert 'name="sku"' in xml and "perRegion" in xml


def test_importer_seed_prediction_uses_unreviewed_not_matched() -> None:
    """种子点标注 prediction 也不得自动写 matched（人工未确认）。"""
    from src.ls_platform.importer import _build_prediction_result

    ann = {"x": 100, "y": 200, "name": "可口可乐500ml"}
    result = _build_prediction_result(ann, 1000, 1000, {"可口可乐500ml"})
    statuses = [r for r in result if r["type"] == "choices"]
    assert statuses and statuses[0]["value"]["choices"] == ["unreviewed"]
