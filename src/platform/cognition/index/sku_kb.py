"""SKU `.kb` Domain Retriever 适配（Task 8）。

`.kb/`（training-data/processed/knowledge-base）是 FMCG 识别域专用
索引，只作为独立 retriever 接入联邦检索面；其数据**永不写入**企业
KB 事实表（cognition_* 表），也不得与企业 KB 混索引（00 审计 §4、
05 Task 8）。V1 为只读 stub：kb_dir 未配置/不存在时诚实返回空。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..context import CognitiveContext


class SkuKbDomainRetriever:
    def __init__(self, store: Any, *, kb_dir: Path | str | None) -> None:
        self.store = store
        self.kb_dir = Path(kb_dir) if kb_dir else None

    def available(self) -> bool:
        return bool(self.kb_dir and self.kb_dir.exists())

    def search(self, query: str, ctx: CognitiveContext
               ) -> list[dict[str, Any]]:
        """只读检索；不写任何 DB 表（评审隔离断言）。"""
        if not self.available():
            return []
        entries_file = self.kb_dir / "entries.json"
        if not entries_file.exists():
            return []
        try:
            entries = json.loads(entries_file.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return []
        q = (query or "").strip().lower()
        out = []
        for e in entries:
            blob = f"{e.get('sku_id', '')} {e.get('name', '')} " \
                   f"{e.get('description', '')}".lower()
            if q and q in blob:
                out.append({"target_kind": "external",
                            "domain": "sku_kb",
                            "target_id": str(e.get("sku_id", "")),
                            "summary": str(e.get("name", "")),
                            "_origin": ".kb", "_writable": False})
        return out
