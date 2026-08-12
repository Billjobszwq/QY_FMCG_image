"""SI3 红测试：Scope Integrity V3（真实运营投影与 Gate 3.0）。

对应纠偏指令第三节 20 项现状复现与第四节 Scope Graph 契约。
本文件先于修复存在（红），定义目标契约；不得为通过而删改断言。

根因映射（见 docs/implementation/agentic-business-os-scope-integrity-v3/
00-LIVE-AUDIT.md）：
- 隔离只看行自身列（OPERATIONAL_FILTER），不追父链 effective scope；
- scope 绑定"先 commit 再 bind"，非事务原子；
- test_run_id 不校验 uat_test_run_v1 存在/current；
- INSERT OR REPLACE 覆盖 Test Run namespace；
- scanner except/continue 吞异常放行；
- /control/gate 只读静态 gate.json，无 freshness。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.home_center import HomeCenterService
from src.platform.test_data import FixtureTestDataService
from src.platform.scope import (ScopePolicy, ScopeResolver,
                                ScopeViolation, ScopedQuery,
                                ExecutionScopeV1)

NS = "uatv5_si3_red"


class _OkRecognition:
    def recognize(self, data, conf=0.25):
        return {"count": 0, "products": []}


class _FakeProfiles:
    def list_profiles(self):
        return [{"profile_id": "production_legacy", "status": "enabled",
                 "blockers": [], "components": []}]


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "si3-pw")
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=_OkRecognition(), probe=lambda spec: None)
    build_profiles_service(bundle)
    store = bundle.store
    tds = FixtureTestDataService(store)
    # 正规 Test Run 上下文（current）
    tds.create_test_run_context(NS, customer_ids=[])
    return {"store": store, "bundle": bundle, "tds": tds,
            "home": HomeCenterService(store),
            "resolver": ScopeResolver(store),
            "policy": ScopePolicy()}


def _mk_fixture_customer(store, cid="si3-fx-cust"):
    store._conn.execute(
        "INSERT INTO md_customer_v1 (customer_id, name, data_scope,"
        " test_run_id, is_test_fixture, created_at, updated_at)"
        " VALUES (?,?,?,?,1,datetime('now'),datetime('now'))",
        (cid, "SI3 fixture 客户", "uat_fixture", NS))
    store._conn.commit()
    return cid


def _mk_fixture_run(store, run_id="run-fx1", work_id="work-fx1",
                    customer_id="si3-fx-cust", status="running"):
    store._conn.execute(
        "INSERT INTO business_run_v1 (run_id, work_id, customer_id,"
        " status, command_kind, data_scope, test_run_id, created_at,"
        " updated_at) VALUES (?,?,?,?,?,?,?,datetime('now'),"
        "datetime('now'))",
        (run_id, work_id, customer_id, status, "workflow.run",
         "uat_fixture", NS))
    store._conn.commit()
    return run_id


# --------------------------------------------------------------------
# R1：fixture response → media 必须继承 fixture（现状 24 条泄漏）
# --------------------------------------------------------------------

class TestMediaInheritance:
    def test_r01_media_inherits_response_scope(self, env):
        store = env["store"]
        from src.platform.survey import SurveyService
        cid = _mk_fixture_customer(store)
        svc = SurveyService(store)
        store._conn.execute(
            "INSERT INTO survey_definition_v1 (survey_id, name,"
            " status, version, spec_json, created_by, data_scope,"
            " test_run_id, created_at, updated_at)"
            " VALUES ('sv-fx','fx','published',1,?,'t',?,?,"
            "datetime('now'),datetime('now'))",
            (json.dumps({"questions": [{"id": "q1", "type": "photo"}]}),
             "uat_fixture", NS))
        store._conn.execute(
            "INSERT INTO survey_assignment_v1 (assignment_id,"
            " survey_id, survey_version, status, customer_id,"
            " data_scope, test_run_id, created_at, updated_at)"
            " VALUES ('sa-fx','sv-fx',1,'assigned',?,?,?,"
            "datetime('now'),datetime('now'))",
            (cid, "uat_fixture", NS))
        store._conn.commit()
        resp = svc.start_response(assignment_id="sa-fx",
                                  respondent="tester")
        m = svc.attach_media(response_id=resp["response_id"],
                             question_id="q1", actor="tester")
        row = store._conn.execute(
            "SELECT data_scope, test_run_id FROM survey_media_v1"
            " WHERE media_id=?", (m["media_id"],)).fetchone()
        assert row["data_scope"] == "uat_fixture", \
            "fixture response 的 media 被标 operational（指令 4.12）"
        assert row["test_run_id"] == NS


# --------------------------------------------------------------------
# R2：fixture Run 的 Work 不得出现在 operational 投影（现状 8）
# --------------------------------------------------------------------

class TestWorkInheritance:
    def test_r02_work_under_fixture_run_hidden_from_home(self, env):
        store, home = env["store"], env["home"]
        _mk_fixture_customer(store)
        _mk_fixture_run(store)
        # 真实泄漏形态：work 自身无 scope 列值（NULL→operational），
        # 但父 run 是 fixture——effective scope 必须为 fixture。
        store._conn.execute(
            "INSERT INTO work_item_v2 (work_id, run_id, customer_id,"
            " status, title, visibility, created_at, updated_at)"
            " VALUES ('work-fx1','run-fx1','si3-fx-cust','running',"
            " 'UAT 任务','current',datetime('now'),datetime('now'))")
        store._conn.commit()
        proj = store.rebuild_work_projection()
        assert not any(it["work_id"] == "work-fx1"
                       for it in proj["items"]), \
            "fixture Run 的 Work 出现在 operational current 投影"
        alerts = home.agent_alerts()
        assert not any(a.get("ref_id") == "work-fx1" for a in alerts)


# --------------------------------------------------------------------
# R3：recognition_task 继承 Run scope（现状 5）
# --------------------------------------------------------------------

class TestRecognitionInheritance:
    def test_r03_recognition_task_inherits_run_scope(self, env):
        store, bundle = env["store"], env["bundle"]
        from src.platform.control_plane import CommandGateway
        import base64
        cid = _mk_fixture_customer(store)
        _mk_fixture_run(store, run_id="run-fx-rec",
                        work_id="work-fx-rec")
        gw = CommandGateway(store, _FakeProfiles(),
                            recognition_adapter=_OkRecognition())
        out = gw.submit(
            command_kind="vision.recognition.create",
            params={"images": [["a.jpg",
                                base64.b64encode(b"x").decode()]]},
            actor="tester", source="api", customer_id=cid,
            parent_run_id="run-fx-rec")
        row = store._conn.execute(
            "SELECT data_scope, test_run_id FROM recognition_task"
            " WHERE run_id=?", (out["run_id"],)).fetchone()
        assert row is not None
        assert row["data_scope"] == "uat_fixture", \
            "fixture Run 触发的识别任务被标 operational（指令 4.11）"
        assert row["test_run_id"] == NS


# --------------------------------------------------------------------
# R4：Agent 工具创建的 BI 草稿继承 Agent Run scope（现状 5+）
# --------------------------------------------------------------------

class TestAgentToolInheritance:
    def test_r04_agent_bi_draft_inherits_scope(self, env):
        store = env["store"]
        from src.platform.agents.runtime import AgentRuntime
        from src.platform.analytics import AnalyticsService
        cid = _mk_fixture_customer(store)
        _mk_fixture_run(store, run_id="run-fx-ag",
                        work_id="work-fx-ag")
        rt = AgentRuntime(store, analytics=AnalyticsService(store))
        rt.invoke("analytics_agent", "生成报表草稿", actor="tester",
                  customer_id=cid, parent_run_id="run-fx-ag")
        row = store._conn.execute(
            "SELECT data_scope, test_run_id FROM bi_report_spec_v1"
            " ORDER BY created_at DESC LIMIT 1").fetchone()
        assert row is not None
        assert row["data_scope"] == "uat_fixture", \
            "fixture Agent Run 创建的 BI 草稿被标 operational"
        assert row["test_run_id"] == NS


# --------------------------------------------------------------------
# R5：失败 Agent 先解析 scope（现状 5 轮 operational 失败账本）
# --------------------------------------------------------------------

class TestFailedAgentScope:
    def test_r05_missing_agent_failure_keeps_fixture_scope(self, env):
        """真实泄漏形态：fixture 客户直调（无 parent_run）且无
        test_run_id → resolver 抛错被吞，失败账本落 operational。"""
        store = env["store"]
        from src.platform.agents.runtime import (AgentRuntime,
                                                 AgentRuntimeError)
        cid = _mk_fixture_customer(store)
        rt = AgentRuntime(store)
        with pytest.raises(AgentRuntimeError):
            rt.invoke("no_such_agent_si3", "x", actor="tester",
                      customer_id=cid)
        row = store._conn.execute(
            "SELECT data_scope, test_run_id FROM business_run_v1"
            " WHERE command_kind='agent.invoke' ORDER BY created_at"
            " DESC LIMIT 1").fetchone()
        assert row is not None
        assert row["data_scope"] == "uat_fixture", \
            "失败 Agent Run 被标 operational（指令 4.10）"
        assert row["test_run_id"], \
            "fixture 客户下失败 Agent 账本缺 test_run_id"
        usage = store._conn.execute(
            "SELECT count(*) c FROM usage_event_v2 WHERE"
            " COALESCE(data_scope,'operational')='operational' AND"
            " customer_id=?", (cid,)).fetchone()["c"]
        assert usage == 0, "失败 Agent 的 Usage 计入运营账本"


# --------------------------------------------------------------------
# R6：Usage API 不得计入 fixture effective scope（现状 ~80 条）
# --------------------------------------------------------------------

class TestUsageApiIsolation:
    def test_r06_usage_summary_excludes_fixture(self, env, tmp_path,
                                                monkeypatch):
        from fastapi.testclient import TestClient
        from src.platform.api.app import create_app
        store, bundle = env["store"], env["bundle"]
        _mk_fixture_customer(store)
        _mk_fixture_run(store, run_id="run-fx-usage",
                        work_id="work-fx-usage", status="succeeded")
        store.insert_usage_event_v2(
            usage_id="u-fx1", unit="recognition_photo", quantity=7,
            run_id="run-fx-usage", work_id="work-fx-usage",
            node="recognition", capability="vision.recognition.create",
            customer_id="si3-fx-cust", project_id="",
            source_evidence="recognition_task:t")
        store.insert_usage_event_v2(
            usage_id="u-op1", unit="recognition_photo", quantity=2,
            run_id="run-op1", work_id="work-op1", node="recognition",
            capability="vision.recognition.create",
            customer_id="real-cust", project_id="",
            source_evidence="recognition_task:t")
        app = create_app(services=(), probe=lambda spec: None,
                         bundle=bundle,
                         recognition_adapter=_OkRecognition(),
                         web_dist=Path("/nonexistent-dist"))
        c = TestClient(app)
        r = c.post("/api/v1/auth/login",
                   json={"username": "admin", "password": "si3-pw"})
        s = c.get("/api/v1/usage/summary").json()
        total = sum(u["total"] for u in s["by_unit"])
        assert total == 2, \
            f"Usage 汇总计入 fixture（应为 2，实际 {total}）"
        rows = c.get("/api/v1/usage/rows").json()["rows"]
        assert all(r["usage_id"] != "u-fx1" for r in rows), \
            "Usage rows 返回 fixture 行"


# --------------------------------------------------------------------
# R7：is_test_fixture 客户结构性 fixture（现状 1 条 operational）
# --------------------------------------------------------------------

class TestCustomerFixtureFlag:
    def test_r07_fixture_flag_customer_structural(self, env):
        store = env["store"]
        from src.platform.iam import IAMService, MasterDataService
        iam = IAMService(store)
        md = MasterDataService(store, iam=iam)
        md.create_customer(customer_id="si3-flag-cust",
                           name="带测试标记客户",
                           is_test_fixture=True, created_by="admin",
                           test_run_id=NS)
        row = store._conn.execute(
            "SELECT COALESCE(data_scope,'operational') ds FROM"
            " md_customer_v1 WHERE customer_id='si3-flag-cust'"
        ).fetchone()
        assert row["ds"] in ("uat_fixture", "demo_fixture"), \
            "is_test_fixture=1 客户仍为 operational（指令三.7）"
        listed = md.list_customers()
        assert not any(c["customer_id"] == "si3-flag-cust"
                       for c in listed), \
            "默认客户列表返回 fixture 客户（指令三.11）"


# --------------------------------------------------------------------
# R8：terminal Run 下节点必须收敛（现状 39 条漂移）
# --------------------------------------------------------------------

class TestTerminalConvergence:
    def test_r08_cancel_run_converges_nodes(self, env):
        store, bundle = env["store"], env["bundle"]
        from src.platform.workflow import WorkflowService
        store._conn.execute(
            "INSERT INTO workflow_definition_v1 (definition_id, name,"
            " status, version, spec_json, spec_hash, created_by,"
            " created_at, updated_at)"
            " VALUES ('wf-si3','si3','published',1,?,'h','t',"
            "datetime('now'),datetime('now'))",
            (json.dumps({"trigger": {"type": "manual"},
                         "variables": {},
                         "nodes": [{"id": "start", "type": "trigger"},
                                   {"id": "ap1", "type": "human_approval"},
                                   {"id": "end", "type": "end"}],
                         "edges": [{"from": "start", "to": "ap1"},
                                   {"from": "ap1", "to": "end"}]}),))
        store._conn.commit()
        wf = WorkflowService(store, bundle.capabilities, None)
        run = wf.start_run("wf-si3", inputs={}, actor="tester")["run"]
        # 制造残留 running 节点（真实泄漏形态：终态前未收敛）
        store._conn.execute(
            "UPDATE workflow_node_execution_v1 SET status='running'"
            " WHERE run_id=? AND node_id='ap1'", (run["run_id"],))
        store._conn.commit()
        wf.cancel_run(run["run_id"], actor="tester")
        n = store._conn.execute(
            "SELECT count(*) c FROM workflow_node_execution_v1 WHERE"
            " run_id=? AND status IN ('running','pending','queued',"
            "'waiting','paused')", (run["run_id"],)).fetchone()["c"]
        assert n == 0, "cancelled Run 残留 non-terminal 节点（指令八）"


# --------------------------------------------------------------------
# R9/R10：Test Run fail-closed 与 namespace 不可覆盖
# --------------------------------------------------------------------

class TestTestRunRegistry:
    def test_r09_missing_or_archived_test_run_rejected(self, env):
        resolver, store = env["resolver"], env["store"]
        with pytest.raises(ScopeViolation):
            resolver.resolve(test_run_id="no_such_test_run_si3")
        env["tds"].archive_namespace(NS)
        with pytest.raises(ScopeViolation):
            resolver.resolve(test_run_id=NS)

    def test_r10_test_run_namespace_immutable(self, env):
        tds = env["tds"]
        tds.create_test_run_context(NS + "_b",
                                    customer_ids=["c-a"])
        with pytest.raises(Exception) as ei:
            tds.create_test_run_context(NS + "_b",
                                        customer_ids=["c-other"])
        assert "409" in str(ei.value) or "conflict" in \
            str(ei.value).lower() or "存在" in str(ei.value), \
            "重复 namespace 不同内容应 409，而非 INSERT OR REPLACE"


# --------------------------------------------------------------------
# R11/R12：父子一致性扩展与绑定原子性
# --------------------------------------------------------------------

class TestPolicyAndAtomicity:
    def test_r11_parent_child_customer_conflict_rejected(self, env):
        policy = env["policy"]
        parent = ExecutionScopeV1(data_scope="uat_fixture",
                                  test_run_id=NS,
                                  customer_id="cust-A")
        child = ExecutionScopeV1(data_scope="uat_fixture",
                                 test_run_id=NS, customer_id="cust-B")
        with pytest.raises(ScopeViolation):
            policy.check_child(parent, child)

    def test_r12_scope_binding_atomic_with_create(self, env):
        """指令 4.8：对象创建与 scope 写入必须同一事务；禁止先
        commit 再 bind。V3 必须提供原子创建入口：test_run 无效时
        对象根本不得落库。"""
        from src.platform.scope import create_scoped_customer
        store = env["store"]
        with pytest.raises(ScopeViolation):
            create_scoped_customer(
                store, customer_id="si3-atomic", name="t",
                test_run_id="no_such_test_run_si3", actor="admin")
        row = store._conn.execute(
            "SELECT count(*) c FROM md_customer_v1 WHERE"
            " customer_id='si3-atomic'").fetchone()["c"]
        assert row == 0, \
            "scope 绑定失败后业务对象已提交（先 commit 再 bind）"


# --------------------------------------------------------------------
# R13/R14/R15：Gate 3.0（scanner fail-fast / freshness / 父链泄漏）
# --------------------------------------------------------------------

class TestGate3:
    def test_r13_scanner_exception_must_block(self, env):
        store = env["store"]
        # 破坏一张被扫描表的结构（删列不可行则重建缺列表）
        store._conn.execute(
            "CREATE TABLE scope_scan_probe_v1 (id TEXT)")
        store._conn.commit()
        sq = ScopedQuery(store)
        # 让 _SCOPED_TABLES 中出现不存在的表：scanner 必须阻断而非吞
        import src.platform.scope as scope_mod
        orig = scope_mod._SCOPED_TABLES
        scope_mod._SCOPED_TABLES = orig + ("no_such_table_si3",)
        try:
            with pytest.raises(Exception):
                sq.fixture_missing_test_run()
        finally:
            scope_mod._SCOPED_TABLES = orig

    def test_r14_gate_stale_after_db_change(self, env, tmp_path):
        from src.platform.gate_evaluator import \
            evaluate_gate_from_evidence
        store = env["store"]
        gate_path = tmp_path / "gate.json"
        res = evaluate_gate_from_evidence(
            store=store, out_path=gate_path)
        # 生成 gate.json 后 DB 发生变化 → 实时读取必须 STALE/BLOCKED
        store._conn.execute(
            "INSERT INTO md_customer_v1 (customer_id, name,"
            " created_at, updated_at) VALUES ('post-gate','t',"
            "datetime('now'),datetime('now'))")
        store._conn.commit()
        res2 = evaluate_gate_from_evidence(
            store=store, recorded_gate_path=gate_path) \
            if "recorded_gate_path" in \
            evaluate_gate_from_evidence.__code__.co_varnames else None
        assert res2 is not None, \
            "Gate 评估器不支持 freshness 复评（指令九.4）"
        assert res2["gate"] != "READY_FOR_REAL_DATA_UAT", \
            "DB 已变化但 Gate 仍 READY（指令三.18）"

    def test_r15_gate_blocks_parent_chain_leakage(self, env):
        store = env["store"]
        _mk_fixture_customer(store)
        _mk_fixture_run(store, run_id="run-fx-gate",
                        work_id="work-fx-gate", status="succeeded")
        store._conn.execute(
            "INSERT INTO work_item_v2 (work_id, run_id, customer_id,"
            " status, title, visibility, created_at, updated_at)"
            " VALUES ('work-fx-gate','run-fx-gate','si3-fx-cust',"
            "'done','t','current',datetime('now'),datetime('now'))")
        store._conn.commit()
        # 泄漏扫描必须直接看见父链泄漏（work 自身无 scope 列值，
        # 父 run 为 fixture）；而非仅依赖行自身列。
        leak = ScopedQuery(store).operational_leakage()
        assert any("work_item" in t for t in leak), \
            "泄漏扫描看不见父链泄漏（只看行自身列，指令三.13 假阳性根源）"
        from src.platform.gate_evaluator import \
            evaluate_gate_from_evidence
        res = evaluate_gate_from_evidence(store=store)
        assert res["gate"] != "READY_FOR_REAL_DATA_UAT", \
            "父链泄漏未阻断 Gate"


# --------------------------------------------------------------------
# R16：UAT 报告 ids 必填（现状：uatv4 ids={} 且 validator 放行）
# --------------------------------------------------------------------

class TestReportIds:
    def test_r16_uatv4_report_ids_required(self):
        from scripts.uat_report_validator import validate_report
        rep = {"protocol": "uatv4", "checks": [], "failed": 0,
               "ids": {}, "namespace": "uatv4_x",
               "current_bundle": "prod_v4_best_r1"}
        problems = validate_report(rep)
        assert any("ids" in p.lower() for p in problems), \
            "UAT V4 validator 放行空 ids（指令三.19）"


# --------------------------------------------------------------------
# R17：问卷列表默认不含 fixture（现状：list_surveys 零过滤）
# --------------------------------------------------------------------

class TestSurveyListIsolation:
    def test_r17_survey_list_excludes_fixture(self, env):
        store = env["store"]
        from src.platform.survey import SurveyService
        store._conn.execute(
            "INSERT INTO survey_definition_v1 (survey_id, name,"
            " status, version, spec_json, created_by, data_scope,"
            " test_run_id, created_at, updated_at)"
            " VALUES ('sv-fx-list','UAT fx','published',1,'{}','t',"
            "'uat_fixture',?,datetime('now'),datetime('now'))", (NS,))
        store._conn.execute(
            "INSERT INTO survey_definition_v1 (survey_id, name,"
            " status, version, spec_json, created_by, data_scope,"
            " created_at, updated_at)"
            " VALUES ('sv-op-list','运营问卷','published',1,'{}',"
            "'t','operational',datetime('now'),datetime('now'))")
        store._conn.commit()
        rows = SurveyService(store).list_surveys()
        ids = {r["survey_id"] for r in rows}
        assert "sv-fx-list" not in ids, \
            "普通问卷列表返回 fixture 问卷（指令三.10）"
        assert "sv-op-list" in ids
