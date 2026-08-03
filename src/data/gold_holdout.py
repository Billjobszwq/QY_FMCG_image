"""RA-002：冻结 gold holdout 数据协议。

原则：
- 以 门店(scode)+采集日期 为 group 做分组切分（同门店同日连拍必同侧）
- gold 照片永不参与：crop 生成、阈值搜索、hard-negative mining、返修训练
- 一旦创建即冻结；重建必须显式 --force 并生成新文件（旧文件归档）
- 所有训练数据构建器必须先调用 check_no_leak，泄漏即抛异常（fail-closed）

CLI：python -m src.data.gold_holdout {create|status|check-photo <id,...>}"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT

PROTOCOL_DIR = PROJECT_ROOT / ".data_protocol"
GOLD_FILE = PROTOCOL_DIR / "gold_holdout.json"
B2_MANIFEST = PROJECT_ROOT / ".eval" / "batch2" / "manifest.json"
DEFAULT_RATIO = 0.15
DEFAULT_SEED = 20260804


def _group_key(p: dict) -> str:
    meta = p.get("meta") or {}
    scode = str(meta.get("scode", "NA"))
    day = str(meta.get("createtime", ""))[:10]
    return f"{scode}|{day}"


def load_gold() -> dict | None:
    if not GOLD_FILE.exists():
        return None
    return json.loads(GOLD_FILE.read_text(encoding="utf-8"))


def gold_photo_ids() -> set[str]:
    g = load_gold()
    return set(g.get("photo_ids", [])) if g else set()


def gold_shas() -> set[str]:
    g = load_gold()
    return set(g.get("sha256", [])) if g else set()


def check_no_leak(photo_ids, shas=None, context: str = "") -> None:
    """训练数据构建器必须调用：与 gold 有任何交集即抛异常。"""
    gids = gold_photo_ids()
    if not gids:
        return  # 尚未建立 gold 时不阻断（create 后所有构建自动受控）
    leak = set(map(str, photo_ids)) & gids
    if shas:
        leak_sha = set(shas) & gold_shas()
        if leak_sha:
            raise RuntimeError(f"[gold-holdout] SHA 泄漏 {len(leak_sha)} 张 ({context})，gold 永不进训练")
    if leak:
        raise RuntimeError(f"[gold-holdout] 照片泄漏 {len(leak)} 张 ({context})，gold 永不进训练: {sorted(leak)[:5]}")


def create_gold(manifest_path: Path = B2_MANIFEST, ratio: float = DEFAULT_RATIO,
                seed: int = DEFAULT_SEED, force: bool = False) -> dict:
    """按 (门店,日期) 分组随机选取 ~ratio 照片冻结为 gold。已冻结时非 force 拒绝。"""
    if GOLD_FILE.exists() and not force:
        raise RuntimeError(f"gold holdout 已冻结: {GOLD_FILE}。重建需显式 --force（旧文件将归档）")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    photos = manifest["photos"]
    groups: dict[str, list[str]] = {}
    for pid, p in photos.items():
        groups.setdefault(_group_key(p), []).append(str(pid))

    rng = random.Random(seed)
    gkeys = sorted(groups.keys())
    rng.shuffle(gkeys)
    target = int(len(photos) * ratio)
    selected_groups, selected_ids, n = [], [], 0
    for gk in gkeys:
        if n >= target:
            break
        selected_groups.append(gk)
        selected_ids.extend(groups[gk])
        n += len(groups[gk])

    sha_map = {str(pid): (photos[pid].get("image") or {}).get("sha256")
               for pid in selected_ids}
    record = {
        "frozen": True,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seed": seed, "ratio": ratio,
        "source_manifest": str(manifest_path),
        "n_photos_total": len(photos),
        "n_groups_total": len(gkeys),
        "n_groups_gold": len(selected_groups),
        "n_photos_gold": len(selected_ids),
        "groups": selected_groups,
        "photo_ids": sorted(selected_ids),
        "sha256": sorted([s for s in sha_map.values() if s]),
    }
    if GOLD_FILE.exists() and force:
        backup = PROTOCOL_DIR / f"gold_holdout_{time.strftime('%Y%m%d%H%M%S')}.bak.json"
        GOLD_FILE.replace(backup)
        print(f"  旧 gold 已归档: {backup}")
    PROTOCOL_DIR.mkdir(parents=True, exist_ok=True)
    GOLD_FILE.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        GOLD_FILE.chmod(0o444)  # 只读防篡改
    except Exception:
        pass
    return record


def status() -> dict:
    g = load_gold()
    if not g:
        return {"exists": False}
    return {"exists": True, "frozen": g.get("frozen"), "created_at": g.get("created_at"),
            "n_photos_gold": g.get("n_photos_gold"), "n_groups_gold": g.get("n_groups_gold"),
            "n_photos_total": g.get("n_photos_total"), "ratio": g.get("ratio"), "seed": g.get("seed")}


def main():
    ap = argparse.ArgumentParser(description="gold holdout 数据协议（RA-002）")
    ap.add_argument("action", choices=["create", "status", "check-photo"])
    ap.add_argument("--ratio", type=float, default=DEFAULT_RATIO)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--photo-ids", default="")
    a = ap.parse_args()
    if a.action == "create":
        r = create_gold(ratio=a.ratio, seed=a.seed, force=a.force)
        print(json.dumps({k: r[k] for k in ("n_photos_gold", "n_groups_gold", "n_photos_total")}, ensure_ascii=False))
    elif a.action == "status":
        print(json.dumps(status(), ensure_ascii=False, indent=2))
    elif a.action == "check-photo":
        ids = [x for x in a.photo_ids.split(",") if x]
        try:
            check_no_leak(ids, context="cli-check")
            print("无泄漏")
        except RuntimeError as e:
            print(e)
            sys.exit(1)


if __name__ == "__main__":
    main()
