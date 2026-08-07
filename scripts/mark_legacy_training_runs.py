"""GLTC D2：追加式标记历史 legacy dry-run（non_executable）。

背景：training_run 表 4 条历史 dry_run 的 command 含当前 train_v1 CLI
已禁用的 `--dataset/--budget-minutes`。红线：不删除、不改历史行；
仅追加 training_run_supersession_v1 记录，禁止后续批准/入队。

流程（幂等）：
1. sqlite3 backup API 备份 + 双向 integrity_check；
2. PlatformStore 打开（自动应用 migration 020）；
3. 扫描 command_json 含禁用参数的 dry_run，逐条追加 supersession；
4. 输出证据 JSON（拒绝覆盖既有证据文件）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FORBIDDEN_ARGS = ("--dataset", "--budget-minutes")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / ".platform/platform.sqlite"))
    ap.add_argument("--evidence",
                    default=str(ROOT / ".platform"
                                / "training_run_legacy_supersession.json"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    from src.platform.data.store import PlatformStore

    db = Path(a.db)
    evidence_path = Path(a.evidence)
    if evidence_path.exists():
        print(f"证据文件已存在，拒绝覆盖: {evidence_path}")
        return 0

    # 1. 备份 + integrity（迁移前强制）
    backup_dir = ROOT / ".platform/backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"platform_before_legacy_run_supersession_{ts}.sqlite"
    store = PlatformStore(db)
    store.backup(backup_path)
    for p in (db, backup_path):
        out = subprocess.run(["sqlite3", str(p), "PRAGMA integrity_check"],
                             capture_output=True, text=True)
        if out.stdout.strip() != "ok":
            print(f"integrity_check 失败: {p}: {out.stdout}")
            return 1

    # 2. 扫描禁用参数
    rows = store._conn.execute(
        "SELECT run_id, command_json, status FROM training_run").fetchall()
    targets = []
    for r in rows:
        cmd = json.loads(r["command_json"])
        if any(arg in FORBIDDEN_ARGS for arg in cmd):
            targets.append(dict(r))

    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
        cwd=ROOT).stdout.strip()

    # 3. 追加式标记
    for t in targets:
        if not a.dry_run:
            store.supersede_training_run(
                t["run_id"], reason="cli_args_removed",
                superseded_by="training_control_v2", git_commit=git_commit)

    ledger = store.list_training_run_supersessions()
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit,
        "backup": str(backup_path),
        "forbidden_args": list(FORBIDDEN_ARGS),
        "marked": [t["run_id"] for t in targets],
        "n_total_training_run": len(rows),
        "ledger_after": ledger,
        "dry_run": a.dry_run,
        "note": "历史 training_run 行未修改；仅追加 supersession 账本",
    }
    if not a.dry_run:
        evidence_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8")
    print(json.dumps({"marked": len(targets),
                      "ledger_rows": len(ledger),
                      "backup": str(backup_path),
                      "dry_run": a.dry_run}, ensure_ascii=False))
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
