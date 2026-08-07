"""V2 zero-shot 方法（确定性纯函数）：分层采样 + 真实检索候选 + 真 top-k。

对 V1 的修正（用户指令第十节）：
- V1 采样"按文件名排序取前 N"导致 48 crop 只来自 2 张照片；
  V2 按门店/session/照片/SKU 分层轮转采样，确定性可复现；
- V1 候选 = gt + 干扰项（主动注入真值）；V2 候选必须来自真实检索
  链路（查询文本 → KB 向量检索），retrieve_candidates 签名上
  不接受任何 GT 参数（结构防线）；
- V1 top5 检查完整 K=8 列表；V2 recall@k 只检查真实 predicted
  ranking 的前 k 个，候选不足 k 时自然截断、不伪造。

红线：缺门店/session 元数据的照片不得混入分层采样（fail-closed，
只计入 photos_without_meta 报告）；分母为 0 的指标一律 None。
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

V2_SAMPLING_VERSION = "zeroshot-sampling.v2"


def parse_photo_rows(rows: Iterable[Sequence[Any]]) -> dict[str, dict]:
    """实景照片.xlsx 行 → photo_id → {store, store_code, session, photo_type}。

    行结构：(ID, SCode, SName, CreateTime, ItemName, TypeName, ...)。
    同一 photo_id 多行（每行一个标注框）取首次出现的门店/session。"""
    meta: dict[str, dict] = {}
    for row in rows:
        if row is None or len(row) < 6:
            continue
        photo_id, store_code, store, create_time = (
            row[0], row[1], row[2], row[3])
        if photo_id in (None, ""):
            continue
        key = str(photo_id)
        if key in meta:
            continue
        if hasattr(create_time, "strftime"):
            session = create_time.strftime("%Y-%m-%d")
        else:
            session = str(create_time or "")[:10]
        meta[key] = {
            "store": str(store or ""),
            "store_code": str(store_code or ""),
            "session": session,
            "photo_type": str(row[5] or ""),
        }
    return meta


def stratified_sample(
    regions: list[dict[str, Any]],
    photo_meta: Mapping[str, dict],
    *,
    limit: int,
    max_per_photo: int = 8,
    max_per_sku: int = 32,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """按门店/session/照片/SKU 分层的确定性采样。

    算法：合格照片（有元数据）按 (store, session, photo_id) 排序，
    轮转每轮每照片取 1 个区域（受 max_per_photo/max_per_sku 约束），
    直到取满 limit 或耗尽。同一输入必须产出同一结果。"""
    all_photos = {r["photo_id"] for r in regions}
    eligible = sorted((p for p in all_photos if p in photo_meta),
                      key=lambda p: (photo_meta[p]["store"],
                                     photo_meta[p]["session"], p))
    by_photo: dict[str, list[dict]] = {p: [] for p in eligible}
    for r in regions:
        if r["photo_id"] in by_photo:
            by_photo[r["photo_id"]].append(r)
    for p in eligible:
        by_photo[p].sort(key=lambda r: r.get("region_index", 0))

    pointers = {p: 0 for p in eligible}
    photo_cnt: Counter = Counter()
    sku_cnt: Counter = Counter()
    picked: list[dict] = []
    progress = True
    while len(picked) < limit and progress:
        progress = False
        for p in eligible:
            if len(picked) >= limit:
                break
            if photo_cnt[p] >= max_per_photo:
                continue
            arr, ptr = by_photo[p], pointers[p]
            while ptr < len(arr) and sku_cnt[arr[ptr]["gt"]] >= max_per_sku:
                ptr += 1
            pointers[p] = ptr + 1 if ptr < len(arr) else ptr
            if ptr < len(arr):
                r = arr[ptr]
                picked.append(r)
                photo_cnt[p] += 1
                sku_cnt[r["gt"]] += 1
                progress = True

    picked_photos = {r["photo_id"] for r in picked}
    report = {
        "sampling_version": V2_SAMPLING_VERSION,
        "limit": limit,
        "picked": len(picked),
        "n_photos": len(picked_photos),
        "n_stores": len({photo_meta[p]["store"] for p in picked_photos}),
        "n_sessions": len({photo_meta[p]["session"] for p in picked_photos}),
        "n_skus": len({r["gt"] for r in picked}),
        "photos_without_meta": len(all_photos - set(photo_meta)),
        "eligible_photos": len(eligible),
        "per_photo": dict(sorted(photo_cnt.items())),
    }
    return picked, report


def enumerate_regions(dataset_root) -> tuple[list[dict], dict[int, str]]:
    """轻量解析 val 标签 → 区域清单（不读图像像素）。

    返回 [{photo_id, cls, gt, box_norm:[cx,cy,w,h], region_index}], names。"""
    import yaml
    from pathlib import Path
    root = Path(dataset_root)
    data = yaml.safe_load((root / "data.yaml").read_text("utf-8"))
    names = list(data["names"])
    class_names = {i: n for i, n in enumerate(names)}
    lbl_dir = root / "labels" / "val"
    regions: list[dict] = []
    for lbl_path in sorted(lbl_dir.glob("*.txt")):
        for idx, line in enumerate(
                lbl_path.read_text("utf-8").splitlines()):
            parts = line.split()
            if len(parts) < 5:
                continue
            cls = int(parts[0])
            regions.append({
                "photo_id": lbl_path.stem,
                "cls": cls,
                "gt": class_names.get(cls, f"class_{cls}"),
                "box_norm": [float(v) for v in parts[1:5]],
                "region_index": idx,
            })
    return regions, class_names


def retrieve_candidates(
    query_text: str,
    *,
    embed_fn: Callable[[list[str]], Sequence[Sequence[float]]],
    kb_ids: Sequence[str],
    kb_vectors: np.ndarray,
    topk: int = 8,
) -> list[tuple[str, float]]:
    """真实候选检索：查询文本 → 向量 → KB 余弦排序 top-k。

    签名刻意不接受 GT/类别/真名参数——候选只允许来自检索链路
    （OCR/属性文本 + SKU KB），任何 GT 注入在结构上不可表达。
    返回按相似度降序的 (sku_id, similarity)，即真实 predicted ranking。"""
    qv = np.asarray(embed_fn([query_text])[0], dtype="float32")
    qv = qv / (np.linalg.norm(qv) + 1e-9)
    vec = np.asarray(kb_vectors, dtype="float32")
    nv = vec / (np.linalg.norm(vec, axis=1, keepdims=True) + 1e-9)
    sims = nv @ qv
    order = np.argsort(-sims, kind="stable")[: max(0, topk)]
    return [(str(kb_ids[i]), float(sims[i])) for i in order]
