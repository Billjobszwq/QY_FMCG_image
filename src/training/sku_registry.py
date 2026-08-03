"""SKU 注册表构建：从训练数据 xlsx 提取所有 SKU name，分配 QY_YL_000000 起编号。

输出：data/sku_registry.json（name → sku_id 映射 + 元数据）
用法：python -m src.training.sku_registry"""
from __future__ import annotations

import json
from pathlib import Path

import openpyxl

from ..common.config import PROJECT_ROOT

XLSX = PROJECT_ROOT / "第一批训练数据.xlsx"
OUT = PROJECT_ROOT / "data" / "sku_registry.json"


def build_registry(xlsx: Path = XLSX) -> dict:
    """解析 xlsx 中所有唯一 name，按字母排序分配 QY_YL_000000 起编号。"""
    wb = openpyxl.load_workbook(str(xlsx), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(c).strip() if c else "" for c in rows[0]]
    name_idx = header.index("name")
    wb.close()

    names = sorted({str(r[name_idx]).strip() for r in rows[1:] if r[name_idx]})
    registry = {}
    for i, name in enumerate(names):
        sku_id = f"QY_YL_{i:06d}"
        registry[name] = {
            "sku_id": sku_id,
            "name": name,
            "class_id": i,
        }
    return registry


def save_registry(registry: dict, out: Path = OUT):
    out.parent.mkdir(parents=True, exist_ok=True)
    # 输出格式：{name: {sku_id, name, class_id}}
    out.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    # 同时输出 classes 列表（YOLO 用）
    classes_path = out.parent / "sku_classes.json"
    classes = sorted(registry.keys(), key=lambda n: registry[n]["class_id"])
    classes_path.write_text(json.dumps(classes, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main():
    registry = build_registry()
    save_registry(registry)
    print(f"SKU_REGISTRY: {len(registry)} SKUs, IDs QY_YL_000000 ~ QY_YL_{len(registry)-1:06d}")
    print(f"  -> {OUT}")
    print(f"  -> {OUT.parent / 'sku_classes.json'}")
    # 打印前10个
    for i, (name, info) in enumerate(sorted(registry.items(), key=lambda x: x[1]["class_id"])):
        if i >= 10:
            print(f"  ... ({len(registry) - 10} more)")
            break
        print(f"  {info['sku_id']}: {name}")
    return registry


if __name__ == "__main__":
    main()
