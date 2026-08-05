"""U3-3：SHA 精确去重 + pHash 近重复分组（只读台账 + 只读图片）。

口径（手册 §5.2 / 指令）：
- SHA 精确去重：台账 GROUP BY sha256；重复组保留全部 source reference，
  不删除任何台账行（台账本身不可变）。
- pHash 近重复：仅对有本地文件的 directory 来源做 DCT-pHash（自实现，
  不新增依赖），按唯一文件扫描（同 SHA/同路径多条引用只扫一次），
  汉明距离 ≤ threshold 归一组（union-find）。
- download_failed：台账中 sha256 为空的行（manifest ok=false 下载失败项）。
- 报告必须声明唯一数口径：禁止把目录数量相加冒充唯一照片总数。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def sha_dedupe(store) -> dict[str, Any]:
    """SHA 精确去重：返回 total_refs/unique_sha/exact_dup_groups/groups。"""
    rows = store._conn.execute(
        "SELECT asset_id, source_id, source_uri, photo_id, sha256"
        " FROM source_asset_inventory_v1 ORDER BY asset_id").fetchall()
    by_sha: dict[str, list[dict[str, Any]]] = {}
    empty = 0
    for r in rows:
        sha = r["sha256"]
        if not sha:
            empty += 1
            continue
        by_sha.setdefault(sha, []).append({
            "asset_id": r["asset_id"], "source_id": r["source_id"],
            "source_uri": r["source_uri"], "photo_id": r["photo_id"],
        })
    groups = [
        {"sha256": sha, "count": len(ms), "members": ms}
        for sha, ms in sorted(by_sha.items()) if len(ms) > 1
    ]
    return {
        "total_refs": len(rows),
        "unique_sha": len(by_sha),
        "rows_without_sha": empty,
        "exact_dup_groups": len(groups),
        "groups": groups,
    }


def phash64(path: Path, hash_size: int = 8, highfreq_factor: int = 4) -> int:
    """DCT-pHash（imagehash 同构口径），返回 64 位整数。"""
    import numpy as np
    from PIL import Image
    from scipy.fftpack import dct

    size = hash_size * highfreq_factor
    img = Image.open(path).convert("L").resize((size, size),
                                               Image.Resampling.LANCZOS)
    px = np.asarray(img, dtype=np.float64)
    coeffs = dct(dct(px, axis=0, norm="ortho"), axis=1, norm="ortho")
    low = coeffs[:hash_size, :hash_size]
    med = float(np.median(low))
    bits = (low > med).flatten()
    v = 0
    for b in bits:
        v = (v << 1) | int(b)
    return v


def _hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def group_near_duplicates(store, root: Path,
                          threshold: int = 8) -> dict[str, Any]:
    """对 directory 来源的本地文件做 pHash 近重复分组（按唯一文件）。"""
    rows = store._conn.execute(
        "SELECT asset_id, source_id, source_uri"
        " FROM source_asset_inventory_v1"
        " WHERE source_type='directory' AND source_uri NOT LIKE '%#%'"
        " ORDER BY asset_id").fetchall()
    # 按 source_uri 去重：同一文件的多条来源引用只扫描一次
    uniq: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        uniq.setdefault(r["source_uri"], []).append({
            "asset_id": r["asset_id"], "source_id": r["source_id"],
            "source_uri": r["source_uri"],
        })
    uris = sorted(uniq)
    hashes: list[int | None] = []
    for uri in uris:
        p = root / uri
        try:
            hashes.append(phash64(p) if p.is_file() else None)
        except Exception:
            hashes.append(None)
    # union-find
    parent = list(range(len(uris)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    idx = [i for i, h in enumerate(hashes) if h is not None]
    for a in range(len(idx)):
        for b in range(a + 1, len(idx)):
            if _hamming(hashes[idx[a]], hashes[idx[b]]) <= threshold:  # type: ignore[arg-type]
                union(idx[a], idx[b])
    comps: dict[int, list[int]] = {}
    for i in idx:
        comps.setdefault(find(i), []).append(i)
    groups = []
    for members_idx in sorted(comps.values(), key=lambda m: uris[m[0]]):
        members = [m for i in members_idx for m in uniq[uris[i]]]
        groups.append({
            "group_id": "nd-" + members[0]["asset_id"][:12],
            "size": len(members_idx),
            "members": members,
        })
    return {
        "scanned": len(idx),
        "threshold_hamming": threshold,
        "groups": groups,
        "near_dup_groups": sum(1 for g in groups if g["size"] > 1),
    }


def build_dedup_report(store, root: Path,
                       threshold: int = 8) -> dict[str, Any]:
    """汇总去重报告：原始引用数/SHA 唯一数/精确重复组/近重复组/下载失败。"""
    exact = sha_dedupe(store)
    near = group_near_duplicates(store, root, threshold=threshold)
    return {
        "raw_refs": exact["total_refs"],
        "unique_sha": exact["unique_sha"],
        "rows_without_sha": exact["rows_without_sha"],
        "exact_dup_groups": exact["exact_dup_groups"],
        "near_dup_groups": near["near_dup_groups"],
        "near_dup_scanned": near["scanned"],
        "threshold_hamming": threshold,
        "download_failed": exact["rows_without_sha"],
        "groups_exact": exact["groups"],
        "groups_near": near["groups"],
        "note": ("unique_sha 为 SHA 精确去重后的唯一照片数；"
                 "近重复组仅覆盖有本地文件的 directory 来源，"
                 "manifest-only 来源的近重复需后续 embedding；"
                 "禁止把目录数量相加冒充唯一照片总数"),
    }
