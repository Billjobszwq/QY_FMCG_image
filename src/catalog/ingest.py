"""参考图库遍历与记录骨架。

默认角色：jpg = 单品平躺旋转实拍（已肉眼核实，统一不再逐张问 VLM）；
png = 标准/促销图，需 VLM 判定是否促销合成图（multi_or_promo 则排除出参考库）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import naming

IMG_EXT = {".jpg", ".jpeg", ".png"}
JPG = {".jpg", ".jpeg"}


@dataclass
class SkuRecord:
    id: str
    display: str
    kb_folder: str
    kb_missing: bool = False
    attrs: dict = field(default_factory=dict)
    refs: list = field(default_factory=list)  # [{sha256,filename,ext,role,excluded}]
    card: dict = field(default_factory=dict)
    embedding_text: str = ""
    flags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "display": self.display,
            "kb_folder": self.kb_folder,
            "kb_missing": self.kb_missing,
            "attrs": self.attrs,
            "refs": self.refs,
            "card": self.card,
            "embedding_text": self.embedding_text,
            "flags": self.flags,
        }


def collect(folder: Path):
    """返回 [(ext, filename, path), ...]，按名排序。"""
    items = []
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() in IMG_EXT:
            items.append((f.suffix.lower(), f.name, f))
    return items


def skeleton_record(folder_name: str, items) -> SkuRecord:
    p = naming.parse(folder_name)
    rec = SkuRecord(
        id=folder_name,
        display=folder_name,
        kb_folder=folder_name,
        attrs={"volume_ml": p["volume_ml"], "sugar": p["sugar"], "flavor_core": naming.match_key(folder_name)[2]},
    )
    for ext, name, _path in items:
        rec.refs.append(
            {
                "sha256": "",
                "filename": name,
                "ext": ext,
                "role": "single_plain_rotation" if ext in JPG else "standard_unknown",
                "excluded": False,
            }
        )
    return rec
