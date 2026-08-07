"""N2 Task 3：三批资产接入与精确去重（02 设计 §2）。

canonical 规则（冻结）：
1. 第一/二批精确重复（SHA）优先采用第二批坐标版本；
2. 第一批仅补独有照片；
3. 第三批独立纳入（与一/二批精确重叠为 0）；
4. 坐标不一致写 coordinate_discrepancies ledger（保留双份引用）；
5. 缺 SHA 的引用 fail-closed（不得静默纳入）。
"""
from __future__ import annotations

from typing import Any


class AssetScopeError(RuntimeError):
    """资产范围构建错误（fail-closed）。"""


def _points(photo: dict[str, Any]) -> list[dict[str, Any]]:
    a = photo.get("annotations")
    if isinstance(a, str):
        a = eval(a) if a.strip() else []  # noqa: S307 - 本地 manifest 历史格式
    return list(a or [])


def _sha(photo: dict[str, Any]) -> str:
    img = photo.get("image") or {}
    if isinstance(img, str):
        img = eval(img) if img.strip() else {}  # noqa: S307
    return img.get("sha256") or ""


def build_asset_scope(batches: dict[str, list[dict[str, Any]]]
                      ) -> dict[str, Any]:
    """构建 canonical 资产范围。

    batches: {"batch1": [...], "batch2": [...], "batch3": [...]}
    每个 photo: {id, image:{sha256}, annotations:[{x,y,name,...}]}
    """
    canonical: dict[str, dict[str, Any]] = {}
    discrepancies: list[dict[str, Any]] = []
    priority = ("batch2", "batch1", "batch3")  # 批2 优先；批1 补独有；批3 独立

    # 先按批收集 sha -> photos
    by_batch: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for bname, photos in batches.items():
        m: dict[str, list[dict[str, Any]]] = {}
        for p in photos:
            s = _sha(p)
            if not s:
                raise AssetScopeError(
                    f"photo {p.get('id')} 缺 sha256（fail-closed）")
            m.setdefault(s, []).append(p)
        by_batch[bname] = m

    all_shas: set[str] = set()
    for m in by_batch.values():
        all_shas |= set(m)

    for s in sorted(all_shas):
        chosen = None
        for bname in priority:
            if s in by_batch.get(bname, {}):
                # 批1 只补独有：若批2 也有，跳过批1
                if bname == "batch1" and s in by_batch.get("batch2", {}):
                    continue
                chosen = bname
                break
        if chosen is None:
            raise AssetScopeError(f"sha {s[:16]} 无可选来源")
        photo = by_batch[chosen][s][0]
        canonical[s] = {
            "photo_sha256": s,
            "photo_id": str(photo.get("id")),
            "source_batch": chosen,
            "points": _points(photo),
            "meta": photo.get("meta") or {},
        }
        # 差异 ledger：批1 与批2 同 sha 但坐标不同
        if s in by_batch.get("batch1", {}) and s in by_batch.get("batch2", {}):
            p1 = _points(by_batch["batch1"][s][0])
            p2 = _points(by_batch["batch2"][s][0])
            if sorted(map(str, p1)) != sorted(map(str, p2)):
                discrepancies.append({
                    "photo_sha256": s,
                    "batch1_photo_id": str(by_batch["batch1"][s][0].get("id")),
                    "batch2_photo_id": str(by_batch["batch2"][s][0].get("id")),
                    "batch1_points": len(p1),
                    "batch2_points": len(p2),
                    "canonical_choice": "batch2"})

    return {
        "exact_unique": len(canonical),
        "canonical_photos": canonical,
        "coordinate_discrepancies": discrepancies,
        "batch_counts": {b: len(ps) for b, ps in batches.items()},
    }


def canonical_points(scope: dict[str, Any]) -> int:
    return sum(len(p["points"]) for p in scope["canonical_photos"].values())
