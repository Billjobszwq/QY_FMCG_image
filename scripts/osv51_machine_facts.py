#!/usr/bin/env python3
"""OSV51 C-8：机器事实单一事实源（machine facts）。

FINAL-REPORT / STATUS 中的 HEAD、branch、Registry 计数、Gate checks
数、UAT namespace/batch IDs、测试数量、服务状态、bundle、训练进程
一律由本脚本从机器证据生成（.eval/scope_v5/machine_facts.json），
禁止手工重复录入（杜绝 42vs52 / 125vs126 / 过期 namespace 漂移）。

用法：python3 scripts/osv51_machine_facts.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EV = ROOT / ".eval" / "scope_v5"
OUT = EV / "machine_facts.json"


def _git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=str(ROOT),
                              capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _load(p: Path) -> dict | None:
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return None


def _http(url: str) -> int:
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001
        return 0


def _training_procs() -> int:
    try:
        out = subprocess.run(
            ["pgrep", "-f",
             "train_detector|train_classifier|train_segmenter|"
             "run_qwen3vl_lora|ultralytics"],
            capture_output=True, text=True, timeout=10).stdout
        return len([l for l in out.splitlines() if l.strip()])
    except Exception:  # noqa: BLE001
        return -1


def main() -> int:
    from src.platform.scope_registry import SCOPE_REGISTRY
    gate = _load(EV / "gate.json")
    uat = _load(EV / "uatv7" / "report.json")
    test = _load(EV / "test_report.json")
    brow = _load(EV / "browser" / "browser_evidence.json")
    negd = _load(EV / "gate_negative_tests.json")
    current = _load(ROOT / ".models" / "bundles" / "CURRENT.json")

    facts = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git": {
            "head": _git("rev-parse", "HEAD"),
            "branch": _git("branch", "--show-current"),
            "worktree_clean": _git("status", "--porcelain",
                                   "--untracked-files=no") == "",
            "commits_since_baseline": len([
                l for l in _git("log", "--format=%h",
                                "8e31708d..HEAD").splitlines()
                if l.strip()]),
        },
        "registry": {"entries": len(SCOPE_REGISTRY)},
        "gate": {
            "gate": (gate or {}).get("gate"),
            "checks_total": len((gate or {}).get("checks") or []),
            "checks_ok": sum(1 for c in (gate or {}).get("checks") or []
                             if c.get("ok")),
            "evaluator_version": (gate or {}).get("evaluator_version"),
            "source_commit": (gate or {}).get("source_commit"),
        },
        "gate_negatives": {
            "count": len((negd or {}).get("gate_negative_tests") or []),
            "all_blocked": (negd or {}).get("all_blocked"),
        },
        "uatv7": {
            "namespace": (uat or {}).get("namespace"),
            "total": (uat or {}).get("total"),
            "failed": (uat or {}).get("failed"),
            "ids": (uat or {}).get("ids"),
            "binding_source_commit":
                ((uat or {}).get("binding") or {}).get("source_commit"),
        },
        "tests": {
            "suite": (test or {}).get("suite"),
            "failed": (test or {}).get("failed"),
            "passed": (test or {}).get("passed"),
            "skipped": (test or {}).get("skipped"),
            "deselected": (test or {}).get("deselected"),
            "binding_source_commit":
                ((test or {}).get("binding") or {}).get("source_commit"),
        },
        "browser": {
            "pages": len((brow or {}).get("pages") or []),
            "assertions_ok": sum(
                1 for p in (brow or {}).get("pages") or []
                if p.get("assertion")),
            "console_errors_unexplained":
                (brow or {}).get("console_errors_unexplained"),
            "binding_source_commit":
                ((brow or {}).get("binding") or {}).get("source_commit"),
        },
        "services": {
            "app": _http("http://127.0.0.1:8400/api/v1/health") == 200,
            "recognize": _http("http://127.0.0.1:8091/") != 0,
            "monitor": _http("http://127.0.0.1:8092/") != 0,
            "label_studio":
                _http("http://127.0.0.1:8300/health") == 200,
        },
        "production": {
            "bundle": (current or {}).get("bundle_id"),
            "previous": (current or {}).get("previous"),
        },
        "training_processes": _training_procs(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(facts, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(json.dumps(facts, ensure_ascii=False, indent=2)[:2500])
    print(f"facts → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
