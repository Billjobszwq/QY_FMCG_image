"""训练数据与冻结协议集的五键零泄漏守卫（G2 门禁）。

五键（任一交集非零即 fail-closed，legacy/被取代集仅报告）：
  1. photo ID
  2. 图片内容 SHA256
  3. 规范化门店（store_norm.norm_store，NFKC+标点+空白+casefold）
  4. 模糊别名（canonical key + ALIAS_TABLE，与 3 同键实现，显式披露）
  5. 采集会话（canonical 门店@采集日期）

规则：
  - role 以 legacy 开头：仅报告交集，不阻断（当前模型已见过）。
  - 声明了 supersedes 且自身被新版本取代的集（如 dev_v1 → dev_v2）：
    仅报告，不阻断。判定依据是目录内存在任一集声明 supersedes=该集名。
  - 其余 frozen=True 集：任何键交集非零即抛 RuntimeError。

协议集若未内嵌 stores/sessions（旧格式），从 photo_ids 经
clean_manifest 文件名推导，保证五键检查对全部历史集生效。
"""
from __future__ import annotations

import json
from pathlib import Path

from .store_norm import norm_store, session_of_filename, store_of_filename


def _derive_keys(photo_ids, clean: dict) -> tuple[set, set]:
    """从文件名推导协议集的 canonical 门店集与 session 集。"""
    stores, sessions = set(), set()
    for pid in photo_ids:
        fn = (clean.get(str(pid)) or {}).get("filename", "")
        if not fn:
            continue
        stores.add(norm_store(store_of_filename(fn)))
        sessions.add(session_of_filename(fn))
    return stores, sessions


def load_active_sets(protocol_dir: Path, clean: dict) -> tuple[dict, dict]:
    """返回 (active, reported)：name → {pids, shas, stores, sessions, role}。

    active：fail-closed 生效的冻结集；reported：legacy/被取代集（仅报告）。"""
    recs = {}
    for f in sorted(Path(protocol_dir).glob("*.json")):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(rec, dict) or not rec.get("frozen"):
            continue
        recs[f.stem] = (f, rec)

    superseded = {rec.get("supersedes") for _, rec in recs.values() if rec.get("supersedes")}
    active, reported = {}, {}
    for name, (f, rec) in recs.items():
        pids = set(map(str, rec.get("photo_ids", [])))
        stores = {norm_store(s) for s in rec.get("stores", [])}
        if not stores or not rec.get("sessions"):
            d_stores, d_sessions = _derive_keys(pids, clean)
            stores |= d_stores
            sessions = d_sessions if not rec.get("sessions") else set(rec["sessions"])
        else:
            sessions = set(rec.get("sessions", []))
        entry = {"file": str(f), "role": str(rec.get("role", "")),
                 "pids": pids, "shas": set(rec.get("sha256", [])),
                 "stores": stores, "sessions": sessions}
        if entry["role"].startswith("legacy") or name in superseded:
            reported[name] = entry
        else:
            active[name] = entry
    return active, reported


def check_no_leak(photo_ids, shas, stores_raw, sessions, clean: dict,
                  protocol_dir: Path, context: str) -> dict:
    """五键泄漏检查。交集非零（active 集）即抛 RuntimeError。

    返回 report: {set_name: {status, hits:{key: count}}}，调用方必须
    写入 build_audit。"""
    ids = set(map(str, photo_ids or ()))
    ssh = {s for s in (shas or ()) if s}
    st_norm = {norm_store(s) for s in (stores_raw or ()) if s}
    sess = set(sessions or ())

    active, reported = load_active_sets(protocol_dir, clean)
    report = {}

    def hits(entry):
        return {
            "photo_id": len(ids & entry["pids"]),
            "sha256": len(ssh & entry["shas"]),
            "store_canonical": len(st_norm & entry["stores"]),
            "alias_fuzzy": len(st_norm & entry["stores"]),  # 同 canonical 键，显式披露
            "session": len(sess & entry["sessions"]),
        }

    for name, entry in {**active, **reported}.items():
        h = hits(entry)
        total = sum(h.values())
        enforced = name in active
        report[name] = {"role": entry["role"], "enforced": enforced, "hits": h}
        if total == 0:
            continue
        msg = (f"[protocol-guard] {name} ({entry['role']}) 交集: "
               + ", ".join(f"{k}={v}" for k, v in h.items() if v))
        if enforced:
            raise RuntimeError(
                f"{msg} —— ({context}) 冻结集零泄漏失败，拒绝构建。"
                f"抽样前必须排除 active protocol 的全部五键。")
        print(f"  {msg} —— 仅报告不阻断（legacy/已被取代）")
    return report
