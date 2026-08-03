"""写出层：提案(预标注) / 人工审核 / 训练源(approved) 三者分离。

红线：自动产出只进 proposals/；训练只读 approved/；approved 仅由人工 approved 照片生成；
rework/rejected 移除对应 approved。全部经 paths 护栏，绝不碰原始资产。人工动作以追加事件留痕。"""
from __future__ import annotations

import json

from ..common import paths

LABEL_DIR = paths.PROJECT_ROOT / ".labels"
PROPOSALS = LABEL_DIR / "proposals"
APPROVED = LABEL_DIR / "approved"
REVIEWS = LABEL_DIR / "reviews"


def _ensure():
    for d in (LABEL_DIR, PROPOSALS, APPROVED, REVIEWS):
        d.mkdir(parents=True, exist_ok=True)


def build_classmap(reg):
    ids = sorted(reg.canonicals.keys())
    return {c: i for i, c in enumerate(ids)}, ids


def _norm(box, W, H):
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2 / W, (y1 + y2) / 2 / H, (x2 - x1) / W, (y2 - y1) / H)


def _guard_unlink(p):
    p = paths.assert_writable(p)
    if p.exists():
        p.unlink()


def write_classmap(ids):
    _ensure()
    paths.safe_write_text(LABEL_DIR / "classes.json", json.dumps(ids, ensure_ascii=False, indent=2))


def write_proposal(asset_id, regions_with_cls, W, H):
    """提案=预标注草稿（给人工看），非训练源。"""
    _ensure()
    lines = []
    for cls, b in regions_with_cls:
        xc, yc, w, h = _norm(b, W, H)
        lines.append(f"{cls} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}")
    paths.safe_write_text(PROPOSALS / f"{asset_id}.txt", "\n".join(lines) + ("\n" if lines else ""))


def write_proposal_sidecar(asset_id, records):
    _ensure()
    paths.safe_write_text(PROPOSALS / f"{asset_id}.json", json.dumps(records, ensure_ascii=False, indent=2))


def write_review(asset_id, review):
    _ensure()
    paths.safe_write_text(REVIEWS / f"{asset_id}.json", json.dumps(review, ensure_ascii=False, indent=2))


def append_review_event(event):
    _ensure()
    with paths.safe_open_write(LABEL_DIR / "review_events.jsonl", "a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def apply_review_to_approved(asset_id, review, W, H, classmap):
    """approved=训练唯一来源；仅 status==approved 且 confirmed 且 canonical 合法的区域入。"""
    _ensure()
    if review.get("status") == "approved":
        lines = []
        for r in review.get("regions", []):
            cid = r.get("canonical_id")
            if cid in classmap and r.get("confirmed", True):
                xc, yc, w, h = _norm(r["box"], W, H)
                lines.append(f"{classmap[cid]} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}")
        paths.safe_write_text(APPROVED / f"{asset_id}.txt", "\n".join(lines) + ("\n" if lines else ""))
    else:
        _guard_unlink(APPROVED / f"{asset_id}.txt")


def write_review_queue(queue):
    _ensure()
    paths.safe_write_text(LABEL_DIR / "review_queue.json", json.dumps(queue, ensure_ascii=False, indent=2))
