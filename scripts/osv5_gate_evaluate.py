#!/usr/bin/env python3
"""OSV51 T6：Gate 3.3 全量评估（evidence-driven，写入机器 gate.json）。

绑定：HEAD / 代码树 hash / migration hash / DB scope-graph
fingerprint / 事件与 outbox 水位 / work 投影 hash / 关键表计数。
OSV51 C-6：**recorded 侧只来自各证据文件的 binding 块**（UAT/test/
browser/negative 生成时刻各自独立计算），current 侧现场计算——
禁止把当前值同时当作 recorded 与 current（自比较）。
评估后 /api/v1/control/gate 的实时 freshness 复评以本文件为基准：
DB/代码变化 → STALE_GATE_EVIDENCE。

用法：python3 scripts/osv5_gate_evaluate.py
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
GATE_OUT = ROOT / ".eval" / "scope_v5" / "gate.json"
UAT_REPORT = ROOT / ".eval" / "scope_v5" / "uatv7" / "report.json"
BROWSER_REPORT = ROOT / ".eval" / "scope_v5" / "browser" / \
    "browser_evidence.json"
ISSUES = ROOT / "docs" / "implementation" / \
    "agentic-business-os-operational-scope-v5" / "ISSUES.md"
TEST_REPORT = ROOT / ".eval" / "scope_v5" / "test_report.json"
NEGATIVE_REPORT = ROOT / ".eval" / "scope_v5" / \
    "gate_negative_tests.json"

from src.platform import binding_core as _bc  # noqa: E402


def _load(path: Path) -> dict | None:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return None


def _service_health() -> dict:
    """与 bin/abos probe 同语义：app=/api/v1/health 200；
    LS=/health 200；recognize/monitor 根路径可达（任意 HTTP 响应）。"""
    import urllib.error

    def code(url: str) -> int:
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception:  # noqa: BLE001
            return 0

    return {"app": code("http://127.0.0.1:8400/api/v1/health") == 200,
            "recognize": code("http://127.0.0.1:8091/") != 0,
            "monitor": code("http://127.0.0.1:8092/") != 0,
            "label_studio": code("http://127.0.0.1:8300/health") == 200}


def _manifest_entry(path: Path) -> dict | None:
    try:
        if not path.exists():
            return None
        blob = path.read_bytes()
        st = path.stat()
        from datetime import datetime, timezone
        return {"path": str(path.relative_to(ROOT)),
                "sha256": hashlib.sha256(blob).hexdigest(),
                "size": st.st_size,
                "generated_at": datetime.fromtimestamp(
                    st.st_mtime, tz=timezone.utc).isoformat()}
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    from src.composition.build import build_production_bundle
    from src.platform.gate_evaluator import (EVALUATOR_VERSION,
                                             evaluate_gate_from_evidence)

    class _NoRec:
        def recognize(self, data, conf=0.25):
            return {"count": 0, "products": []}

    bundle = build_production_bundle(
        db_path=ROOT / ".platform" / "platform.sqlite",
        cas_root=ROOT / ".platform" / "cas",
        recognition_adapter=_NoRec(), probe=lambda spec: None)
    store = bundle.store

    # ---- OSV52：证据 manifest（路径/SHA256/大小/生成时间）——
    # recorded 侧只来自证据文件本身，禁止自比较。 ----
    manifest = {}
    for kind, path in (("uat_report", UAT_REPORT),
                       ("test_report", TEST_REPORT),
                       ("browser_report", BROWSER_REPORT),
                       ("negative_report", NEGATIVE_REPORT),
                       ("issue_ledger", ISSUES)):
        entry = _manifest_entry(path)
        if entry:
            manifest[kind] = entry

    # ---- current 侧：现场独立计算 ----
    head = _bc.git_head(ROOT)
    tree = _bc.tree_hash(ROOT)
    mig = _bc.migration_hash(store._conn)
    # recorded 侧：来自各证据 binding 块（anchor 取 test/uat/...）
    def _binding_of(path: Path) -> dict:
        d = _load(path)
        return (d or {}).get("binding") or {}
    anchor = next((_binding_of(p) for p in (TEST_REPORT, UAT_REPORT,
                                            BROWSER_REPORT,
                                            NEGATIVE_REPORT)
                   if _binding_of(p)), {})
    evidence_bindings = {
        "uat": _binding_of(UAT_REPORT) or None,
        "test": _binding_of(TEST_REPORT) or None,
        "browser": _binding_of(BROWSER_REPORT) or None,
        "negative": _binding_of(NEGATIVE_REPORT) or None,
    }
    result = evaluate_gate_from_evidence(
        store=store,
        uat_report_path=UAT_REPORT if UAT_REPORT.exists() else None,
        browser_report_path=BROWSER_REPORT if BROWSER_REPORT.exists()
        else None,
        issue_ledger_path=ISSUES if ISSUES.exists() else None,
        test_report_path=TEST_REPORT if TEST_REPORT.exists() else None,
        negative_report_path=NEGATIVE_REPORT
        if NEGATIVE_REPORT.exists() else None,
        service_health=_service_health(),
        source_commit=anchor.get("source_commit", ""),
        current_head=head,
        recorded_tree_hash=anchor.get("code_tree_hash", ""),
        current_tree_hash=tree,
        recorded_migration_hash=anchor.get("migration_hash", ""),
        current_migration_hash=mig,
        worktree_clean=_bc.worktree_clean(ROOT),
        evidence_bindings=evidence_bindings,
        evidence_root=ROOT,
        out_path=GATE_OUT)

    # OSV52：gate.json 附带证据 manifest；随后登记 gate_run_v1
    # candidate（Active Gate Registry；激活需人工批准）。
    try:
        recorded = json.loads(GATE_OUT.read_text(encoding="utf-8"))
        recorded["evidence_manifest"] = manifest
        GATE_OUT.write_text(json.dumps(recorded, ensure_ascii=False,
                                       indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"manifest 写入失败: {e}", file=sys.stderr)
    gate_run_id = ""
    try:
        from src.platform.gate_registry import record_gate_run
        manifest_blob = json.dumps(manifest, ensure_ascii=False,
                                   sort_keys=True).encode()
        gate_run_id = record_gate_run(
            store, protocol="scope_v5", gate_path=GATE_OUT,
            source_commit=head, evaluator_version=EVALUATOR_VERSION,
            evidence_manifest_hash=hashlib.sha256(
                manifest_blob).hexdigest()[:16],
            gate_file_sha256=hashlib.sha256(
                GATE_OUT.read_bytes()).hexdigest(),
            requested_by="osv5_gate_evaluate",
            note=f"gate={result.get('gate')}")
    except Exception as e:  # noqa: BLE001
        print(f"gate_run 登记失败: {e}", file=sys.stderr)
    print(json.dumps({"gate": result["gate"],
                      "reasons": result["reasons"][:8],
                      "checks_failed": [c["check"] for c in
                                        result["checks"]
                                        if not c["ok"]],
                      "gate_run_id": gate_run_id,
                      "out": str(GATE_OUT)}, ensure_ascii=False,
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
