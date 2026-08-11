"""ABOSV2 Phase F 红测试：BI 纵向切片（Gate G6）。

要求（任务书 §十/BI）：
1. 语义层：注册制 Metric；Agent 不得任意 SQL，只映射已注册指标；
2. ReportSpec 版本化 draft→approved→published；数值来自平台事实表；
3. 异常 → 追问 WorkItem → 回答 → 报表刷新（新版本，不覆盖旧报告）；
4. customer 作用域：越权不可评估他客户指标。
"""
from __future__ import annotations

import base64
from pathlib import Path

import pytest

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.analytics import AnalyticsError, AnalyticsService
from src.platform.control_plane import CommandGateway

IMG = base64.b64encode(b"\xff\xd8fake").decode()


class _FakeRec:
    def recognize(self, data: bytes, conf: float = 0.25):
        return {"count": 1, "products": [{"name": "X", "count": 1}]}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "v2-admin-pw")
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=_FakeRec(), probe=lambda spec: None)
    profiles = build_profiles_service(bundle)
    gateway = CommandGateway(bundle.store, profiles,
                             recognition_adapter=_FakeRec())
    svc = AnalyticsService(bundle.store)
    # 造事实：两条识别（usage）+ 一份已提交问卷（分数 10）
    for i in range(2):
        out = gateway.submit(
            command_kind="vision.recognition.create",
            params={"images": [[f"p{i}.jpg", b"\xff\xd8fake"]]},
            actor="admin", source="api", customer_id="cust-a",
            project_id="pj-a")
        assert out["status"] == "succeeded"
    gateway.submit(command_kind="vision.recognition.create",
                   params={"images": [["b.jpg", b"\xff\xd8fake"]]},
                   actor="admin", source="api", customer_id="cust-b")
    conn = bundle.store._conn
    conn.execute(
        "INSERT INTO survey_response_v1 (response_id, assignment_id,"
        " survey_id, survey_version, customer_id, respondent, status,"
        " answers_json, scores_json, score_version, submitted_at,"
        " created_at, updated_at)"
        " VALUES ('rsp-bi-1','','svy-x',1,'cust-a','f','submitted','{}',"
        " '{\"total\": 10.0}',1,'2026-08-12','2026-08-12','2026-08-12')")
    conn.commit()
    return {"store": bundle.store, "svc": svc, "gateway": gateway}


class TestSemanticLayer:
    def test_registered_metrics_only(self, env):
        svc = env["svc"]
        ids = {m["metric_id"] for m in svc.list_metrics()}
        assert {"recognition.photos", "survey.avg_score",
                "workflow.runs"} <= ids
        with pytest.raises(AnalyticsError):
            svc.evaluate_metric("evil.raw_sql", customer_id="cust-a")

    def test_metric_values_from_real_facts(self, env):
        svc = env["svc"]
        assert svc.evaluate_metric("recognition.photos",
                                   customer_id="cust-a") == 2.0
        assert svc.evaluate_metric("recognition.photos",
                                   customer_id="cust-b") == 1.0
        assert svc.evaluate_metric("survey.avg_score",
                                   customer_id="cust-a") == 10.0
        assert svc.evaluate_metric("survey.submitted",
                                   customer_id="cust-a") == 1.0

    def test_agent_maps_only_registered_metrics(self, env):
        svc = env["svc"]
        out = svc.agent_draft("看看识别情况", customer_id="cust-a",
                              actor="admin")
        assert out["draft"] is not None
        assert "recognition.photos" in out["metrics"]
        assert out["requires_human_approval"] is True
        # 未知意图：诚实拒绝，不生成任意查询
        out2 = svc.agent_draft("随便聊聊", customer_id="cust-a",
                               actor="admin")
        assert out2["draft"] is None and out2["metrics"] == []


class TestReportLifecycle:
    def test_draft_approve_publish_gate_and_values(self, env):
        svc = env["svc"]
        rep = svc.create_report_spec(
            name="识别周报", metrics=["recognition.photos"],
            customer_id="cust-a", actor="admin", dimensions=["project"])
        assert rep["status"] == "draft"
        with pytest.raises(AnalyticsError):
            svc.publish_report(rep["spec_id"], actor="admin")
        svc.approve_report(rep["spec_id"], actor="admin")
        pub = svc.publish_report(rep["spec_id"], actor="admin")
        assert pub["status"] == "published" and pub["published_at"]
        ev = svc.evaluate_report(rep["spec_id"])
        assert ev["values"]["recognition.photos"] == 2.0
        assert ev["breakdown"]["pj-a"]["recognition.photos"] == 2.0
        # 未注册指标不得进报表
        with pytest.raises(AnalyticsError):
            svc.create_report_spec(name="bad", metrics=["no.such"],
                                   customer_id="cust-a", actor="admin")

    def test_anomaly_followup_refresh_flow(self, env):
        """异常 → 追问任务 → 回答 → 报表刷新（新版本）。"""
        svc = env["svc"]
        rep = svc.create_report_spec(
            name="问卷质量", metrics=["survey.avg_score"],
            customer_id="cust-a", actor="admin")
        svc.approve_report(rep["spec_id"], actor="admin")
        svc.publish_report(rep["spec_id"], actor="admin")
        # 规则：平均分 < 20 → 异常（observed=10）
        chk = svc.check_anomaly(metric_id="survey.avg_score",
                                customer_id="cust-a", op="lt",
                                threshold=20, actor="system")
        assert chk["hit"] is True and chk["observed"] == 10.0
        ano = chk["anomaly"]
        assert ano["status"] == "open" and ano["follow_up_work_id"]
        # 追问工作项存在（current 投影可见）
        work = env["store"].get_work_item_v2(ano["follow_up_work_id"])
        assert work["status"] == "todo" and work["subject_id"] == \
            ano["anomaly_id"]
        # 未越界不生成异常
        chk2 = svc.check_anomaly(metric_id="survey.avg_score",
                                 customer_id="cust-a", op="gt",
                                 threshold=100, actor="system")
        assert chk2["hit"] is False and chk2["anomaly"] is None
        # 回答 → 异常关闭 + 工作项 done + 报表刷新 v2（旧版本保留）
        out = svc.answer_anomaly(ano["anomaly_id"],
                                 answer="已核实：巡店员评分偏保守",
                                 actor="analyst")
        assert out["anomaly"]["status"] == "resolved"
        assert env["store"].get_work_item_v2(
            ano["follow_up_work_id"])["status"] == "done"
        refreshed = out["refreshed_report"]
        assert refreshed["version"] == 2 and refreshed["status"] == "draft"
        assert ano["anomaly_id"] in refreshed["note"]
        old = svc.get_report_spec(rep["spec_id"], version=1)
        assert old["status"] == "published", "旧报告不得被覆盖"
        # 刷新版重新评估数值一致（数据未变）
        ev = svc.evaluate_report(refreshed["spec_id"], version=2)
        assert ev["values"]["survey.avg_score"] == 10.0
        # 重复回答已关闭异常被拒
        with pytest.raises(AnalyticsError):
            svc.answer_anomaly(ano["anomaly_id"], answer="again",
                               actor="analyst")
