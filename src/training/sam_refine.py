"""SAM 精修标注纯函数（数据集坐标 → SAM box prompt → 紧框替换）。

口径：
- 数据集现有 YOLO 粗框作为 SAM 的 box prompt，SAM 输出 mask 的紧框
  （tight box）替换原框几何；SKU 类别沿用原框（坐标定位）。
- SAM 框不合法（退化/越逃/过大）时回退原框，绝不伪造新框。
- 本模块为纯函数，不含 SAM 权重加载；推理在隔离 venv worker 执行。"""
from __future__ import annotations

from pathlib import Path

# 精修硬约束（fail-closed：任何一条不满足即回退原框）
MIN_AREA_PX = 64          # 紧框最小像素面积
MAX_AREA_SHARE = 0.5      # 紧框占整图面积上限（超过视为背景误分割）
MAX_ASPECT_RATIO = 30.0   # 长短边比上限
MAX_REL_AREA = 4.0        # 紧框面积 / 原框面积 上限
DEFAULT_TOL = 0.25        # 紧框允许超出原框的相对边长容忍带


def parse_yolo_label(text: str, *, width: int, height: int) -> list[dict]:
    """解析 YOLO 标签文本 → [{class_id, box_px(x1,y1,x2,y2)}]。非法行抛 ValueError。"""
    rows = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split()
        if len(parts) != 5:
            raise ValueError(f"YOLO 标签行字段数错误: {ln!r}")
        try:
            cid = int(parts[0])
            cx, cy, w, h = (float(v) for v in parts[1:])
        except ValueError as e:
            raise ValueError(f"YOLO 标签行数值非法: {ln!r}") from e
        for v in (cx, cy, w, h):
            if not (0.0 <= v <= 1.0):
                raise ValueError(f"YOLO 标签行越界: {ln!r}")
        bw, bh = w * width, h * height
        rows.append({
            "class_id": cid,
            "box_px": (cx * width - bw / 2, cy * height - bh / 2,
                       cx * width + bw / 2, cy * height + bh / 2),
        })
    return rows


def is_valid_bbox(box: tuple, width: int, height: int, *,
                  min_area_px: float = MIN_AREA_PX,
                  max_area_share: float = MAX_AREA_SHARE,
                  max_ratio: float = MAX_ASPECT_RATIO) -> bool:
    """框合法性硬约束：非退化、在图内、面积/长宽比不极端。"""
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return False
    if x1 < 0 or y1 < 0 or x2 > width or y2 > height:
        return False
    bw, bh = x2 - x1, y2 - y1
    if bw * bh < min_area_px:
        return False
    if bw * bh > max_area_share * width * height:
        return False
    ratio = max(bw, bh) / max(min(bw, bh), 1e-9)
    if ratio > max_ratio:
        return False
    return True


def clamp_bbox(box: tuple, width: int, height: int) -> tuple:
    """裁剪到图像范围。"""
    x1, y1, x2, y2 = box
    return (max(0, min(x1, width)), max(0, min(y1, height)),
            max(0, min(x2, width)), max(0, min(y2, height)))


def refine_one(orig_box: tuple, sam_box: tuple | None,
               width: int, height: int, *, tol: float = DEFAULT_TOL,
               max_rel_area: float = MAX_REL_AREA) -> tuple[tuple, str]:
    """单框精修：SAM 紧框合法且未逃逸 → 接受；否则回退原框。

    返回 (final_box, source)，source ∈ {"sam", "orig"}。
    接受条件（全部满足）：
    1. sam_box 非空且通过图像级硬约束；
    2. SAM 框中心落在原框内（防止抓错相邻瓶子）；
    3. SAM 框面积不超过原框 max_rel_area 倍；
    4. SAM 框超出原框的部分在容忍带内（相对原框边长）。
    """
    if sam_box is None:
        return orig_box, "orig"
    if not is_valid_bbox(sam_box, width, height):
        return orig_box, "orig"
    sx1, sy1, sx2, sy2 = sam_box
    ox1, oy1, ox2, oy2 = orig_box
    # 中心必须保留在原框内
    cx, cy = (sx1 + sx2) / 2, (sy1 + sy2) / 2
    if not (ox1 <= cx <= ox2 and oy1 <= cy <= oy2):
        return orig_box, "orig"
    # 面积上限
    orig_area = max((ox2 - ox1) * (oy2 - oy1), 1e-9)
    if (sx2 - sx1) * (sy2 - sy1) > max_rel_area * orig_area:
        return orig_box, "orig"
    # 容忍带：允许超出原框最多 tol * 原框边长
    bw, bh = ox2 - ox1, oy2 - oy1
    if (sx1 < ox1 - tol * bw or sx2 > ox2 + tol * bw
            or sy1 < oy1 - tol * bh or sy2 > oy2 + tol * bh):
        return orig_box, "orig"
    return clamp_bbox(sam_box, width, height), "sam"


def to_yolo_line(class_id, box_px: tuple, *, width: int, height: int) -> str:
    """像素框 → YOLO 归一化行。越界/退化抛 ValueError。

    容差 0.5px：解析→回写存在浮点误差（如 -0.00075），在容差内先裁剪到
    图像范围再写；超出容差仍视为非法。"""
    x1, y1, x2, y2 = box_px
    eps = 0.5
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"像素框退化: {box_px}")
    if x1 < -eps or y1 < -eps or x2 > width + eps or y2 > height + eps:
        raise ValueError(f"像素框越界: {box_px} (图像 {width}x{height})")
    x1, y1 = max(0.0, x1), max(0.0, y1)
    x2, y2 = min(float(width), x2), min(float(height), y2)
    cx = ((x1 + x2) / 2) / width
    cy = ((y1 + y2) / 2) / height
    w = (x2 - x1) / width
    h = (y2 - y1) / height
    return f"{class_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}"


def write_yolo_label(path: Path, rows: list[tuple], *, width: int, height: int) -> None:
    """rows: [(class_id, box_px)] → YOLO 标签文件。"""
    lines = [to_yolo_line(cid, box, width=width, height=height) for cid, box in rows]
    Path(path).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
