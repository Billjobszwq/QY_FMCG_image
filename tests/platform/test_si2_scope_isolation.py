"""SI2 T1 红测试：UAT Fixture 全域隔离、执行作用域贯通与可信 Gate V2。

对应纠偏指令第五节 T1 的 22 项。本文件先于实现存在（红），
定义目标契约：

- src/platform/scope.py：ExecutionScopeV1 / ScopeResolver /
  ScopePolicy / ScopeViolation / ScopedQuery；
- TestDataService 扩展：create_test_run_context（先建 Test Run 再建
  对象）/ archive_namespace 全域归档 / operational_residue_full；
- Home/Agent/BI/Finance 默认 operational；
- Gate 2.1：HEAD 绑定、STALE、浏览器语义断言、全 Domain 泄漏=0、
  证据数字规范。

不得为通过而删改本文件的断言语义。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.home_center import HomeCenterService
from src.platform.test_data import TestDataService
# 目标契约（T2 实现）：
from src.platform.scope import (ExecutionScopeV1, ScopePolicy,
                                ScopeResolver, ScopeViolation)

ROOT = Path(__file__).resolve().parents[2]


class _OkRecognition:
    def recognize(self, data, conf=0.25):
        return {"count": 0, "products": []}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "si2-pw")
    adapter = _OkRecognition()
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=adapter, probe=lambda spec: None)
    build_profiles_service(bundle)
    store = bundle.store
    return {"store": store, "bundle": bundle,
            "home": HomeCenterService(store),
            "tds": TestDataService(store),
            "resolver": ScopeResolver(store),
            "policy": ScopePolicy()}


def _mk_fixture_customer(store, cid="uatv4-fx-cust", ns="uatv4_t1_fx"):
    store._conn.execute(
        "INSERT INTO md_customer_v1 (customer_id, name, data_scope,"
        " created_at, updated_at) VALUES (?,?,?,"
        " datetime('now'), datetime('now'))",
        (cid, "Fixture 客户", "uat_fixture"))
    store._conn.commit()
    return cid


def _mk_run(store, run_id, work_id, *, customer_id="", scope="uat_fixture",
            test_run_id="uatv4_t1_fx", parent_run_id=None,
            command_kind="workflow.run", status="succeeded"):
    store._conn.execute(
        "INSERT INTO business_run_v1 (run_id, work_id, customer_id,"
        " status, command_kind, data_scope, test_run_id, parent_run_id,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,datetime('now'),"
        "datetime('now'))",
        (run_id, work_id, customer_id, status, command_kind, scope,
         test_run_id, parent_run_id))
    store._conn.execute(
        "INSERT INTO work_item_v2 (work_id, run_id, customer_id, status,"
        " title, data_scope, visibility, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
        (work_id, run_id, customer_id, "done", "t", scope, "history"))
    store._conn.commit()


# --------------------------------------------------------------------
# 1-6：首页/日历/最近对象/活动日志不得出现 fixture
# --------------------------------------------------------------------

class TestHomeFixtureIsolation:
    def test_01_calendar_excludes_fixture_field_tasks(self, env):
        store, home = env["store"], env["home"]
        cid = _mk_fixture_customer(store)
        store._conn.execute(
            "INSERT INTO field_task_v1 (task_id, kind, status,"
            " customer_id, address_id, data_scope, test_run_id,"
            " created_at, updated_at)"
            " VALUES ('ft-fx1','visit','assigned',?,?,?,?,"
            "datetime('now'),datetime('now'))",
            (cid, "addr-fx", "uat_fixture", "uatv4_t1_fx"))
        store._conn.commit()
        events = home.calendar_events()
        assert not any(e.get("ref_id") == "ft-fx1" for e in events), \
            "fixture 外勤任务出现在 operational 首页日历"

    def test_02_calendar_excludes_fixture_survey_assignments(self, env):
        store, home = env["store"], env["home"]
        cid = _mk_fixture_customer(store)
        store._conn.execute(
            "INSERT INTO survey_definition_v1 (survey_id, name, status,"
            " version, spec_json, created_by, data_scope, test_run_id,"
            " created_at, updated_at)"
            " VALUES ('sv-fx1','fx','published',1,'{}','t',?,?,"
            "datetime('now'),datetime('now'))",
            ("uat_fixture", "uatv4_t1_fx"))
        store._conn.execute(
            "INSERT INTO survey_assignment_v1 (assignment_id, survey_id,"
            " survey_version, status, customer_id, data_scope,"
            " test_run_id, created_at, updated_at)"
            " VALUES ('sa-fx1','sv-fx1',1,'assigned',?,?,?,"
            "datetime('now'),datetime('now'))",
            (cid, "uat_fixture", "uatv4_t1_fx"))
        store._conn.commit()
        events = home.calendar_events()
        assert not any(e.get("ref_id") == "sa-fx1" for e in events), \
            "fixture 问卷分配出现在 operational 首页日历"

    def test_03_home_excludes_fixture_user_calendar(self, env):
        store, home = env["store"], env["home"]
        cid = _mk_fixture_customer(store)
        store._conn.execute(
            "INSERT INTO user_calendar_v1 (event_id, actor, title, kind,"
            " starts_at, all_day, customer_id, data_scope, test_run_id,"
            " created_by, created_at, updated_at)"
            " VALUES ('cal-fx1','a','UAT 日程','user',"
            "'2026-08-20T09:00:00Z',0,?,?,?,'a',datetime('now'),"
            "datetime('now'))",
            (cid, "uat_fixture", "uatv4_t1_fx"))
        store._conn.commit()
        events = home.calendar_events()
        assert not any(e.get("event_id") == "cal-fx1" for e in events), \
            "fixture 用户日程出现在 operational 首页"

    def test_04_recent_objects_excludes_fixture_customer_project(self, env):
        store, home = env["store"], env["home"]
        cid = _mk_fixture_customer(store)
        store._conn.execute(
            "INSERT INTO md_project_v1 (project_id, customer_id, name,"
            " data_scope, test_run_id, created_at, updated_at)"
            " VALUES ('prj-fx1',?,?,?,?,"
            "datetime('now'),datetime('now'))",
            (cid, "Fixture 项目", "uat_fixture", "uatv4_t1_fx"))
        store._conn.commit()
        recent = home.recent_objects()
        assert cid not in {c["id"] for c in recent["customers"]}
        assert "prj-fx1" not in {p["id"] for p in recent["projects"]}, \
            "fixture Customer/Project 出现在 operational 最近对象"

    def test_05_recent_objects_excludes_fixture_workflow_bi(self, env):
        store, home = env["store"], env["home"]
        store._conn.execute(
            "INSERT INTO workflow_definition_v1 (definition_id, name,"
            " status, version, spec_json, spec_hash, created_by,"
            " data_scope, test_run_id, created_at, updated_at)"
            " VALUES ('wf-fx1','UAT V4 fx','published',1,'{}','h','t',"
            "'uat_fixture','uatv4_t1_fx',datetime('now'),datetime('now'))")
        store._conn.execute(
            "INSERT INTO bi_report_spec_v1 (spec_id, name, status,"
            " version, created_by, data_scope, test_run_id, created_at,"
            " updated_at) VALUES ('bi-fx1','UAT fx 报表','draft',1,'t',"
            "'uat_fixture','uatv4_t1_fx',datetime('now'),datetime('now'))")
        store._conn.commit()
        recent = home.recent_objects()
        assert "wf-fx1" not in {w["id"] for w in recent["workflows"]}
        assert "bi-fx1" not in {r["id"] for r in recent["reports"]}, \
            "fixture Workflow/BI 出现在 operational 最近对象"

    def test_06_activity_excludes_fixture_events(self, env):
        store, home = env["store"], env["home"]
        _mk_run(store, "run-fx-ev", "work-fx-ev")
        store.emit_event(
            event_id="evt-fx1", event_type="run.succeeded",
            run_id="run-fx-ev", work_id="work-fx-ev",
            correlation_id="corr-fx", actor_type="system",
            actor_id="t", payload={})
        acts = home.activity()
        assert not any(a["run_id"] == "run-fx-ev" for a in acts), \
            "fixture 事件出现在 operational 活动日志"


# --------------------------------------------------------------------
# 7-9：Supervisor/BI/Finance 默认不混入 fixture
# --------------------------------------------------------------------

class TestAgentBiFinanceIsolation:
    def test_07_supervisor_default_query_excludes_fixture(self, env):
        from src.platform.agents.runtime import AgentRuntime
        store = env["store"]
        cid = _mk_fixture_customer(store)
        store._conn.execute(
            "INSERT INTO md_project_v1 (project_id, customer_id, name,"
            " data_scope, test_run_id, created_at, updated_at)"
            " VALUES ('prj-fx2',?,?,?,?,datetime('now'),datetime('now'))",
            (cid, "fx", "uat_fixture", "uatv4_t1_fx"))
        store._conn.execute(
            "INSERT INTO md_project_v1 (project_id, customer_id, name,"
            " data_scope, created_at, updated_at)"
            " VALUES ('prj-op1','real-cust','real','operational',"
            "datetime('now'),datetime('now'))")
        store._conn.commit()
        rt = AgentRuntime(store)
        out = rt._exec_tool("master.data.summary", {}, actor="sup",
                            customer_id="")
        assert out["projects"] == 1, \
            "Supervisor 默认查询汇总了 fixture 项目"

    def test_08_bi_default_aggregation_excludes_fixture(self, env):
        store = env["store"]
        from src.platform.analytics import AnalyticsService
        _mk_run(store, "run-fx-bi", "work-fx-bi",
                customer_id="uatv4-fx-cust")
        _mk_fixture_customer(store)
        store.insert_usage_event_v2(
            usage_id="usage-fx1", unit="recognition_photo", quantity=9,
            run_id="run-fx-bi", work_id="work-fx-bi", node="recognition",
            capability="vision.recognition.create",
            customer_id="uatv4-fx-cust", project_id="",
            source_evidence="recognition_task:t",
            data_scope="uat_fixture", test_run_id="uatv4_t1_fx")
        store.insert_usage_event_v2(
            usage_id="usage-op1", unit="recognition_photo", quantity=3,
            run_id="run-op-bi", work_id="work-op-bi", node="recognition",
            capability="vision.recognition.create",
            customer_id="real-cust", project_id="",
            source_evidence="recognition_task:t")
        svc = AnalyticsService(store)
        out = svc.evaluate_metric("recognition.photos",
                                  customer_id="uatv4-fx-cust")
        val = out["value"] if isinstance(out, dict) else out
        assert val == 0, f"BI 默认聚合混入 fixture：{val}"

    def test_09_finance_billing_excludes_fixture(self, env):
        store = env["store"]
        from src.platform.finance import FinanceService
        _mk_fixture_customer(store)
        _mk_run(store, "run-fx-fin", "work-fx-fin",
                customer_id="uatv4-fx-cust")
        store.insert_usage_event_v2(
            usage_id="usage-fx2", unit="recognition_photo", quantity=50,
            run_id="run-fx-fin", work_id="work-fx-fin", node="recognition",
            capability="vision.recognition.create",
            customer_id="uatv4-fx-cust", project_id="",
            source_evidence="recognition_task:t",
            data_scope="uat_fixture", test_run_id="uatv4_t1_fx")
        svc = FinanceService(store)
        svc.seed_rate_cards()
        from datetime import datetime, timezone
        period = datetime.now(timezone.utc).strftime("%Y-%m")
        inv = svc.generate_invoice(customer_id="uatv4-fx-cust",
                                   period=period, actor="fin",
                                   include_subscription=False)
        assert float(inv["total"]) == 0.0, \
            f"fixture Usage 混入客户账单：total={inv['total']}"


# --------------------------------------------------------------------
# 10-13：作用域继承与 fail-closed
# --------------------------------------------------------------------

class TestScopeInheritance:
    def test_10_agent_child_run_inherits_test_run_id(self, env):
        store = env["store"]
        from src.platform.agents.runtime import AgentRuntime
        cid = _mk_fixture_customer(store)
        _mk_run(store, "run-fx-parent", "work-fx-parent",
                customer_id=cid, status="running",
                command_kind="workflow.run")
        rt = AgentRuntime(store)
        try:
            rt.invoke("supervisor", "汇总", actor="tester",
                      customer_id=cid, parent_run_id="run-fx-parent")
        except Exception:
            pass  # 定义缺失等失败不影响本断言：看已写入的 run
        child = store._conn.execute(
            "SELECT data_scope, test_run_id FROM business_run_v1 WHERE"
            " parent_run_id='run-fx-parent'").fetchone()
        assert child is not None, "Agent 未创建子 BusinessRun"
        assert child["data_scope"] == "uat_fixture"
        assert child["test_run_id"] == "uatv4_t1_fx", \
            "Agent 子 Run 未继承 test_run_id"

    def test_11_command_child_run_inherits_test_run_id(self, env):
        store, bundle = env["store"], env["bundle"]
        from src.platform.control_plane import CommandGateway
        cid = _mk_fixture_customer(store)
        _mk_run(store, "run-fx-cmd", "work-fx-cmd", customer_id=cid,
                status="running")
        gw = CommandGateway(store, None,
                            recognition_adapter=_OkRecognition())
        import base64
        out = gw.submit(
            command_kind="vision.recognition.create",
            params={"images": [["a.jpg", base64.b64encode(b"x").decode()]]},
            actor="tester", source="api", customer_id=cid,
            parent_run_id="run-fx-cmd")
        run = store.get_business_run(out["run_id"])
        assert run["data_scope"] == "uat_fixture"
        assert run["test_run_id"] == "uatv4_t1_fx", \
            "command 子 Run 未继承 test_run_id"

    def test_12_workflow_recovery_paths_keep_scope(self, env):
        """workflow 节点执行/timer/branch 行必须继承父 run scope。"""
        store = env["store"]
        cid = _mk_fixture_customer(store)
        _mk_run(store, "run-fx-wf", "work-fx-wf", customer_id=cid,
                status="running")
        store._conn.execute(
            "INSERT INTO workflow_node_execution_v1 (run_id, node_id,"
            " node_type, status, data_scope, test_run_id, started_at)"
            " VALUES ('run-fx-wf','n1','transform','running',"
            "'uat_fixture','uatv4_t1_fx',datetime('now'))")
        store._conn.execute(
            "INSERT INTO workflow_timer_v1 (timer_id, run_id, node_id,"
            " fire_at, seconds, status, data_scope, test_run_id,"
            " created_at)"
            " VALUES ('tm-fx1','run-fx-wf','n2',"
            "'2026-08-20T00:00:00Z',5,'pending','uat_fixture',"
            "'uatv4_t1_fx',datetime('now'))")
        store._conn.commit()
        from src.platform.scope import ScopedQuery
        leaked = ScopedQuery(store).recovery_residue()
        assert leaked == 0, \
            f"recovery 路径丢失作用域（泄漏 {leaked}）"

    def test_13_fixture_parent_operational_child_fail_closed(self, env):
        policy = env["policy"]
        parent = ExecutionScopeV1(data_scope="uat_fixture",
                                  test_run_id="uatv4_t1_fx",
                                  customer_id="uatv4-fx-cust")
        child = ExecutionScopeV1(data_scope="operational",
                                 test_run_id="",
                                 customer_id="real-cust")
        with pytest.raises(ScopeViolation) as ei:
            policy.check_child(parent, child)
        assert ei.value.code.startswith("SCOPE_CONFLICT")


# --------------------------------------------------------------------
# 14-17：Gate 阻断与归档语义
# --------------------------------------------------------------------

class TestArchiveAndGateLineage:
    def test_14_missing_test_run_id_blocks_gate(self, env):
        store = env["store"]
        _mk_run(store, "run-fx-miss", "work-fx-miss",
                test_run_id="")  # fixture 但缺 test_run_id
        from src.platform.gate_evaluator import evaluate_gate_from_evidence
        res = evaluate_gate_from_evidence(
            store=store, uat_report_path=None,
            browser_report_path=None, issue_ledger_path=None,
            test_report_path=None, service_health=None,
            source_commit="x")
        assert res["gate"] != "READY_FOR_REAL_DATA_UAT"
        assert any("SCOPE_LINEAGE" in (r or "") for r in res["reasons"]) \
            or res["gate"] == "BLOCKED_BY_SCOPE_LINEAGE", \
            "test_run_id 缺失未阻断 Gate"

    def test_15_archive_all_domain_residue_zero(self, env):
        store, tds = env["store"], env["tds"]
        cid = _mk_fixture_customer(store, ns="uatv4_t1_ar")
        _mk_run(store, "run-ar1", "work-ar1", customer_id=cid,
                test_run_id="uatv4_t1_ar", status="running")
        store._conn.execute(
            "INSERT INTO field_task_v1 (task_id, kind, status,"
            " customer_id, address_id, data_scope, test_run_id,"
            " created_at, updated_at) VALUES"
            " ('ft-ar1','visit','assigned',?,?,?,?,datetime('now'),"
            "datetime('now'))",
            (cid, "addr-ar", "uat_fixture", "uatv4_t1_ar"))
        store._conn.execute(
            "INSERT INTO survey_assignment_v1 (assignment_id,"
            " survey_id, survey_version, status, customer_id, data_scope,"
            " test_run_id, created_at, updated_at)"
            " VALUES ('sa-ar1','sv',1,'assigned',?,?,?,"
            "datetime('now'),datetime('now'))",
            (cid, "uat_fixture", "uatv4_t1_ar"))
        store._conn.commit()
        tds.archive_namespace("uatv4_t1_ar")
        assert tds.operational_residue_full() == {}, \
            "归档后全 Domain operational fixture 残留不为 0"

    def test_16_operational_named_uat_not_archived(self, env):
        store, tds = env["store"], env["tds"]
        store._conn.execute(
            "INSERT INTO md_customer_v1 (customer_id, name, data_scope,"
            " created_at, updated_at) VALUES ('real-uat-name',"
            "'UAT 实业有限公司','operational',datetime('now'),"
            "datetime('now'))")
        store._conn.execute(
            "INSERT INTO business_run_v1 (run_id, work_id, customer_id,"
            " status, command_kind, data_scope, created_at, updated_at)"
            " VALUES ('run-real-uat','work-real-uat','real-uat-name',"
            "'succeeded','workflow.run','operational',datetime('now'),"
            "datetime('now'))")
        store._conn.commit()
        tds.archive_namespace("uatv4_whatever")
        row = store.get_business_run("run-real-uat")
        assert row["data_scope"] == "operational", \
            "名称含 UAT 的 operational 对象被错误归档"

    def test_17_fixture_unnamed_is_isolated(self, env):
        store, tds = env["store"], env["tds"]
        store._conn.execute(
            "INSERT INTO md_customer_v1 (customer_id, name, data_scope,"
            " created_at, updated_at) VALUES ('plain-cust',"
            "'普通名称客户','uat_fixture',datetime('now'),"
            "datetime('now'))")
        store._conn.execute(
            "INSERT INTO business_run_v1 (run_id, work_id, customer_id,"
            " status, command_kind, data_scope, test_run_id, created_at,"
            " updated_at) VALUES ('run-plain','work-plain','plain-cust',"
            "'running','workflow.run','uat_fixture','uatv4_ns9',"
            "datetime('now'),datetime('now'))")
        store._conn.commit()
        home = env["home"]
        assert "plain-cust" not in {
            c["id"] for c in home.recent_objects()["customers"]}, \
            "名称不含 UAT 但 scope=uat_fixture 的对象未被隔离"


# --------------------------------------------------------------------
# 18-21：Gate 2.1 语义/绑定/证据数字
# --------------------------------------------------------------------

class TestGateV21:
    def _browser_report(self, tmp_path, actual="run-OTHER"):
        p = tmp_path / "browser_evidence.json"
        p.write_text(json.dumps({
            "files": [], "console_errors_unexplained": 0,
            "pages": [{"route": "/workflows",
                       "expected_object_id": "wf-44f211a575",
                       "actual_object_id": actual,
                       "assertion": False}]}), encoding="utf-8")
        return p

    def test_18_browser_object_id_mismatch_blocks(self, env, tmp_path):
        from src.platform.gate_evaluator import evaluate_gate_from_evidence
        p = self._browser_report(tmp_path, actual="run-OTHER")
        res = evaluate_gate_from_evidence(
            store=env["store"], browser_report_path=str(p),
            source_commit="x")
        assert res["gate"] == "BLOCKED_BY_BROWSER_SEMANTICS", \
            f"浏览器对象 ID 不一致未阻断：{res['gate']}"

    def test_19_gate_source_commit_mismatch_stale(self, env, tmp_path):
        from src.platform.gate_evaluator import evaluate_gate_from_evidence
        res = evaluate_gate_from_evidence(
            store=env["store"], source_commit="6664022f",
            current_head="9f3554e7")
        assert res["gate"] == "STALE_GATE_EVIDENCE", \
            "source_commit 与 HEAD 不一致未判定 STALE"

    def test_20_gate_code_tree_change_stale(self, env):
        from src.platform.gate_evaluator import evaluate_gate_from_evidence
        res = evaluate_gate_from_evidence(
            store=env["store"], source_commit="same",
            current_head="same",
            recorded_tree_hash="hash-before",
            current_tree_hash="hash-after")
        assert res["gate"] == "STALE_GATE_EVIDENCE", \
            "tracked 代码变化未判定 STALE"

    def test_21_residue_zero_evidence_shows_zero(self, env, tmp_path):
        from src.platform.gate_evaluator import evaluate_gate_from_evidence
        rep = tmp_path / "report.json"
        rep.write_text(json.dumps({
            "checks": [], "failed": 0,
            "workflow_node_types": ["trigger", "transform", "condition",
                                    "wait", "parallel", "join", "loop",
                                    "human_approval", "agent", "model"],
            "storefront": {"negative_rejected": True,
                           "positive_submitted": True},
            "parallel": {"wall_seconds": 2.0, "terminal": "succeeded"},
            "anomaly_chain": {"anomaly_id": "a", "follow_up": "f",
                              "human_answer": True, "resolved": True,
                              "report_versions": 2},
            "agent_failure": {"failed_run": "r", "evidence": "e",
                              "usage_recorded": True},
            "rate_limit": {"denied_429": True},
            "current_bundle": "prod_v4_best_r1",
            "training_processes": 0,
            "operational_residue": 0,
            "usage_lineage": {"total": 1, "linked": 1}}),
            encoding="utf-8")
        res = evaluate_gate_from_evidence(
            store=env["store"], uat_report_path=str(rep),
            source_commit="same", current_head="same")
        chk = {c["check"]: c for c in res["checks"]}
        assert chk["operational_uat_residue_zero"]["evidence"] == "0", \
            "residue=0 的 evidence 未显示数字 0"


# --------------------------------------------------------------------
# 22：pytest collection warning
# --------------------------------------------------------------------

class TestWarnings:
    def test_22_testdataservice_no_collection_warning(self):
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--collect-only",
             str(ROOT / "src" / "platform" / "test_data.py")],
            capture_output=True, text=True, cwd=str(ROOT), timeout=120)
        assert "PytestCollectionWarning" not in proc.stdout \
            + proc.stderr, "TestDataService 仍触发 pytest 收集警告"
