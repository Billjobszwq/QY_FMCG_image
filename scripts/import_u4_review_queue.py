"""U4-3：把 .review_queue/review_queue_diag_v1.json 的真实 250 条
pending 队列接入生产平台库（.platform/platform.sqlite）。

- 只读队列 JSON，追加式写入 review_task_v1（不可变），不改动源文件；
- 幂等：重复执行 imported=0；
- 打印导入前后状态分布，作为接入证据。

用法：
  python -m scripts.import_u4_review_queue
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUEUE = PROJECT_ROOT / ".review_queue" / "review_queue_diag_v1.json"
DB = PROJECT_ROOT / ".platform" / "platform.sqlite"


def main() -> None:
    from src.platform.annotate.review import import_review_queue
    from src.platform.data.store import PlatformStore

    if not QUEUE.exists():
        raise SystemExit(f"队列文件不存在: {QUEUE}")
    src = json.loads(QUEUE.read_text(encoding="utf-8"))

    store = PlatformStore(DB)
    try:
        before = Counter(t["review_mode"]
                         for t in store.list_review_tasks())
        out = import_review_queue(store, QUEUE,
                                  seed=src.get("seed", 20260804))
        out2 = import_review_queue(store, QUEUE,
                                   seed=src.get("seed", 20260804))
        tasks = store.list_review_tasks()
        after = Counter(t["review_mode"] for t in tasks)
    finally:
        store.close()

    print(json.dumps({
        "db": str(DB),
        "queue_file": str(QUEUE),
        "queue_version": src.get("queue_version"),
        "protocol": src.get("protocol"),
        "source_items": len(src.get("items", [])),
        "imported": out["imported"],
        "rerun_imported": out2["imported"],
        "total_tasks": out2["total"],
        "before_by_mode": dict(before),
        "after_by_mode": dict(after),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
