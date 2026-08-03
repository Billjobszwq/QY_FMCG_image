"""定位（双模式）。不依赖训好的 YOLO（标注阶段还没有它，否则循环）。

模式 B（带种子=点或框）：种子→整瓶框；点用与尺度无关的瓶身比例启发式外扩。
模式 A（无种子）：OCR 文本框→产品区域（LOC 缩放按 LOC_NORM 假设，需校准）。"""
from __future__ import annotations

from ..common import omlx

BOX_W_FRAC = 0.07   # 瓶身宽占整图比例（启发式，可调）
BOX_H_FRAC = 0.18   # 瓶身高占整图比例
LOC_NORM = 1000.0   # PaddleOCR-VL 的 LOC 坐标假设归一化到 0..1000（需校准，仅 Mode A）


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _box_from_point(x, y, W, H):
    w, h = BOX_W_FRAC * W, BOX_H_FRAC * H
    return [_clamp(x - w / 2, 0, W - 1), _clamp(y - h / 2, 0, H - 1), _clamp(x + w / 2, 0, W - 1), _clamp(y + h / 2, 0, H - 1)]


def _center(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _nearest(point, boxes):
    px, py = point
    best, bd = None, 1e18
    for b in boxes:
        cx, cy = _center(b)
        d = (cx - px) ** 2 + (cy - py) ** 2
        if d < bd:
            bd, best = d, b
    return best


def _expand_vertical(b, H, up=1.2, down=1.6, wpad=1.3):
    x1, y1, x2, y2 = b
    bw = (x2 - x1) * wpad
    cx = (x1 + x2) / 2
    nh = (y2 - y1) * (1 + up + down)
    cy = (y1 + y2) / 2 + (down - up) / 2 * (y2 - y1)
    return [_clamp(cx - bw / 2, 0, 99999), _clamp(cy - nh / 2, 0, H), _clamp(cx + bw / 2, 0, 99999), _clamp(cy + nh / 2, 0, H)]


def seed_to_box(seed, W, H, ocr_boxes_px=None, snap=False):
    """seed 为 {x,y} 点 或 {x1,y1,x2,y2} 框。"""
    if all(k in seed for k in ("x1", "y1", "x2", "y2")):
        return [_clamp(seed["x1"], 0, W), _clamp(seed["y1"], 0, H), _clamp(seed["x2"], 0, W), _clamp(seed["y2"], 0, H)]
    x, y = seed["x"], seed["y"]
    if snap and ocr_boxes_px:
        nb = _nearest((x, y), ocr_boxes_px)
        if nb:
            return _expand_vertical(nb, H)
    return _box_from_point(x, y, W, H)


def ocr_boxes_px(image_bytes, W, H, mime="image/png"):
    raw = omlx.ocr_boxes(image_bytes, mime=mime)
    return [[a / LOC_NORM * W, b / LOC_NORM * H, c / LOC_NORM * W, d / LOC_NORM * H] for r in raw for (a, b, c, d) in (r["bbox"],)]


def discover_regions(image_bytes, W, H, mime="image/png"):
    return [_expand_vertical(b, H) for b in ocr_boxes_px(image_bytes, W, H, mime)]
