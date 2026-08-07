"""U5：把 review_queue_diag_v2 导入生产平台库（PLC3-005，fail-closed）。

与 U4 的区别：导入前先 photo_identity.validate_queue_items 逐条校验
actual_sha(photo_id)==declared_sha256，错一条即拒绝（不允许部分导入）。

用法：
  python -m scripts.import_u5_review_queue_v2
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUEUE = PROJECT_ROOT / ".review_queue" / "review_queue_diag_v2.json"
MANIFEST = PROJECT_ROOT / ".batch3_clean" / "clean_manifest.json"
DB = PROJECT_ROOT / ".platform" / "platform.sqlite"


def main() -> None:
    from src.data.photo_identity import validate_queue_items
    from src.platform.annotate.review import import_review_queue
    from src.platform.data.store import PlatformStore

    if not QUEUE.exists():
        raise SystemExit(f"队列文件不存在: {QUEUE}")
    src = json.loads(QUEUE.read_text(encoding="utf-8"))
    if src.get("queue_version") != "rq_v2":
        raise SystemExit(f"queue_version 非 rq_v2: {src.get('queue_version')}")

    report = validate_queue_items(src.get("items", []),
                                  manifest_path=MANIFEST)
    print(json.dumps({"pre_import_validation": report},
                     ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit("[u5] 配对校验未通过，fail-closed：拒绝导入")

    store = PlatformStore(DB)
    try:
        before = Counter(t["review_mode"]
                         for t in store.list_review_tasks_active())
        out = import_review_queue(store, QUEUE,
                                  seed=src.get("seed", 20260804))
        out2 = import_review_queue(store, QUEUE,
                                   seed=src.get("seed", 20260804))
        after = Counter(t["review_mode"]
                        for t in store.list_review_tasks_active())
        stats = store.review_task_stats()
    finally:
        store.close()

    print(json.dumps({
        "db": str(DB),
        "queue_file": str(QUEUE),
        "queue_version": src.get("queue_version"),
        "source_items": len(src.get("items", [])),
        "imported": out["imported"],
        "rerun_imported": out2["imported"],
        "active_by_mode_before": dict(before),
        "active_by_mode_after": dict(after),
        "task_stats": stats,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
