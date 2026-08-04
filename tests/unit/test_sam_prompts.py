"""SAM 提示构造契约（手册§六）：坐标点=正提示，相邻 SKU 点=负提示，
固定比例框只作粗 ROI（coarse_only），不得作为真实框。"""
import pytest

from src.sam_assist.contracts import InstanceInput
from src.sam_assist.prompts import GENERAL_PRODUCT_FRAC, PromptConfig, build_prompts


def _inst(iid, x, y, sku_raw="", canonical=None):
    return InstanceInput(
        asset_id="asset_1", photo_id="p1", image_sha256="a" * 64,
        width=1500, height=2000, instance_id=iid, x=float(x), y=float(y),
        sku_raw_name=sku_raw, sku_canonical=canonical, quality_version="qv1")


def _registry_frac(name):
    # 模拟 sku_box_frac：注册 SKU 有各自比例
    return {"乌龙茶500": (0.06, 0.20)}.get(name)


def test_positive_point_is_instance_coord():
    target = _inst("i1", 500, 800, "乌龙茶500", "c1")
    p = build_prompts(target, [target], _registry_frac, PromptConfig())
    assert p.positive_point == (500.0, 800.0)
    assert p.positive_label == 1


def test_nearest_neighbors_within_radius_are_negatives():
    target = _inst("i1", 500, 800, "乌龙茶500")
    near = _inst("i2", 560, 810)        # 在半径内 → 负提示
    far = _inst("i3", 1200, 800)        # 超出半径 → 不参与
    cfg = PromptConfig(neg_radius_px=200.0, max_negatives=4)
    p = build_prompts(target, [target, near, far], _registry_frac, cfg)
    assert (560.0, 810.0) in p.negative_points
    assert (1200.0, 800.0) not in p.negative_points
    assert all(l == 0 for l in p.negative_labels)


def test_negative_never_same_instance_or_duplicate_positive():
    target = _inst("i1", 500, 800)
    dup = _inst("i1", 500, 800)  # 同 instance_id 不得成为负点
    p = build_prompts(target, [target, dup], _registry_frac, PromptConfig())
    assert p.negative_points == ()


def test_max_negatives_cap_nearest_first():
    target = _inst("i0", 500, 800)
    others = [_inst(f"i{k}", 500 + 10 * k, 800) for k in range(1, 6)]
    cfg = PromptConfig(neg_radius_px=1000.0, max_negatives=2)
    p = build_prompts(target, [target] + others, _registry_frac, cfg)
    assert len(p.negative_points) == 2
    assert p.negative_points == ((510.0, 800.0), (520.0, 800.0))  # 最近优先


def test_coarse_box_uses_registered_frac_with_configurable_expand():
    target = _inst("i1", 500, 800, "乌龙茶500")
    cfg = PromptConfig(roi_expand=1.4)
    p = build_prompts(target, [target], _registry_frac, cfg)
    bw, bh = 0.06 * 1500 * 1.4, 0.20 * 2000 * 1.4
    x1, y1, x2, y2 = p.coarse_box
    assert abs((x2 - x1) - bw) < 1e-6 and abs((y2 - y1) - bh) < 1e-6
    assert abs((x1 + x2) / 2 - 500) < 1e-6
    assert p.coarse_only is True, "固定比例框只能作粗 ROI，必须标 coarse_only"


def test_unregistered_sku_uses_general_product_roi_not_dropped():
    target = _inst("i9", 300, 400, "未注册新包装")
    cfg = PromptConfig(roi_expand=1.0)
    p = build_prompts(target, [target], _registry_frac, cfg)
    bw, bh = GENERAL_PRODUCT_FRAC
    x1, y1, x2, y2 = p.coarse_box
    assert x2 > x1 and y2 > y1
    assert abs((x2 - x1) - bw * 1500) < 1e-6
    assert abs((y2 - y1) - bh * 2000) < 1e-6
    assert p.coarse_only is True


def test_coarse_box_clamped_to_image():
    target = _inst("i1", 5, 5, "乌龙茶500")
    p = build_prompts(target, [target], _registry_frac, PromptConfig(roi_expand=2.0))
    x1, y1, x2, y2 = p.coarse_box
    assert x1 >= 0 and y1 >= 0 and x2 <= 1500 and y2 <= 2000


def test_expand_ratio_not_hardcoded():
    """默认扩张比例必须通过配置管理（手册§六.3）。"""
    cfg = PromptConfig()
    assert hasattr(cfg, "roi_expand")
    target = _inst("i1", 500, 800, "乌龙茶500")
    p1 = build_prompts(target, [target], _registry_frac, PromptConfig(roi_expand=1.0))
    p2 = build_prompts(target, [target], _registry_frac, PromptConfig(roi_expand=2.0))
    w1 = p1.coarse_box[2] - p1.coarse_box[0]
    w2 = p2.coarse_box[2] - p2.coarse_box[0]
    assert abs(w2 - 2 * w1) < 1e-6


def test_prompt_set_records_config_version():
    target = _inst("i1", 500, 800, "乌龙茶500")
    p = build_prompts(target, [target], _registry_frac, PromptConfig())
    assert p.config_version  # 提示参数版本必须可追溯
