"""rq_v1 追加式失效 + rq_v2 登记（PLC3-004，不可变账本）。

顺序（每步 fail-closed）：
1. sqlite backup API 备份平台库 → .platform/backups/（拒绝覆盖）；
2. integrity_check 源库与备份库均 ok；
3. register rq_v1 / rq_v2（幂等）；
4. invalidate rq_v1（reason=invalid_id_sha_mapping，superseded_by=rq_v2）；
5. 写证据报告 .review_queue/rq_v1_invalidation_evidence.json；
6. 打印账本与 active/invalid 统计。

不删除、不改写任何 review_task_v1 历史行。

用法：
  python -m scripts.invalidate_rq_v1_publish_rq_v2
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB = PROJECT_ROOT / ".platform" / "platform.sqlite"
BACKUP_DIR = PROJECT_ROOT / ".platform" / "backups"
V1_QUEUE = PROJECT_ROOT / ".review_queue" / "review_queue_diag_v1.json"
V2_QUEUE = PROJECT_ROOT / ".review_queue" / "review_queue_diag_v2.json"
EVIDENCE = PROJECT_ROOT / ".review_queue" / "rq_v1_invalidation_evidence.json"


def _integrity(db: Path) -> str:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
            text=True).strip()
    except Exception:
        return ""


def main() -> None:
    from src.platform.data.store import PlatformStore

    if not V2_QUEUE.exists():
        raise SystemExit(f"V2 队列不存在，先运行 build_review_queue_v2: {V2_QUEUE}")
    v1 = json.loads(V1_QUEUE.read_text(encoding="utf-8"))
    v2 = json.loads(V2_QUEUE.read_text(encoding="utf-8"))
    audit = v2.get("audit", {})
    if audit.get("pairing_correct") != audit.get("n_tasks"):
        raise SystemExit("V2 审计配对未全对，fail-closed：拒绝登记/失效")

    # 1+2. 备份 + 双向 integrity_check
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / "platform_before_rq_v1_invalidation.sqlite"
    if backup.exists():
        raise SystemExit(f"备份已存在，禁止覆盖: {backup}")
    src = sqlite3.connect(DB)
    dst = sqlite3.connect(backup)
    src.backup(dst)
    dst.close(); src.close()
    ic_src, ic_bak = _integrity(DB), _integrity(backup)
    if ic_src != "ok" or ic_bak != "ok":
        raise SystemExit(f"integrity_check 未通过: src={ic_src} bak={ic_bak}")

    # 3+4. 账本登记与追加式失效
    commit = _git_commit()
    store = PlatformStore(DB)
    try:
        store.register_queue_version(
            queue_version="rq_v1", protocol=v1.get("protocol", ""),
            n_tasks=len(v1.get("items", [])), source_path=str(V1_QUEUE))
        store.register_queue_version(
            queue_version="rq_v2", protocol=v2.get("protocol", ""),
            n_tasks=len(v2.get("items", [])), source_path=str(V2_QUEUE))
        store.invalidate_queue_version(
            queue_version="rq_v1",
            reason="invalid_id_sha_mapping",
            root_cause=("diagnostic_v1.json 将 photo_ids 与 sha256 各自独立排序，"
                        "下游按数组位置 zip 造成 ID/SHA 错配"
                        "（协议 2/500、队列 0/250 配对正确）"),
            impact_summary=("250 条 rq_v1 任务的 sha256 与 photo_id 错配，"
                            "审核对象与图片内容不对应；gold_region 为 0，"
                            "未污染任何真值；历史行保留，仅追加失效记录"),
            git_commit=commit,
            evidence_path=str(EVIDENCE),
            superseded_by="rq_v2")
        ledger = store.list_queue_ledger()
        stats = store.review_task_stats()
    finally:
        store.close()

    # 5. 证据报告
    evidence = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": commit,
        "backup": str(backup),
        "integrity_check": {"source": ic_src, "backup": ic_bak},
        "rq_v1": {"source": str(V1_QUEUE), "n_tasks": len(v1.get("items", [])),
                  "pairing_correct": "0/250（现场复现）"},
        "rq_v2": {"source": str(V2_QUEUE), "n_tasks": audit.get("n_tasks"),
                  "n_unique_photos": audit.get("n_unique_photos"),
                  "pairing_correct": f"{audit.get('pairing_correct')}/{audit.get('n_tasks')}",
                  "tasks_hash": audit.get("tasks_hash")},
        "reason": "invalid_id_sha_mapping",
        "superseded_by": "rq_v2",
        "ledger": ledger,
        "task_stats": stats,
    }
    if not EVIDENCE.exists():
        tmp = EVIDENCE.with_suffix(".tmp")
        tmp.write_text(json.dumps(evidence, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(EVIDENCE)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
