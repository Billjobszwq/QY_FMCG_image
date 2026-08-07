"""Canonical photo identity：photo_id → sha256 的唯一权威配对途径（PLC3-001）。

背景（P0，2026-08-07）：diagnostic_v1.json 把 photo_ids 与 sha256 各自独立
排序保存，下游按数组位置 zip 造成 2/500、队列 0/250 的 ID/SHA 错配。
本模块锁定：**任何配对都必须按 photo_id 从权威 manifest 查询 sha256**，
禁止位置 zip；导入前逐条校验，错一条 fail-closed。

权威源：.batch3_clean/clean_manifest.json（photo_id → sha256/width/height/filename）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ..common.config import PROJECT_ROOT

PROTOCOL_DIR = PROJECT_ROOT / ".data_protocol"
CLEAN_MANIFEST = PROJECT_ROOT / ".batch3_clean" / "clean_manifest.json"


class IdentityError(Exception):
    """photo identity 链错误（manifest 缺 ID、配对错配、fail-closed 拒绝）。"""


def _load_manifest(manifest_path: Path | str | None) -> dict[str, dict]:
    p = Path(manifest_path) if manifest_path else CLEAN_MANIFEST
    if not p.is_file():
        raise IdentityError(f"权威 manifest 不存在: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def canonical_mapping(photo_ids: Iterable[str],
                      manifest_path: Path | str | None = None) -> dict[str, str]:
    """按 photo_id 从权威 manifest 查询 sha256；任一 ID 缺失即 fail-closed。"""
    manifest = _load_manifest(manifest_path)
    out: dict[str, str] = {}
    missing: list[str] = []
    for pid in photo_ids:
        pid = str(pid)
        rec = manifest.get(pid)
        sha = rec.get("sha256") if isinstance(rec, dict) else None
        if not sha:
            missing.append(pid)
            continue
        out[pid] = sha
    if missing:
        raise IdentityError(
            f"manifest 缺少 {len(missing)} 个 photo_id 的 sha256（fail-closed）: "
            f"{missing[:5]}{'...' if len(missing) > 5 else ''}")
    return out


def validate_pairing(pairs: Iterable[tuple[str, str]], *,
                     manifest_path: Path | str | None = None) -> dict[str, Any]:
    """逐条校验 (photo_id, sha256) 配对是否与权威 manifest 一致。

    用于检测历史"独立排序数组按位置 zip"造成的错配；任何 mismatch 都会
    令 ok=False（fail-closed），调用方不得继续导入/发布。"""
    manifest = _load_manifest(manifest_path)
    checked = correct = 0
    mismatches: list[dict[str, str]] = []
    for pid, sha in pairs:
        pid = str(pid)
        checked += 1
        rec = manifest.get(pid)
        actual = rec.get("sha256") if isinstance(rec, dict) else None
        if actual == sha:
            correct += 1
        else:
            mismatches.append({"photo_id": pid, "declared": str(sha),
                               "actual": str(actual)})
    return {"ok": checked > 0 and correct == checked,
            "checked": checked, "correct": correct,
            "mismatches": len(mismatches),
            "first_mismatches": mismatches[:10]}


def validate_queue_items(items: Iterable[dict], *,
                         manifest_path: Path | str | None = None) -> dict[str, Any]:
    """队列导入前门禁：逐条 actual_sha(photo_id)==declared_sha256。

    错一条即 fail-closed，不允许部分导入（allow_partial_import 恒 False）。"""
    report = validate_pairing(
        ((it.get("photo_id"), it.get("sha256")) for it in items),
        manifest_path=manifest_path)
    report["allow_partial_import"] = False
    return report


def canonical_assets(manifest_path: Path | str | None = None) -> dict[str, Any]:
    """同 SHA 多 photo_id 的 canonical asset 分组（确定性 + 别名证据）。

    canonical_photo_id 取组内最小 photo_id（字典序，确定性）；其余为别名，
    证据保留各别名 filename，便于追溯同内容重复登记。"""
    manifest = _load_manifest(manifest_path)
    by_sha: dict[str, list[str]] = {}
    for pid, rec in manifest.items():
        sha = rec.get("sha256") if isinstance(rec, dict) else None
        if sha:
            by_sha.setdefault(sha, []).append(str(pid))
    out: dict[str, dict] = {}
    for sha, pids in by_sha.items():
        pids = sorted(set(pids))
        canonical = pids[0]
        out[sha] = {
            "canonical_photo_id": canonical,
            "alias_photo_ids": pids,
            "evidence": {p: manifest[p].get("filename", "") for p in pids},
        }
    return {"by_sha": out, "n_sha": len(out),
            "n_duplicated_sha": sum(1 for g in out.values()
                                    if len(g["alias_photo_ids"]) > 1)}
