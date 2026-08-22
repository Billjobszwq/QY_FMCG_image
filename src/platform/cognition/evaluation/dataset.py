"""金标准数据集加载（Task 12 / 03 §9.1）。

gold_queries.jsonl 每行一条样本：
  id, class（exact_rule/paraphrase/temporal/conflict/insufficient/acl/
  injection/skill/l2/l3）, query, mode, expect_knowledge_ids（期望命中的
  knowledge_id 列表）, expect_abstain（bool）, expect_empty_for_customer
  （ACL 负例：该客户上下文应零命中）, expect_quote_contains（期望片段子串）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GOLD_CLASSES = ("exact_rule", "paraphrase", "temporal", "multi_hop",
                "global", "conflict", "insufficient", "acl", "injection",
                "skill", "l2_case", "l3_methodology")


@dataclass(frozen=True)
class GoldQuery:
    id: str
    cls: str
    query: str
    mode: str = "lookup"
    polarity: str = "positive"           # positive / negative
    target_kinds: tuple[str, ...] = ("knowledge",)
    as_of: str = ""                      # ISO 时间（时间有效性样本）
    scope: dict[str, Any] = field(default_factory=dict)
    expect_knowledge_ids: list[str] = field(default_factory=list)
    expect_target_ids: list[str] = field(default_factory=list)
    expect_abstain: bool = False
    expect_empty_for_customer: str | None = None
    expect_conflict: bool | None = None
    expect_quote_contains: str | None = None
    forbidden_source_ids: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


# 已建模为一等字段的键（其余进 extra）
_KNOWN_KEYS = ("id", "query", "mode", "polarity", "target_kinds",
               "as_of", "scope", "expect_knowledge_ids",
               "expect_target_ids", "expect_abstain",
               "expect_empty_for_customer", "expect_conflict",
               "expect_quote_contains", "forbidden_source_ids")


def load_gold(path: Path | str) -> list[GoldQuery]:
    p = Path(path)
    out: list[GoldQuery] = []
    seen_ids: set[str] = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        d = json.loads(line)
        cls = d.get("class", "exact_rule")
        if cls not in GOLD_CLASSES:
            raise ValueError(
                f"gold 样本 class 非法（{cls}），必须属于 {GOLD_CLASSES}")
        sid = d.get("id", f"g{len(out)}")
        if sid in seen_ids:
            raise ValueError(f"gold 样本 id 重复（fail-closed）: {sid}")
        seen_ids.add(sid)
        known = {k: d[k] for k in _KNOWN_KEYS if k in d}
        extra = {k: v for k, v in d.items()
                 if k not in known and k not in ("class", "id")}
        out.append(GoldQuery(
            id=sid,
            cls=cls,
            query=known.get("query", ""),
            mode=known.get("mode", "lookup"),
            polarity=known.get("polarity", "positive"),
            target_kinds=tuple(known.get("target_kinds", ["knowledge"])),
            as_of=known.get("as_of", ""),
            scope=dict(known.get("scope", {})),
            expect_knowledge_ids=list(known.get("expect_knowledge_ids", [])),
            expect_target_ids=list(known.get("expect_target_ids", [])),
            expect_abstain=bool(known.get("expect_abstain", False)),
            expect_empty_for_customer=known.get("expect_empty_for_customer"),
            expect_conflict=known.get("expect_conflict"),
            expect_quote_contains=known.get("expect_quote_contains"),
            forbidden_source_ids=list(known.get("forbidden_source_ids", [])),
            extra=extra))
    return out


def gold_content_hash(path: Path | str) -> str:
    """gold fixture 内容哈希（绑定进报告，供 Gate freshness 复核；
    只用于绑定，不得被 provider 读取做特化）。"""
    import hashlib
    return hashlib.sha256(
        Path(path).read_bytes()).hexdigest()
