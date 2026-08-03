"""SKU 别名 / 归一注册表。

canonical_id 为稳定主键；登记 KB 文件夹名、实景它模名、错字变体等所有别名。
resolve() 先精确查别名索引，再用归一匹配键兜底；无法解析返回 None。
别名冲突（同一字符串指向两个 canonical）在构建时直接抛错，绝不静默合并。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import naming


@dataclass
class Canonical:
    id: str
    display: str
    kb_folder: Optional[str]
    kb_missing: bool = False
    aliases: list[str] = field(default_factory=list)


class Registry:
    def __init__(self, canonicals: list[Canonical]):
        self.canonicals: dict[str, Canonical] = {c.id: c for c in canonicals}
        self._index: dict[str, str] = {}
        for c in canonicals:
            keys = {c.id, c.display, *c.aliases}
            if c.kb_folder:
                keys.add(c.kb_folder)
            for k in keys:
                if k in self._index and self._index[k] != c.id:
                    raise ValueError(f"别名冲突: {k!r} 同时指向 {self._index[k]} 与 {c.id}")
                self._index[k] = c.id

    def resolve(self, name: str) -> Optional[tuple[str, str]]:
        """返回 (canonical_id, method)，method in {exact, norm}；无法解析返回 None。"""
        if name in self._index:
            return self._index[name], "exact"
        mk = naming.match_key(name)
        hits = [
            cid
            for cid, c in self.canonicals.items()
            if naming.match_key(c.display) == mk or (c.kb_folder and naming.match_key(c.kb_folder) == mk)
        ]
        if len(hits) == 1:
            return hits[0], "norm"
        return None

    def coverage(self, names) -> dict:
        unresolved = [n for n in names if self.resolve(n) is None]
        return {"total": len(names), "resolved": len(names) - len(unresolved), "unresolved": unresolved}


def build_registry(kb_names, alias_data_path: Path, extra_names=None) -> Registry:
    data = json.loads(Path(alias_data_path).read_text(encoding="utf-8"))["canonicals"]
    by_kb: dict[str, Canonical] = {}
    canon: list[Canonical] = []
    for entry in data:
        kb = entry.get("kb_folder")
        disp = entry.get("display") or kb
        cid = kb or disp
        c = Canonical(
            id=cid,
            display=disp,
            kb_folder=kb,
            kb_missing=bool(entry.get("kb_missing")),
            aliases=list(entry.get("aliases", [])),
        )
        canon.append(c)
        if kb:
            by_kb[kb] = c
    for name in kb_names:
        if name not in by_kb:
            canon.append(Canonical(id=name, display=name, kb_folder=name, aliases=[name]))
    reg = Registry(canon)
    # 仍无法解析的额外名称（如真·新品）记为 kb_missing 占位，避免静默丢失标签
    for name in extra_names or []:
        if reg.resolve(name) is None:
            reg.canonicals[name] = Canonical(id=name, display=name, kb_folder=None, kb_missing=True, aliases=[name])
            reg._index[name] = name
    return reg
