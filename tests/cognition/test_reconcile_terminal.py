"""R2-04（Step 3）：reconcile_cognition 终态对账红测试。

要求：succeeded research 缺 report/evidence、research/business/work
状态漂移、孤儿 step/query/claim 任一出现都必须被报告（G9 fail 依据）。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "reconcile_cognition.py"


def _load_reconcile():
    name = "reconcile_cognition_under_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _mkstore(tmp_path):
    from src.platform.data.store import PlatformStore
    return PlatformStore(tmp_path / "p.sqlite")


def _seed_run(store, *, run_id="rrun-1", biz_id="run-1", work_id="work-1",
              research_status="succeeded", biz_status="succeeded",
              work_status="completed", with_report=True,
              with_evidence=True):
    conn = store._conn
    ts = "2026-08-21T00:00:00Z"
    conn.execute(
        "INSERT INTO business_run_v1 (run_id, work_id, tenant_id,"
        " trigger_type, status, command_kind, created_at, updated_at)"
        " VALUES (?,?,'local','research',?,'research.run',?,?)",
        (biz_id, work_id, biz_status, ts, ts))
    conn.execute(
        "INSERT INTO work_item_v2 (work_id, run_id, status, owner_type,"
        " owner_id, title, created_at, updated_at) VALUES"
        " (?,?,?,'system','research_service','t',?,?)",
        (work_id, biz_id, work_status, ts, ts))
    conn.execute(
        "INSERT INTO research_run_v1 (research_run_id, business_run_id,"
        " question, mode, budget_json, consumed_json, state_json,"
        " status, tenant_id, customer_id, project_id, data_scope,"
        " test_run_id, permission_tags_json, created_by, created_at,"
        " updated_at) VALUES (?,?,'q','lookup','{}','{}','{}',?,"
        "'local','','','operational','','[]','alice',"
        "'2026-08-21T00:00:00Z','2026-08-21T00:00:00Z')",
        (run_id, biz_id, research_status))
    if with_report:
        conn.execute(
            "INSERT INTO research_report_v1 (report_id,"
            " research_run_id, abstain, body_json, claims_json,"
            " citations_json, prompt_version, policy_version,"
            " created_at) VALUES (?,?,0,'{}','[]','[]','s@1','p@1',"
            "'2026-08-21T00:00:00Z')", ("rep-1", run_id))
    if with_evidence:
        conn.execute(
            "INSERT INTO evidence_bundle_v1 (evidence_id, run_id, kind,"
            " source_uri, cas_hash, content_type, producer, created_at)"
            " VALUES (?,?, 'research_run','u','','application/json',"
            " 'research_service','2026-08-21T00:00:00Z')",
            ("evid-1", biz_id))
    conn.commit()


class TestTerminalReconciliation:
    def test_healthy_terminal_run_not_flagged(self, tmp_path):
        mod = _load_reconcile()
        store = _mkstore(tmp_path)
        _seed_run(store)
        out = mod.reconcile(tmp_path / "p.sqlite")
        drift = out["research_terminal_drift"]
        assert drift["succeeded_without_report"] == []
        assert drift["succeeded_without_evidence"] == []
        assert drift["status_drift"] == []
        assert drift["orphan_steps"] == []
        assert drift["orphan_queries"] == []
        assert drift["orphan_claims"] == []
        assert out["gate_ok"] is True
        store.close()

    def test_succeeded_missing_report_and_evidence_flagged(self, tmp_path):
        mod = _load_reconcile()
        store = _mkstore(tmp_path)
        _seed_run(store, with_report=False, with_evidence=False)
        out = mod.reconcile(tmp_path / "p.sqlite")
        drift = out["research_terminal_drift"]
        assert drift["succeeded_without_report"] == ["rrun-1"]
        assert drift["succeeded_without_evidence"] == ["rrun-1"]
        assert out["gate_ok"] is False
        store.close()

    def test_business_work_status_drift_flagged(self, tmp_path):
        mod = _load_reconcile()
        store = _mkstore(tmp_path)
        _seed_run(store, biz_status="failed", work_status="running")
        out = mod.reconcile(tmp_path / "p.sqlite")
        drift = out["research_terminal_drift"]
        assert drift["status_drift"], "research/business/work 漂移必须报告"
        assert out["gate_ok"] is False
        store.close()

    def test_orphan_step_query_claim_flagged(self, tmp_path):
        mod = _load_reconcile()
        store = _mkstore(tmp_path)
        _seed_run(store)
        conn = store._conn
        conn.execute(
            "INSERT INTO research_step_v1 (step_id, research_run_id,"
            " seq, node, status, output_json, started_at) VALUES"
            " ('step-x','rrun-missing',1,'claim','succeeded','{}',"
            "'2026-08-21T00:00:00Z')")
        conn.execute(
            "INSERT INTO research_query_v1 (query_id,"
            " research_run_id, subquestion_id, query_text,"
            " target_kinds_json, strategy, iteration, hits_json,"
            " created_at) VALUES ('q-x','rrun-missing','sq','t','[]',"
            "'hybrid',1,'[]','2026-08-21T00:00:00Z')")
        conn.execute(
            "INSERT INTO research_claim_v1 (claim_id,"
            " research_run_id, subquestion_id, text, claim_type,"
            " importance, support_status, confidence, created_at)"
            " VALUES ('clm-x','rrun-missing','sq','t','fact','high',"
            " 'supported',0.9,'2026-08-21T00:00:00Z')")
        conn.commit()
        out = mod.reconcile(tmp_path / "p.sqlite")
        drift = out["research_terminal_drift"]
        assert drift["orphan_steps"] == ["rrun-missing"]
        assert drift["orphan_queries"] == ["rrun-missing"]
        assert drift["orphan_claims"] == ["rrun-missing"]
        assert out["gate_ok"] is False
        store.close()
