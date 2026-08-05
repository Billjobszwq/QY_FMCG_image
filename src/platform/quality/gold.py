"""U3-6：分层人工质量金标准入口 + 混淆矩阵。

口径（手册 §5/U4 指令）：
- 金标准队列只收「本地真实文件」（directory 来源且文件存在于 root），
  manifest-only（无本地文件）照片不得进入人工金标准。
- 按最新自动结论分层（fail / waiting_human / pass），轮转抽样，
  保证每个层都有代表；sha256 幂等（quality_gold_v1 UNIQUE）。
- 人工未完成时状态只能显示 waiting_human（由 quality_human_v1 是否
  存在该 SHA 的行推导，不做 UPDATE），不得伪造通过。
- 混淆矩阵只对「有人工结论」的对计算；无自动结论或自动结论为
  waiting_human 的统一记为 auto=none。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

VERDICTS = ("pass", "fail")


def _latest_auto(store, sha256: str) -> str | None:
    """该 SHA 最新一条自动结论（quality_decision_v1），无则 None。"""
    rows = store.list_quality_decisions(sha256=sha256, limit=1)
    return rows[0]["auto_decision"] if rows else None


def _candidates(store, root: Path) -> list[dict[str, Any]]:
    """台账中 source_type=directory、本地文件存在、SHA 非空的候选。"""
    out, seen = [], set()
    offset = 0
    while True:
        rows = store.list_inventory_assets(limit=500, offset=offset)
        if not rows:
            break
        offset += 500
        for r in rows:
            if r["source_type"] != "directory":
                continue
            uri = r["source_uri"]
            sha = r.get("sha256") or ""
            if "#" in uri or not sha or sha in seen:
                continue
            if not (root / uri).exists():
                continue
            seen.add(sha)
            auto = _latest_auto(store, sha)
            # 无可信自动结论（无记录或 waiting_human）归入 waiting_human 层
            stratum = auto if auto in ("fail", "pass") else "waiting_human"
            out.append({"sha256": sha, "source_uri": uri,
                        "stratum": stratum})
    return out


def build_gold_queue(store, *, size: int,
                     root: Path) -> dict[str, Any]:
    """分层抽取最多 size 张本地照片进入金标准队列（幂等）。"""
    by_stratum: dict[str, list[dict[str, Any]]] = {}
    for c in _candidates(store, Path(root)):
        by_stratum.setdefault(c["stratum"], []).append(c)

    # 轮转跨层取样，保证每个层都有代表
    picked: list[dict[str, Any]] = []
    while len(picked) < size:
        progressed = False
        for items in by_stratum.values():
            if items and len(picked) < size:
                picked.append(items.pop(0))
                progressed = True
        if not progressed:
            break

    added = 0
    for it in picked:
        if store.add_gold_item(sha256=it["sha256"],
                               source_uri=it["source_uri"],
                               stratum=it["stratum"]):
            added += 1
    return {"added": added,
            "total_queue": len(store.list_gold_queue()),
            "items": picked}


def gold_status(store) -> dict[str, Any]:
    """金标准进度；status 由人工结论是否存在推导（禁止伪造通过）。"""
    items = []
    done = 0
    for q in store.list_gold_queue():
        v = store.find_human_verdict(q["sha256"])
        if v is None:
            status, verdict = "waiting_human", None
        else:
            status, verdict, done = "done", v["verdict"], done + 1
        items.append({"sha256": q["sha256"],
                      "source_uri": q["source_uri"],
                      "stratum": q["stratum"],
                      "status": status,
                      "human_verdict": verdict})
    return {"waiting_human": len(items) - done, "done": done,
            "items": items}


def submit_human_verdict(store, *, sha256: str, verdict: str,
                         reviewer: str,
                         dims: dict[str, Any] | None = None
                         ) -> dict[str, Any]:
    """追加一条真实人工结论（追加式不可变；同一 SHA 仅一次）。"""
    if verdict not in VERDICTS:
        raise ValueError(f"verdict 必须是 {VERDICTS}，收到 {verdict!r}")
    if not reviewer:
        raise ValueError("reviewer 必须为真实登录身份，禁止匿名提交")
    ok = store.add_human_verdict(sha256=sha256, verdict=verdict,
                                 reviewer=reviewer, dims=dims)
    return {"sha256": sha256, "verdict": verdict, "reviewer": reviewer,
            "accepted": ok,
            "note": "同一 SHA 重复提交被忽略；历史结论不可变"}


def confusion_matrix(store) -> dict[str, int]:
    """只对有人工结论的对计算；无自动结论/waiting_human 记为 auto=none。"""
    m = {"pairs": 0,
         "auto_fail_human_fail": 0, "auto_fail_human_pass": 0,
         "auto_pass_human_fail": 0, "auto_pass_human_pass": 0,
         "auto_none_human_fail": 0, "auto_none_human_pass": 0}
    for v in store.list_human_verdicts():
        auto = _latest_auto(store, v["sha256"])
        key_auto = auto if auto in ("fail", "pass") else "none"
        key = f"auto_{key_auto}_human_{v['verdict']}"
        if key not in m:
            continue
        m[key] += 1
        m["pairs"] += 1
    return m
