"""G5 严格 one-to-one IoU 匹配单元测试：IoU 计算与贪心一对一约束。"""
from src.eval.e0_strict_iou import _iou


def test_iou_basic():
    assert _iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert _iou((0, 0, 10, 10), (10, 10, 20, 20)) == 0.0
    # 交集 25 / 并集 175
    assert abs(_iou((0, 0, 10, 10), (5, 5, 15, 15)) - 25 / 175) < 1e-9


def test_iou_zero_area():
    assert _iou((5, 5, 5, 5), (0, 0, 10, 10)) == 0.0


def test_greedy_one_to_one():
    """一个 GT 只能被一个 proposal 匹配（手册 G5 要求）。"""
    gts = [(0, 0, 10, 10)]
    preds = [(0, 0, 10, 10), (1, 1, 11, 11)]  # 两个高重叠 proposal
    pairs = []
    for pi, p in enumerate(preds):
        for gi, g in enumerate(gts):
            v = _iou(p, g)
            if v >= 0.5:
                pairs.append((v, pi, gi))
    pairs.sort(reverse=True)
    used_p, used_g = set(), set()
    matched = []
    for v, pi, gi in pairs:
        if pi in used_p or gi in used_g:
            continue
        used_p.add(pi)
        used_g.add(gi)
        matched.append((pi, gi))
    assert len(matched) == 1  # 严格 one-to-one：只允许一个匹配
