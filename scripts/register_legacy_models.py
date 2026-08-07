"""GLTC Task 2：真实 .models/ 只读 inventory + 追加式登记。

不移动/不删除/不覆盖任何模型文件；登记走 legacy_model_registry_v1
（migration 022，触发器禁删改）；证据 JSON 拒绝覆盖。
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-root", default=str(ROOT / ".models"))
    ap.add_argument("--db", default=str(ROOT / ".platform/platform.sqlite"))
    ap.add_argument("--evidence",
                    default=str(ROOT / ".platform/legacy_model_inventory.json"))
    a = ap.parse_args()

    from src.modules.training_control import legacy as L
    from src.platform.data.store import PlatformStore

    evidence = Path(a.evidence)
    if evidence.exists():
        print(f"证据已存在，拒绝覆盖: {evidence}")
        return 0

    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
        cwd=ROOT).stdout.strip()

    store = PlatformStore(Path(a.db))
    # 备份 + integrity（写前强制）
    backup_dir = ROOT / ".platform/backups"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"platform_before_legacy_registry_{ts}.sqlite"
    store.backup(backup_path)
    out = subprocess.run(["sqlite3", str(backup_path),
                          "PRAGMA integrity_check"],
                         capture_output=True, text=True)
    if out.stdout.strip() != "ok":
        print(f"备份 integrity 失败: {out.stdout}")
        return 1

    inventory = L.scan_model_inventory(Path(a.models_root))
    registered = L.register_legacy_models(store, inventory,
                                          git_commit=git_commit)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit,
        "models_root": a.models_root,
        "backup": str(backup_path),
        "registered_new": registered,
        "models": [
            {"model_id": e["model_id"], "status": e["status"],
             "n_weights": len(e["weights"]),
             "weight_sha256": [w["sha256"] for w in e["weights"]]}
            for e in inventory],
        "note": "只读扫描；未移动/删除/覆盖任何模型文件",
    }
    evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(json.dumps({"registered_new": registered,
                      "total_models": len(inventory),
                      "evidence": str(evidence)}, ensure_ascii=False))
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
