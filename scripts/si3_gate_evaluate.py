#!/usr/bin/env python3
"""SI3 T7：Gate 3.0 全量评估（evidence-driven，写入机器 gate.json）。

绑定：HEAD / 代码树 hash / migration hash / DB scope-graph
fingerprint / 事件与 outbox 水位 / work 投影 hash / 关键表计数。
评估后 /api/v1/control/gate 的实时 freshness 复评以本文件为基准：
DB/代码变化 → STALE_GATE_EVIDENCE。

用法：python3 scripts/si3_gate_evaluate.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
GATE_OUT = ROOT / ".eval" / "scope_v3" / "gate.json"
UAT_REPORT = ROOT / ".eval" / "scope_v3" / "uatv5" / "report.json"
BROWSER_REPORT = ROOT / ".eval" / "scope_v3" / "browser" / \
    "browser_evidence.json"
ISSUES = ROOT / "docs" / "implementation" / \
    "agentic-business-os-scope-integrity-v3" / "ISSUES.md"
TEST_REPORT = ROOT / ".eval" / "scope_v3" / "test_report.json"


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT),
            capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _worktree_clean() -> bool:
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=str(ROOT), capture_output=True, text=True,
            timeout=10).stdout
        return out.strip() == ""
    except Exception:  # noqa: BLE001
        return False


def _tree_hash() -> str:
    h = hashlib.sha256()
    for sub in ("src/platform", "web/src", "scripts"):
        base = ROOT / sub
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts \
                    and not p.name.startswith("."):
                h.update(str(p.relative_to(ROOT)).encode())
                h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _migration_hash(store) -> str:
    rows = store._conn.execute(
        "SELECT name FROM schema_migrations ORDER BY id").fetchall()
    return hashlib.sha256(
        ",".join(r["name"] for r in rows).encode()).hexdigest()[:16]


def _service_health() -> dict:
    out = {}
    for name, url in (("app", "http://127.0.0.1:8400/api/v1/health"),
                      ("recognize", "http://127.0.0.1:8091/health"),
                      ("monitor", "http://127.0.0.1:8092/health"),
                      ("label_studio", "http://127.0.0.1:8300/")):
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                out[name] = r.status == 200
        except Exception:  # noqa: BLE001
            out[name] = False
    return out


def main() -> int:
    from src.composition.build import build_production_bundle
    from src.platform.gate_evaluator import evaluate_gate_from_evidence

    class _NoRec:
        def recognize(self, data, conf=0.25):
            return {"count": 0, "products": []}

    bundle = build_production_bundle(
        db_path=ROOT / ".platform" / "platform.sqlite",
        cas_root=ROOT / ".platform" / "cas",
        recognition_adapter=_NoRec(), probe=lambda spec: None)
    store = bundle.store
    head = _git_head()
    tree = _tree_hash()
    mig = _migration_hash(store)
    result = evaluate_gate_from_evidence(
        store=store,
        uat_report_path=UAT_REPORT if UAT_REPORT.exists() else None,
        browser_report_path=BROWSER_REPORT if BROWSER_REPORT.exists()
        else None,
        issue_ledger_path=ISSUES if ISSUES.exists() else None,
        test_report_path=TEST_REPORT if TEST_REPORT.exists() else None,
        service_health=_service_health(),
        source_commit=head, current_head=head,
        recorded_tree_hash=tree, current_tree_hash=tree,
        recorded_migration_hash=mig, current_migration_hash=mig,
        worktree_clean=_worktree_clean(),
        out_path=GATE_OUT)
    print(json.dumps({"gate": result["gate"],
                      "reasons": result["reasons"][:8],
                      "checks_failed": [c["check"] for c in
                                        result["checks"]
                                        if not c["ok"]],
                      "out": str(GATE_OUT)}, ensure_ascii=False,
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
