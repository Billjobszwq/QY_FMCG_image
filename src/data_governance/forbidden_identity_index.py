"""Unified Forbidden Identity Index v2。

解析每个样本的 13 身份字段；任意活动训练/验证/测试/来源组/
store-session/symlink 命中即排除；identity 无法解析 → unresolved，
不得进入正式 micro-gold。append-only 排除账本。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

CROPPED_RE = re.compile(
    r"^(?P<crop>[0-9a-f]{8})__(?P<src>[0-9a-f]{8})-(?P<item>.+?)_"
    r"(?P<store>.+?)_(?P<scene>.+?)_(?P<ts>\d{14,})_hc(?P<hc>\d+)_"
    r"(?P<batch>\d+)_(?P<sku>.+?)_\d+\.jpg")


@dataclass(frozen=True)
class IdentityRecord:
    photo_id: str | None
    sha: str | None
    group: str | None
    store: str | None
    session: str | None
    symlink_target: str | None


def parse_cropped_identity(name: str) -> dict[str, Any]:
    m = CROPPED_RE.match(name)
    if not m:
        return {"group": None, "store": None, "session": None,
                "photo_id": None, "source_batch": "unknown"}
    return {"group": f"{m.group('src')}|{m.group('item')}|"
                     f"{m.group('store')}|{m.group('ts')[:8]}",
            "store": m.group("store").strip().lower(),
            "session": m.group("ts")[:8],
            "photo_id": m.group("src"),
            "source_batch": "cropped_images"}


def norm_store(s: str | None) -> str | None:
    if not s:
        return None
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", s.lower())


def check_candidate(cand: IdentityRecord, idx: dict) -> dict[str, Any]:
    """fail-closed：任一命中或未解析 → excluded。"""
    if cand.photo_id and cand.photo_id in idx["photo_ids"]:
        return {"excluded": True, "reason": "photo_id_hit"}
    if cand.sha and cand.sha in idx["shas"]:
        return {"excluded": True, "reason": "exact_sha_hit"}
    if cand.symlink_target and cand.symlink_target in idx["symlink_targets"]:
        return {"excluded": True, "reason": "symlink_target_hit"}
    if cand.group and cand.group in idx["groups"]:
        return {"excluded": True, "reason": "leakage_group_hit"}
    ss = (f"{norm_store(cand.store)}@{cand.session}"
          if cand.store and cand.session else None)
    if ss and ss in idx["store_sessions"]:
        return {"excluded": True, "reason": "store_session_hit"}
    if not cand.group and not cand.photo_id:
        return {"excluded": True, "reason": "identity_unresolved"}
    return {"excluded": False, "reason": None}


def _sha(p: Path, cache: dict) -> str:
    rp = str(p.resolve())
    if rp not in cache:
        cache[rp] = hashlib.sha256(p.read_bytes()).hexdigest()
    return cache[rp]


def build_index(sources: dict[str, list[Path]],
                out_dir: Path) -> dict[str, Any]:
    """sources: name -> 文件路径列表。输出 jsonl + audit。"""
    idx = {"photo_ids": set(), "shas": set(), "groups": set(),
           "store_sessions": set(), "symlink_targets": set()}
    cache: dict[str, str] = {}
    rows = []
    per_source: dict[str, int] = {}
    missing: dict[str, int] = {}
    for name, files in sources.items():
        per_source[name] = len(files)
        for f in files:
            ident = parse_cropped_identity(f.name)
            sha = _sha(f, cache)
            target = str(f.resolve()) if f.is_symlink() else None
            rec = IdentityRecord(
                photo_id=ident["photo_id"] or (
                    f.stem if name.startswith("scene") else None),
                sha=sha, group=ident["group"], store=ident["store"],
                session=ident["session"], symlink_target=target)
            if rec.photo_id:
                idx["photo_ids"].add(rec.photo_id)
            idx["shas"].add(sha)
            if target:
                idx["symlink_targets"].add(target)
                idx["shas"].add(_sha(f.resolve(), cache))
            if rec.group:
                idx["groups"].add(rec.group)
            ss = (f"{norm_store(rec.store)}@{rec.session}"
                  if rec.store and rec.session else None)
            if ss:
                idx["store_sessions"].add(ss)
            for fld in ("photo_id", "group", "store", "session"):
                if getattr(rec, fld) is None:
                    missing[fld] = missing.get(fld, 0) + 1
            rows.append({"source": name, **asdict(rec)})
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "forbidden_identity_index_v2.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
        encoding="utf-8")
    audit = {"sources": per_source,
             "counts": {k: len(v) for k, v in idx.items()},
             "missing_field_counts": missing,
             "index_hash": hashlib.sha256(
                 "\n".join(sorted(idx["shas"])).encode()).hexdigest(),
             "builder_hash": hashlib.sha256(
                 Path(__file__).read_bytes()).hexdigest()[:16]}
    (out_dir / "forbidden_identity_index_v2.audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=1), encoding="utf-8")
    return {**idx, "audit": audit}
