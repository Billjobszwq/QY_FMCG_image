"""生成 diagnostic_v1 人工双审队列（手册§七 / 用户要求#12/#13/#26）。

- 前 200 张双审；固定 seed=20260804（协议 seed）盲抽 50 张 blind-manual；
- 队列项全部 pending，不伪造任何结果；
- 输出 `.review_queue/review_queue_diag_v1.json`（已存在则拒绝覆盖）；
- 打印 queue_status：未完成 → awaiting_human_review。

用法：
  python -m scripts.build_review_queue
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

from src.review.human_review_queue import (
    build_review_queue, queue_status, write_queue)

DIAG = PROJECT_ROOT / ".data_protocol/diagnostic_v1.json"
OUT = PROJECT_ROOT / ".review_queue/review_queue_diag_v1.json"


def main():
    d = json.loads(DIAG.read_text(encoding="utf-8"))
    assert d.get("frozen") is True and d["role"] == "diagnostic_v1"
    photos = [{"photo_id": pid, "sha256": sha}
              for pid, sha in zip(d["photo_ids"], d["sha256"])]
    q = build_review_queue(photos, seed=int(d.get("seed", 20260804)))
    write_queue(q, OUT)
    st = queue_status(q)
    print(f"[review] queue → {OUT}")
    print(f"[review] items={st['total']} pending={st['pending']} "
          f"(双审 {st['pending_double_review']} / 盲抽 {st['pending_blind_manual']})")
    print(f"[review] status={st['status']}")
    for b in st["blockers"]:
        print(f"[review] blocker: {b}")


if __name__ == "__main__":
    main()
