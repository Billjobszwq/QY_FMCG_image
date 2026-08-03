"""数据协议集冻结：gold_v2 / dev_v1 / calibration_v1 / diagnostic_v1。

背景（复核报告 3.1）：旧 gold_holdout.json 的 977 张全部被当前 detector/classifier
训练数据见过，不能作为未见基准（降级为 legacy_regression_v1）。真正 gold-v2 必须
从未参与任何训练的新门店 batch3 数据中冻结。

四键隔离（任一违反即不合格）：
  1. 图片内容 SHA256 去重（含与 batch2 训练数据的跨批次去重）
  2. 精确门店码（filename 第 2 段）
  3. 归一化门店名称（与 batch2 训练门店名零交集）
  4. 采集会话 —— 按门店整组分配，同门店照片必进同一集合

用法：
  python -m src.data.protocol_sets status
  python -m src.data.protocol_sets freeze [--seed 20260804] [--dry-run]
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ..common.config import PROJECT_ROOT
from ..data.store_norm import norm_store as _norm_store_canon
from ..data.store_norm import session_of_filename, store_of_filename

PROTOCOL_DIR = PROJECT_ROOT / ".data_protocol"
CLEAN_MANIFEST = PROJECT_ROOT / ".batch3_clean" / "clean_manifest.json"
GRAY_MANIFEST = PROJECT_ROOT / "batch3_gray" / "gray_manifest.json"
B2_MANIFEST = PROJECT_ROOT / ".eval" / "batch2" / "manifest.json"
REGISTRY = PROJECT_ROOT / "data" / "sku_registry.json"
V6_DIR = PROJECT_ROOT / ".datasets" / "sku_v6"
LEGACY_GOLD = PROTOCOL_DIR / "gold_holdout.json"

# 集合规模（照片数）：完整覆盖与门店隔离优先，规模不是机械目标
SET_BUDGETS = [
    ("diagnostic_v1", 500, "只做诊断，不做训练"),
    ("gold_v2", 1200, "最终一次性发布评估，禁止训练和日常调参"),
    ("calibration_v1", 400, "温度缩放/阈值/risk-coverage 校准"),
    ("dev_v1", 800, "实验迭代和错误分析"),
]
GOLD_CLASS_TARGET = 60  # gold_v2 每个关键 SKU 目标实例数（数据允许时）
DEFAULT_SEED = 20260804


def _norm_store(name: str) -> str:
    # G4：统一收敛到 store_norm 的 canonical key（NFKC+标点+空白+casefold），
    # 旧实现只做 trim/casefold，漏掉中英文括号别名（dev_v1 有 2 例）。
    return _norm_store_canon(name)


def _store_of_filename(fn: str) -> str:
    return store_of_filename(fn)


def _load_annotations() -> dict:
    """第三批 xlsx → {photo_id: [names...]}（复用构建器解析逻辑）。"""
    from ..training.build_sku_v6_dataset import parse_batch3_annotations
    anns = parse_batch3_annotations()
    return {pid: [a["name"] for a in v] for pid, v in anns.items()}


def _used_training_stores_and_shas() -> tuple[set, set, set]:
    """已被当前模型训练使用的门店名/SHA/photo_id（全部排除）。"""
    stores, shas, pids = set(), set(), set()
    # batch2（v4 detector + R2 classifier 的训练源）
    if B2_MANIFEST.exists():
        m = json.loads(B2_MANIFEST.read_text(encoding="utf-8"))
        for pid, p in m.get("photos", {}).items():
            meta = p.get("meta") or {}
            if meta.get("sname"):
                stores.add(_norm_store(meta["sname"]))
            sha = (p.get("image") or {}).get("sha256")
            if sha:
                shas.add(sha)
            pids.add(str(pid))
    # 当前 sku_v6 已选 batch3 照片（旧制品）
    if V6_DIR.exists():
        for img in V6_DIR.glob("images/*/b3_*.jpg"):
            seg = img.stem.split("_")
            if len(seg) >= 2:
                pids.add(seg[1])
    return stores, shas, pids


def _gold_class_stats(photo_ids, anns, registry) -> dict:
    counter = collections.Counter()
    for pid in photo_ids:
        for name in anns.get(pid, []):
            if name in registry:
                counter[registry[name]["class_id"]] += 1
    covered = len(counter)
    low = {c: n for c, n in counter.items() if n < GOLD_CLASS_TARGET}
    return {"classes_covered": covered, "n_classes_registry": len(registry),
            "classes_below_target": len(low), "min_class_instances": min(counter.values()) if counter else 0,
            "total_registered_instances": sum(counter.values())}


def freeze(seed: int = DEFAULT_SEED, dry_run: bool = False) -> dict:
    clean = json.loads(CLEAN_MANIFEST.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    gray_ids = set()
    if GRAY_MANIFEST.exists():
        gray_ids = set(json.loads(GRAY_MANIFEST.read_text(encoding="utf-8")).keys())

    print("[protocol] 解析第三批标注 ...")
    anns = _load_annotations()
    used_stores, used_shas, used_pids = _used_training_stores_and_shas()
    print(f"  训练已用: 门店 {len(used_stores)} | SHA {len(used_shas)} | 照片 {len(used_pids)}")

    # 候选：新门店 + 有注册类标注 + 非灰名单 + SHA 全局去重（四键 1/2/3）
    seen_sha, candidates, store_groups = set(), [], collections.defaultdict(list)
    rej = collections.Counter()
    for pid, rec in clean.items():
        pid = str(pid)
        if pid in gray_ids:
            rej["gray"] += 1
            continue
        if pid in used_pids:
            rej["used_pid"] += 1
            continue
        names = anns.get(pid, [])
        if not any(n in registry for n in names):
            rej["no_registered_label"] += 1
            continue
        store = _store_of_filename(rec.get("filename", ""))
        if _norm_store(store) in used_stores:
            rej["trained_store"] += 1
            continue
        sha = rec.get("sha256")
        if not sha or sha in used_shas or sha in seen_sha:
            rej["sha_dup_or_missing"] += 1
            continue
        seen_sha.add(sha)
        candidates.append(pid)
        store_groups[store].append(pid)
    print(f"  候选照片: {len(candidates)} / 新门店 {len(store_groups)} | 排除: {dict(rej)}")

    rng = random.Random(seed)
    stores = sorted(store_groups.keys())
    rng.shuffle(stores)

    assigned: dict[str, list] = {}   # set_name -> photo_ids
    used_groups: set = set()

    def take_stores(budget: int) -> list:
        sel = []
        for s in stores:
            if len(sel) >= budget:
                break
            if s in used_groups:
                continue
            sel.extend(store_groups[s])
            used_groups.add(s)
        return sel

    # diagnostic / calibration / dev：随机门店组填充
    for name, budget, _purpose in SET_BUDGETS:
        if name == "gold_v2":
            continue
        assigned[name] = take_stores(budget)

    # gold_v2：稀有类覆盖贪心 —— 优先吸收含稀有类实例的门店，再随机填充
    gold_have = collections.Counter()
    gold_ids: list = []

    def store_gain(s) -> int:
        g = 0
        for pid in store_groups[s]:
            for n in anns.get(pid, []):
                r = registry.get(n)
                if r and gold_have[r["class_id"]] < GOLD_CLASS_TARGET:
                    g += 1
        return g

    remaining = [s for s in stores if s not in used_groups]
    progress = True
    while len(gold_ids) < 1200 and progress:
        progress = False
        remaining = [s for s in remaining if s not in used_groups]
        # 有稀有类增益的门店优先
        with_gain = [s for s in remaining if store_gain(s) > 0]
        pick = with_gain[0] if with_gain else (remaining[0] if remaining else None)
        if pick is None:
            break
        for pid in store_groups[pick]:
            gold_ids.append(pid)
            for n in anns.get(pid, []):
                r = registry.get(n)
                if r:
                    gold_have[r["class_id"]] += 1
        used_groups.add(pick)
        progress = True
    assigned["gold_v2"] = gold_ids

    # 四键零交集审计（门店整组分配 ⇒ 会话隔离自动满足）
    all_ids = [pid for ids in assigned.values() for pid in ids]
    assert len(all_ids) == len(set(all_ids)), "集合间照片 ID 有交集"
    all_shas = [clean[pid]["sha256"] for pid in all_ids]
    assert len(all_shas) == len(set(all_shas)), "集合间 SHA 有交集"
    set_stores = {name: {_store_of_filename(clean[p]["filename"]) for p in ids}
                  for name, ids in assigned.items()}
    names_list = list(set_stores.keys())
    for i in range(len(names_list)):
        for j in range(i + 1, len(names_list)):
            a, b = names_list[i], names_list[j]
            assert not (set_stores[a] & set_stores[b]), f"门店交集: {a} vs {b}"
    print("  四键零交集审计: 通过（照片ID/SHA/门店/会话）")

    result = {}
    for name, budget, purpose in SET_BUDGETS:
        ids = assigned[name]
        rec = {
            "frozen": True,
            "role": name,
            "usage_policy": purpose,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seed": seed,
            "source": str(CLEAN_MANIFEST),
            "target_photos": budget,
            "n_photos": len(ids),
            "n_stores": len(set_stores[name]),
            "stores": sorted(set_stores[name]),
            "photo_ids": sorted(ids),
            "sha256": sorted(clean[p]["sha256"] for p in ids),
            "class_stats": _gold_class_stats(ids, anns, registry),
            "isolation": "store_group_split: 同门店照片必进同一集合；与 batch2 训练门店/SHA 零交集",
            "seen_by_current_model": False,
        }
        result[name] = rec
        print(f"  {name}: {len(ids)} 张 / {len(set_stores[name])} 门店"
              f" | 类覆盖 {rec['class_stats']['classes_covered']}/208")

    if not dry_run:
        PROTOCOL_DIR.mkdir(parents=True, exist_ok=True)
        for name, rec in result.items():
            fp = PROTOCOL_DIR / f"{name}.json"
            if fp.exists():
                raise RuntimeError(f"协议集已存在，拒绝覆盖: {fp}（协议只追加新版本）")
            fp.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                fp.chmod(0o444)
            except Exception:
                pass
        print(f"  已冻结写入 {PROTOCOL_DIR}（只读）")
    return result


def make_dev_v2(seed: int = DEFAULT_SEED, dry_run: bool = False) -> dict:
    """G4：发布 dev_v1 的追加修正版 dev_v2（不修改 dev_v1）。

    dev_v1 有 2 个门店经 Unicode/括号规范化后与 batch2 训练门店重叠
    （何惠晴(上海如海)、陈娟(承照便利店)），其照片全部移出，并从
    剩余新门店候选池按同口径补足到目标规模。dev_v2 声明 supersedes=
    dev_v1，守卫层据此把 dev_v1 降为仅报告。"""
    clean = json.loads(CLEAN_MANIFEST.read_text(encoding="utf-8"))
    dev1 = json.loads((PROTOCOL_DIR / "dev_v1.json").read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    # batch2 训练门店（canonical）
    b2_stores = set()
    if B2_MANIFEST.exists():
        m = json.loads(B2_MANIFEST.read_text(encoding="utf-8"))
        for p in m.get("photos", {}).values():
            sn = (p.get("meta") or {}).get("sname")
            if sn:
                b2_stores.add(_norm_store(sn))

    # 找出 dev_v1 中与 batch2 canonical 重叠的门店及照片
    bad_stores, bad_pids = set(), []
    for pid in dev1["photo_ids"]:
        fn = clean[str(pid)]["filename"]
        if _norm_store(_store_of_filename(fn)) in b2_stores:
            bad_stores.add(_store_of_filename(fn))
            bad_pids.append(str(pid))
    keep = [p for p in dev1["photo_ids"] if str(p) not in set(bad_pids)]
    print(f"[dev_v2] 移除重叠门店 {sorted(bad_stores)} / {len(bad_pids)} 张，保留 {len(keep)} 张")

    # 所有需排除的 canonical 门店：四协议集 + dev_v1 保留门店 + batch2
    exclude = set(b2_stores)
    for name in ("gold_v2", "calibration_v1", "diagnostic_v1"):
        rec = json.loads((PROTOCOL_DIR / f"{name}.json").read_text(encoding="utf-8"))
        exclude |= {_norm_store(s) for s in rec["stores"]}
    keep_stores = {_norm_store(_store_of_filename(clean[str(p)]["filename"])) for p in keep}
    exclude |= keep_stores
    used_shas = {clean[str(p)]["sha256"] for p in keep}
    for name in ("gold_v2", "calibration_v1", "diagnostic_v1"):
        rec = json.loads((PROTOCOL_DIR / f"{name}.json").read_text(encoding="utf-8"))
        used_shas |= set(rec["sha256"])
    if B2_MANIFEST.exists():
        for p in json.loads(B2_MANIFEST.read_text(encoding="utf-8")).get("photos", {}).values():
            sha = (p.get("image") or {}).get("sha256")
            if sha:
                used_shas.add(sha)

    # 从全量 clean 中找可补门店组（新门店 + 非灰 + 非协议 + SHA 不重）
    gray_ids = set()
    if GRAY_MANIFEST.exists():
        gray_ids = set(json.loads(GRAY_MANIFEST.read_text(encoding="utf-8")).keys())
    anns = _load_annotations()
    groups: dict = collections.defaultdict(list)
    seen_sha = set()
    for pid, recd in clean.items():
        pid = str(pid)
        if pid in gray_ids or pid in set(map(str, dev1["photo_ids"])):
            continue
        fn = recd.get("filename", "")
        st = _store_of_filename(fn)
        if _norm_store(st) in exclude:
            continue
        sha = recd.get("sha256")
        if not sha or sha in used_shas or sha in seen_sha:
            continue
        if not any(n in registry for n in anns.get(pid, [])):
            continue
        seen_sha.add(sha)
        groups[st].append(pid)

    rng = random.Random(seed)
    order = sorted(groups.keys())
    rng.shuffle(order)
    target = dev1.get("target_photos", 800)
    fill: list = []
    for st in order:
        if len(keep) + len(fill) >= target:
            break
        fill.extend(groups[st])
    ids = sorted(set(map(str, keep)) | set(fill))
    print(f"[dev_v2] 补充 {len(fill)} 张（{len({ _store_of_filename(clean[p]['filename']) for p in fill })} 门店）→ 总 {len(ids)}")

    stores = sorted({_store_of_filename(clean[p]["filename"]) for p in ids})
    sessions = sorted({session_of_filename(clean[p]["filename"]) for p in ids})
    # 自检：与 batch2 canonical 门店零交集
    assert not ({_norm_store(s) for s in stores} & b2_stores), "dev_v2 仍与 batch2 门店重叠"
    out = {
        "frozen": True,
        "role": "dev_v2",
        "supersedes": "dev_v1",
        "supersede_reason": "dev_v1 有 2 个门店经 NFKC/括号规范化后与 batch2 训练门店重叠（G4）",
        "removed_stores": sorted(bad_stores),
        "removed_photo_ids": sorted(bad_pids),
        "usage_policy": "实验迭代和错误分析（取代 dev_v1）",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seed": seed,
        "source": str(CLEAN_MANIFEST),
        "target_photos": target,
        "n_photos": len(ids),
        "n_stores": len(stores),
        "stores": stores,
        "sessions": sessions,
        "photo_ids": ids,
        "sha256": sorted(clean[p]["sha256"] for p in ids),
        "class_stats": _gold_class_stats(ids, anns, registry),
        "isolation": "store_group_split: 五键（ID/SHA/规范门店/别名/session）与全部 active 协议集及 batch2 零交集",
        "seen_by_current_model": False,
    }
    if not dry_run:
        fp = PROTOCOL_DIR / "dev_v2.json"
        if fp.exists():
            raise RuntimeError(f"dev_v2 已存在，拒绝覆盖: {fp}")
        fp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[dev_v2] 已写入 {fp}")
    return out


def status() -> dict:
    out = {}
    for f in sorted(PROTOCOL_DIR.glob("*.json")):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        out[f.name] = {"role": rec.get("role", ""), "frozen": rec.get("frozen"),
                       "n_photos": rec.get("n_photos") or rec.get("n_photos_gold"),
                       "created_at": rec.get("created_at")}
    return out


def main():
    ap = argparse.ArgumentParser(description="数据协议集冻结（gold_v2/dev/calibration/diagnostic）")
    ap.add_argument("action", choices=["freeze", "status", "dev_v2"])
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.action == "freeze":
        freeze(seed=a.seed, dry_run=a.dry_run)
    elif a.action == "dev_v2":
        make_dev_v2(seed=a.seed, dry_run=a.dry_run)
    else:
        print(json.dumps(status(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
