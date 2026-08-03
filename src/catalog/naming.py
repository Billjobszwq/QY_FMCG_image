"""SKU 名称解析与归一化匹配键。

存在两套命名法：
  容量在前：'500ml茉莉乌龙（无糖）'
  PET 在后：'茉莉乌龙无糖PET500ML'
归一化匹配键 = (容量, 糖度, 风味核)，用于别名缺失时的兜底匹配。
注意：错字（如 楼/樱）归一化救不了，必须靠别名注册表显式登记。"""
from __future__ import annotations

import re
from typing import Optional

SUGARS = ("无糖", "0糖", "低糖", "微甜")
_VOL = re.compile(r"(\d+)\s*(?:ml|ML)")
_DROP = ("PET", "ML", "ml")


def parse(name: str) -> dict:
    m = _VOL.search(name)
    return {"raw": name, "volume_ml": int(m.group(1)) if m else None, "sugar": next((s for s in SUGARS if s in name), None)}


def _flavor_core(name: str) -> str:
    s = name
    m = _VOL.search(s)
    if m:
        s = s[: m.start()] + s[m.end() :]
    for sugar in SUGARS:
        s = s.replace(sugar, "")
    for d in _DROP:
        s = s.replace(d, "")
    for ch in "（）() 　":
        s = s.replace(ch, "")
    s = s.replace("原味", "")  # '原味乌龙茶' 与 '乌龙茶' 视为同风味核
    return s.strip()


def match_key(name: str) -> tuple:
    p = parse(name)
    return (p["volume_ml"], p["sugar"], _flavor_core(name))
