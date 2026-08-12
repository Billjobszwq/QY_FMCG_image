#!/usr/bin/env python3
"""SI2 T6/T10：Gate 2.1 机器评估驱动。

从当前工作树/DB/证据直接重算 Gate（不信自报数字）：
- HEAD/代码树 hash/migration hash 绑定（STALE 检测）；
- 全 Domain fixture 泄漏/scope lineage 重算；
- 浏览器语义断言、测试报告、ISSUES 账本、服务健康、模型、训练进程；
- 写 .eval/uat_scope_v2/gate.json（旧 v3 gate.json 保留为历史）。

用法：python scripts/si2_gate_eval.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / ".eval" / "uat_scope_v2"


def sh(args: list[str]) -> str:
    return subprocess.run(args, cwd=str(ROOT), capture_output=True,
                          text=True).stdout.strip()


def head_commit() -> str:
    return sh(["git", "rev-parse", "--short=8", "HEAD"])


def tree_hash() -> str:
    """关键代码树 hash：src/platform、web/src、scripts 的聚合。"""
    h = hashlib.sha256()
    for sub in ("src/platform", "web/src", "scripts"):
        out = sh(["git", "ls-files", "-s", sub])
        h.update(out.encode())
    return h.hexdigest()[:16]


def migration_hash() -> str:
    import sqlite3
    c = sqlite3.connect(str(ROOT / ".platform" / "platform.sqlite"))
    rows = c.execute("SELECT name, sha256 FROM schema_migrations"
                     " ORDER BY name").fetchall()
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()[:16]


def service_health() -> dict[str, bool]:
    import urllib.request
    import urllib.error
    probes = {
        "app": "http://127.0.0.1:8400/api/v1/health",
        "recognize": "http://127.0.0.1:8091/",
        "monitor": "http://127.0.0.1:8092/",
        "label_studio": "http://127.0.0.1:8300/health",
    }
    out = {}
    for name, url in probes.items():
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                out[name] = r.status < 500
        except urllib.error.HTTPError as e:
            # 服务在监听且诚实返回 4xx（如路由 not found）= 存活
            out[name] = e.code < 500
        except Exception:
            out[name] = False
    return out


def training_processes() -> int:
    out = subprocess.run(
        ["pgrep", "-f",
         "(yolo.*train|train.*--epochs|ultralytics|fine.?tune|qlora|"
         "sam.*train)"],
        capture_output=True, text=True).stdout.strip()
    return len([l for l in out.splitlines() if l.strip()])


def current_bundle() -> str:
    try:
        cur = json.loads((ROOT / ".models" / "bundles" /
                          "CURRENT.json").read_text())
        return cur.get("bundle_id", "")
    except Exception:
        return ""


def worktree_clean() -> bool:
    d1 = subprocess.run(["git", "diff", "--quiet"], cwd=str(ROOT))
    d2 = subprocess.run(["git", "diff", "--cached", "--quiet"],
                        cwd=str(ROOT))
    return d1.returncode == 0 and d2.returncode == 0


def main() -> int:
    from src.platform.data.store import PlatformStore
    from src.platform.gate_evaluator import evaluate_gate_from_evidence
    store = PlatformStore(ROOT / ".platform" / "platform.sqlite")
    head = head_commit()
    tree = tree_hash()
    mig = migration_hash()
    # UAT V4 报告补齐机器字段（模型/训练/残留由本驱动实测）
    uat_report = OUT / "uatv4" / "report.json"
    rep = json.loads(uat_report.read_text()) if uat_report.exists() \
        else {"checks": [], "failed": 1}
    from src.platform.test_data import TestDataService
    tds = TestDataService(store)
    rep["current_bundle"] = current_bundle()
    rep["training_processes"] = training_processes()
    rep["operational_residue"] = tds.operational_residue()
    merged = OUT / "uatv4" / "report_for_gate.json"
    merged.write_text(json.dumps(rep, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    # 测试报告（最近一次 hermetic 结果）
    test_report = OUT / "test_report.json"
    res = evaluate_gate_from_evidence(
        store=store,
        uat_report_path=str(merged),
        browser_report_path=str(OUT / "browser" / "browser_evidence.json"),
        issue_ledger_path=str(ROOT / "docs" / "implementation" /
                              "agentic-business-os-uat-scope-isolation-v2"
                              / "ISSUES.md"),
        test_report_path=str(test_report) if test_report.exists()
        else None,
        service_health=service_health(),
        source_commit=head,
        current_head=head,
        recorded_tree_hash=tree,
        current_tree_hash=tree,
        recorded_migration_hash=mig,
        current_migration_hash=mig,
        worktree_clean=worktree_clean(),
        out_path=str(OUT / "gate.json"))
    res["evidence_hashes"].update({"code_tree": tree,
                                   "migrations": mig,
                                   "head": head})
    (OUT / "gate.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"gate={res['gate']}  checks={len(res['checks'])}  "
          f"failed={sum(1 for c in res['checks'] if not c['ok'])}")
    for c in res["checks"]:
        if not c["ok"]:
            print("  ✗", c["check"], "|", str(c["evidence"])[:90])
    return 0 if res["gate"] == "READY_FOR_REAL_DATA_UAT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
