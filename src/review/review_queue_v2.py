"""review_queue_diag_v2 构建器（PLC3-003）：ID→SHA 一律按 photo_id 从权威
manifest 查询，禁止位置 zip；发布门禁任一失败即不发布。

设计保留（任务书§七，与 rq_v1 同分布）：
- 协议前 n_double（默认200）张 photo_ids 全部 double_review；
- 固定 seed 从全池盲抽 n_blind（默认50）张 blind_manual；
- 全部任务初始 status=pending，本模块从不生成框、从不伪造结果。

与 rq_v1 的唯一本质区别：sha256 不再来自协议数组位置 zip（P0 根因，
协议 2/500、队列 0/250 配对），而是 photo_identity.canonical_mapping
按 photo_id 查 clean_manifest.json；发布前还校验原图存在 + 现场 SHA。
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from ..data.photo_identity import canonical_mapping, validate_queue_items

BUILDER_VERSION = "rq2_builder_v1"
QUEUE_VERSION = "rq_v2"
PROTOCOL = "diagnostic_v1"
SUPERSEDES = "rq_v1"
BUILDER_PATH = Path(__file__).resolve()


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    return _hash_bytes(Path(path).read_bytes())


def _blob_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _item(pid: str, sha: str, mode: str) -> dict:
    return {
        "photo_id": str(pid),
        "sha256": sha,
        "review_mode": mode,
        "requires_second_review": True,
        "status": "pending",
        "annotator_1": None, "annotator_2": None, "arbiter": None,
        "final_box": None,
    }


def build_v2(*, protocol_path: Path | str, manifest_path: Path | str,
             blobs_dir: Path | str, seed: int, n_double: int = 200,
             n_blind: int = 50, verify_blobs: bool = True,
             git_commit: str = "") -> tuple[dict, dict, dict]:
    """构建 V2 审核队列，返回 (queue, audit, gates)。

    gates["ok"] 为 False 时调用方禁止发布（fail-closed）。
    """
    protocol_path = Path(protocol_path)
    manifest_path = Path(manifest_path)
    blobs_dir = Path(blobs_dir)
    errors: list[str] = []

    proto_bytes = protocol_path.read_bytes()
    proto = json.loads(proto_bytes)
    manifest_bytes = Path(manifest_path).read_bytes()
    photo_ids = [str(p) for p in proto["photo_ids"]]

    # 唯一权威配对途径：按 photo_id 查 manifest（缺失即 fail-closed 抛出）
    mapping = canonical_mapping(photo_ids, manifest_path=manifest_path)

    if len(photo_ids) < n_blind:
        raise ValueError(
            f"照片池 {len(photo_ids)} 张不足盲抽最低 {n_blind} 张，"
            f"fail-closed：不允许静默缩减盲审规模（手册§七）")
    n_double_eff = min(n_double, len(photo_ids))

    items = [_item(pid, mapping[pid], "double_review")
             for pid in photo_ids[:n_double_eff]]
    rng = random.Random(seed)
    blind_ids = sorted(rng.sample(sorted(photo_ids), n_blind))
    items += [_item(pid, mapping[pid], "blind_manual") for pid in blind_ids]

    pairing = validate_queue_items(items, manifest_path=manifest_path)

    # 发布门禁：按唯一照片校验 blob 存在与现场 SHA
    unique_pids = sorted({it["photo_id"] for it in items})
    n_unique = len(unique_pids)
    files_present = sha_verified = 0
    if verify_blobs:
        for pid in unique_pids:
            sha = mapping[pid]
            bp = blobs_dir / sha[:2] / sha
            if not bp.is_file():
                continue
            files_present += 1
            if _blob_sha256(bp) == sha:
                sha_verified += 1
    else:
        errors.append("verify_blobs=False：未做现场校验，禁止发布")

    gates = {
        "ok": (verify_blobs and files_present == n_unique
               and sha_verified == n_unique
               and pairing["ok"]
               and len(mapping) == len(photo_ids)),
        "files_present": files_present,
        "n_unique_photos": n_unique,
        "sha_verified": sha_verified,
        "mapping_recovered": len(mapping),
        "mapping_total": len(photo_ids),
    }

    audit: dict[str, Any] = {
        "builder_version": BUILDER_VERSION,
        "builder_hash": _file_sha256(BUILDER_PATH),
        "git_commit": git_commit,
        "protocol_hash": _hash_bytes(proto_bytes),
        "manifest_hash": _hash_bytes(manifest_bytes),
        "seed": seed,
        "mapping_hash": _hash_bytes(json.dumps(
            mapping, sort_keys=True).encode()),
        "tasks_hash": _hash_bytes(json.dumps(
            items, sort_keys=True, ensure_ascii=False).encode()),
        "n_tasks": len(items),
        "n_unique_photos": n_unique,
        "n_overlap_photos": len(items) - n_unique,
        "sha_verification": {
            "enabled": verify_blobs, "verified": sha_verified,
            "files_present": files_present, "total": n_unique,
            "mismatches": files_present - sha_verified,
        },
        "distribution": {
            "double_review": n_double_eff,
            "blind_manual": n_blind,
        },
        "errors": errors,
        "supersedes": SUPERSEDES,
        "pairing_correct": pairing["correct"],
    }

    queue = {
        "queue_version": QUEUE_VERSION,
        "protocol": PROTOCOL,
        "seed": seed,
        "n_double": n_double_eff,
        "n_blind": n_blind,
        "status": "awaiting_human_review",
        "items": items,
    }
    return queue, audit, gates


def write_v2(queue: dict, audit: dict, out_path: Path | str) -> Path:
    """原子写队列文件（含审计）；已存在则拒绝覆盖（不可变证据链）。"""
    out_path = Path(out_path)
    if out_path.exists() and out_path.stat().st_size > 0:
        raise FileExistsError(
            f"审核队列已存在，禁止覆盖: {out_path}（如需新版请换文件名）")
    doc = dict(queue)
    doc["audit"] = audit
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(out_path)
    return out_path
