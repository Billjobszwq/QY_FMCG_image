"""结构化 chunking（Task 5）。

Markdown：按标题层级维护 heading_path；正文块保留精确 char_start/
char_end（必须满足 content[char_start:char_end] == chunk text，
保证 chunk 可回到原始 locator，02 §2）。
"""
from __future__ import annotations

import hashlib
from typing import Any


def _token_estimate(text: str) -> int:
    return max(1, len(text) // 2)


def chunk_markdown(content: str) -> list[dict[str, Any]]:
    """按标题/段落切分；返回含精确字符偏移的 chunk 列表。"""
    chunks: list[dict[str, Any]] = []
    headings: list[tuple[int, str]] = []  # (level, title)
    lines = content.split("\n")
    pos = 0
    block_start: int | None = None
    block_end: int | None = None

    def flush() -> None:
        nonlocal block_start, block_end
        if block_start is not None and block_end is not None \
                and block_end > block_start:
            text = content[block_start:block_end]
            if text.strip():
                path = [t for _, t in headings]
                chunks.append({
                    "text": text,
                    "char_start": block_start,
                    "char_end": block_end,
                    "heading_path": path,
                    "token_count": _token_estimate(text),
                    "content_hash": hashlib.sha256(
                        text.encode("utf-8")).hexdigest(),
                })
        block_start = None
        block_end = None

    for line in lines:
        stripped = line.strip()
        is_heading = stripped.startswith("#") and stripped.lstrip(
            "#").strip() != ""
        if is_heading:
            flush()
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped.lstrip("#").strip()
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, title))
        elif stripped == "":
            flush()
        else:
            if block_start is None:
                block_start = pos
            block_end = pos + len(line)
        pos += len(line) + 1  # + '\n'
    flush()
    for i, c in enumerate(chunks):
        c["ordinal"] = i
    return chunks


def chunk_plain_text(content: str) -> list[dict[str, Any]]:
    """纯文本：单个 chunk 覆盖全文（保留精确偏移）。"""
    text = content.strip()
    start = content.find(text) if text else 0
    c = {
        "text": text,
        "char_start": start,
        "char_end": start + len(text),
        "heading_path": [],
        "token_count": _token_estimate(text),
        "content_hash": hashlib.sha256(
            text.encode("utf-8")).hexdigest(),
        "ordinal": 0,
    }
    return [c] if text else []
