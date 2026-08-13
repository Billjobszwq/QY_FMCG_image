"""OSV51 C-6 测试：Gate 证据新鲜度绑定（binding 块/去自比较/STALE）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform import binding_core as bc
from src.platform.gate_evaluator import (db_fingerprint,
                                         evaluate_gate_from_evidence)

PW = "osv51-bind-pw"


class _OkRecognition:
    def recognize(self, data, conf=0.25):
        return {"count": 0, "products": []}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", PW)
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=_OkRecognition(), probe=lambda spec: None)
    build_profiles_service(bundle)
    return {"store": bundle.store, "tmp": tmp_path}


ROOT = Path(__file__).resolve().parents[2]


class TestBindingCore:
    def test_tree_hash_deterministic(self):
        assert bc.tree_hash(ROOT) == bc.tree_hash(ROOT)
        assert len(bc.tree_hash(ROOT)) == 16

    def test_command_and_result_hash_stable(self):
        assert bc.command_hash(["a", "b"]) == bc.command_hash(
            ["a", "b"])
        assert bc.command_hash(["a"]) != bc.command_hash(["b"])
        assert bc.result_hash({"x": 1}) == bc.result_hash({"x": 1})

    def test_make_binding_fields(self, env):
        b = bc.make_binding(root=ROOT, conn=env["store"]._conn,
                            argv=["x"], result_payload={"ok": True},
                            started_at="s", finished_at="f",
                            database_fingerprint={"scope_graph": "g"})
        for k in ("source_commit", "code_tree_hash", "migration_hash",
                  "suite_config_hash", "command_hash", "started_at",
                  "finished_at", "result_hash",
                  "database_fingerprint"):
            assert k in b, k


class TestEvaluatorBindingChecks:
    def _fresh_bindings(self, env):
        fp = db_fingerprint(env["store"])
        head = bc.git_head(ROOT) or "h"
        tree = bc.tree_hash(ROOT)
        mig = bc.migration_hash(env["store"]._conn)
        mk = lambda: {"source_commit": head, "code_tree_hash": tree,
                      "migration_hash": mig,
                      "database_fingerprint": fp}
        return mk, head, tree, mig

    def test_missing_binding_blocks_gate(self, env):
        res = evaluate_gate_from_evidence(
            store=env["store"],
            evidence_bindings={"uat": None, "test": None,
                               "browser": None, "negative": None})
        bad = [c["check"] for c in res["checks"] if not c["ok"]]
        for k in ("uat", "test", "browser", "negative"):
            assert f"{k}_evidence_binding_fresh" in bad
        assert res["gate"] != "READY_FOR_REAL_DATA_UAT"

    def test_stale_tree_is_stale(self, env):
        mk, head, tree, mig = self._fresh_bindings(env)
        b = mk()
        b["code_tree_hash"] = "stale0stale0stale0"
        res = evaluate_gate_from_evidence(
            store=env["store"], current_head=head,
            current_tree_hash=tree, current_migration_hash=mig,
            evidence_bindings={"test": b})
        assert res["gate"] == "STALE_GATE_EVIDENCE"

    def test_stale_db_fingerprint_is_stale(self, env):
        mk, head, tree, mig = self._fresh_bindings(env)
        b = mk()
        b["database_fingerprint"] = {
            **b["database_fingerprint"], "event_watermark": 10 ** 9}
        res = evaluate_gate_from_evidence(
            store=env["store"], current_head=head,
            current_tree_hash=tree, current_migration_hash=mig,
            evidence_bindings={"uat": b})
        assert res["gate"] == "STALE_GATE_EVIDENCE"

    def test_fresh_binding_passes_check(self, env):
        mk, head, tree, mig = self._fresh_bindings(env)
        res = evaluate_gate_from_evidence(
            store=env["store"], current_head=head,
            current_tree_hash=tree, current_migration_hash=mig,
            evidence_bindings={"test": mk()})
        by = {c["check"]: c for c in res["checks"]}
        assert by["test_evidence_binding_fresh"]["ok"] is True

    def test_self_compare_injection_never_ready(self, env):
        """旧缺陷复现防护：recorded==current 自比较 + 无 binding 证据
        不得产生 READY。"""
        head = bc.git_head(ROOT) or "h"
        tree = bc.tree_hash(ROOT)
        mig = bc.migration_hash(env["store"]._conn)
        res = evaluate_gate_from_evidence(
            store=env["store"], source_commit=head,
            current_head=head, recorded_tree_hash=tree,
            current_tree_hash=tree, recorded_migration_hash=mig,
            current_migration_hash=mig,
            evidence_bindings={"uat": None, "test": None,
                               "browser": None, "negative": None})
        assert res["gate"] != "READY_FOR_REAL_DATA_UAT"


class TestFreshnessReevalPath:
    def test_recorded_gate_tree_drift_is_stale(self, env, tmp_path):
        fp = db_fingerprint(env["store"])
        rec = {"gate": "READY_FOR_REAL_DATA_UAT", "reasons": [],
               "checks": [], "evidence_hashes": {},
               "evaluator_version": "3.3.0",
               "source_commit": "abc123",
               "code_tree_hash": "oldtree0oldtree0",
               "migration_hash": bc.migration_hash(
                   env["store"]._conn),
               "db_fingerprint": fp}
        p = tmp_path / "gate.json"
        p.write_text(json.dumps(rec), encoding="utf-8")
        res = evaluate_gate_from_evidence(
            store=env["store"], recorded_gate_path=p,
            current_head="abc123",
            current_tree_hash="newtree1newtree1",
            current_migration_hash=rec["migration_hash"])
        assert res["gate"] == "STALE_GATE_EVIDENCE"

    def test_recorded_gate_clean_passes_with_stamp(self, env, tmp_path):
        fp = db_fingerprint(env["store"])
        tree = bc.tree_hash(ROOT)
        mig = bc.migration_hash(env["store"]._conn)
        rec = {"gate": "READY_FOR_REAL_DATA_UAT", "reasons": [],
               "checks": [], "evidence_hashes": {},
               "evaluator_version": "3.3.0",
               "source_commit": "abc123",
               "code_tree_hash": tree, "migration_hash": mig,
               "db_fingerprint": fp}
        p = tmp_path / "gate.json"
        p.write_text(json.dumps(rec), encoding="utf-8")
        res = evaluate_gate_from_evidence(
            store=env["store"], recorded_gate_path=p,
            current_head="abc123", current_tree_hash=tree,
            current_migration_hash=mig, worktree_clean=True)
        assert res["gate"] == "READY_FOR_REAL_DATA_UAT"
        assert res.get("freshness_verified_at")

    def test_recorded_gate_dirty_worktree_is_stale(self, env, tmp_path):
        fp = db_fingerprint(env["store"])
        tree = bc.tree_hash(ROOT)
        mig = bc.migration_hash(env["store"]._conn)
        rec = {"gate": "READY_FOR_REAL_DATA_UAT", "reasons": [],
               "checks": [], "evidence_hashes": {},
               "evaluator_version": "3.3.0",
               "source_commit": "abc123",
               "code_tree_hash": tree, "migration_hash": mig,
               "db_fingerprint": fp}
        p = tmp_path / "gate.json"
        p.write_text(json.dumps(rec), encoding="utf-8")
        res = evaluate_gate_from_evidence(
            store=env["store"], recorded_gate_path=p,
            current_head="abc123", current_tree_hash=tree,
            current_migration_hash=mig, worktree_clean=False)
        assert res["gate"] == "STALE_GATE_EVIDENCE"


class TestTestReportGenerator:
    def test_parse_summary(self):
        from scripts.osv51_test_report import parse_summary
        t = "1 failed, 1478 passed, 1 skipped, 6 deselected in 263s"
        c = parse_summary(t)
        assert c == {"failed": 1, "passed": 1478, "skipped": 1,
                     "deselected": 6}
        # 全绿时 pytest 不输出 “0 failed” → failed 必须为 0
        c2 = parse_summary("1479 passed, 1 skipped, 6 deselected")
        assert c2["failed"] == 0 and c2["passed"] == 1479
        # 无摘要（进程异常）→ failed=-1，Gate 必须阻断
        c3 = parse_summary("internal error")
        assert c3["failed"] == -1 and c3["passed"] == -1
