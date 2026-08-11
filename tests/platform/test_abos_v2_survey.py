"""ABOSV2 Phase E 红测试：问卷纵向切片（Gate G5）。

要求（任务书 §九 / 03-DOMAIN-PACKS-SPEC §3）：
1. 首批题型（单选/多选/填空/打分/拍照）+ 样板问卷模板；预留类型不得伪造；
2. 跳题是可验证 DAG：循环/不可达/冲突检测；
3. 已发布问卷不可原地修改；修改生成新版本；
4. 发布→分配→填写→提交→自动评分（评分版本化，含输入证据）；
5. 拍照题：位置/时间/设备/质量证据；识别= suggestion，人工终审后
   才成 final；拒绝/修改反馈 training_truth=false；
6. 后台修正：correction event（原值/新值/原因/操作者/批准人）+
   评分重算版本；append-only；
7. 报表输入聚合 final 答案与评分，按客户作用域。
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.api.health import ServiceSpec, ServiceStatus
from src.platform.control_plane import CommandGateway
from src.platform.survey import SurveyError, SurveyService

IMG = base64.b64encode(b"\xff\xd8fake-jpeg").decode()


def _fake_probe(spec: ServiceSpec) -> ServiceStatus:
    return ServiceStatus(name=spec.name, status="healthy", latency_ms=1,
                         detail="fake")


class _FakeRec:
    def recognize(self, data: bytes, conf: float = 0.25):
        return {"count": 2, "products": [
            {"name": "SKU-NEW", "count": 1},
            {"name": "SKU-OLD", "count": 1}]}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", "v2-admin-pw")
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=_FakeRec(), probe=_fake_probe)
    profiles = build_profiles_service(bundle)
    gateway = CommandGateway(bundle.store, profiles,
                             recognition_adapter=_FakeRec())
    svc = SurveyService(bundle.store, gateway)
    return {"store": bundle.store, "svc": svc, "gateway": gateway}


def _publish_sample(env) -> str:
    svc = env["svc"]
    d = svc.create_draft(name="样板", spec=None, actor="admin",
                         from_template="tpl_store_visit_v1")
    svc.lint(d["survey_id"])
    svc.publish(d["survey_id"], actor="admin")
    return d["survey_id"]


class TestDefinitionLifecycle:
    def test_template_lints_clean_and_publish_gate(self, env):
        svc = env["svc"]
        d = svc.create_draft(name="t", spec=None, actor="admin",
                             from_template="tpl_store_visit_v1")
        linted = svc.lint(d["survey_id"])
        errors = [i for i in linted["lint_report"]
                  if i["level"] == "error"]
        assert errors == []
        assert linted["status"] == "linted"
        pub = svc.publish(d["survey_id"], actor="admin")
        assert pub["status"] == "published" and pub["published_at"]

    def test_published_immutable_new_version_required(self, env):
        svc = env["svc"]
        sid = _publish_sample(env)
        with pytest.raises(SurveyError):
            svc.update_draft(sid, spec={"questions": []})
        v2 = svc.new_version(sid, actor="admin")
        assert v2["version"] == 2 and v2["status"] == "draft"
        # 未 lint 不得发布
        with pytest.raises(SurveyError):
            svc.publish(sid, actor="admin")
        # 新草稿存在时，分配仍针对已发布版本（历史 Response 绑定原版本）
        a = svc.assign(survey_id=sid, customer_id="c-x",
                       assignee="x", actor="admin")
        assert a["survey_version"] == 1

    def test_dag_detects_cycle_unreachable_conflict(self, env):
        svc = env["svc"]
        spec = {
            "sections": [], "questions": [
                {"id": "q1", "type": "single_choice",
                 "options": [{"value": "a"}, {"value": "b"}]},
                {"id": "q2", "type": "single_choice",
                 "options": [{"value": "a"}]},
                {"id": "q3", "type": "text"},
                {"id": "q4", "type": "text"}],
            "logic_edges": [
                {"from": "q1", "when": {"op": "eq", "value": "a"},
                 "to": "q3"},
                {"from": "q1", "when": {"op": "eq", "value": "a"},
                 "to": "q4"},   # 冲突条件（同题同条件不同目标）
                {"from": "q3", "when": {"op": "eq", "value": "a"},
                 "to": "q1"}],  # 循环（q1→q3→q1，q2 不可达）
            "scoring": {"rules": []}}
        d = svc.create_draft(name="broken", spec=spec, actor="admin")
        linted = svc.lint(d["survey_id"])
        codes = {i["code"] for i in linted["lint_report"]}
        assert "cycle" in codes
        assert "unreachable" in codes
        assert "edge_conflict" in codes
        assert linted["status"] == "draft", "lint 失败不得晋级"
        with pytest.raises(SurveyError):
            svc.publish(d["survey_id"], actor="admin")

    def test_reserved_question_types_not_faked(self, env):
        # ABOSV3 T6：matrix 已真实实现（转由 builder 测试覆盖）；
        # 仍未实现的预留类型（signature 等）继续 fail-closed。
        svc = env["svc"]
        spec = {"questions": [{"id": "q1", "type": "signature"}],
                "logic_edges": [], "scoring": {}}
        d = svc.create_draft(name="reserved", spec=spec, actor="admin")
        linted = svc.lint(d["survey_id"])
        assert any(i["code"] == "unknown_type"
                   for i in linted["lint_report"])


class TestFillAndScore:
    def test_full_flow_with_skip_logic_and_scoring(self, env):
        svc = env["svc"]
        sid = _publish_sample(env)
        a = svc.assign(survey_id=sid, customer_id="cust-x",
                       assignee="field1", actor="admin")
        r = svc.start_response(assignment_id=a["assignment_id"],
                               respondent="field1")
        # 跳题：门店类型=other → 后续题目全部被跳过
        svc.save_answers(r["response_id"], {
            "q_store_type": {"value": "other"}})
        spec = svc.get_survey(sid)["spec"]
        visible = svc.visible_questions(spec, {
            "q_store_type": {"value": "other"}})
        assert "q_sku_present" not in visible
        # 被跳过的必填题不再阻断提交；评分只计可见答案
        sub_other = svc.submit(r["response_id"], actor="field1")
        assert sub_other["status"] == "submitted"
        assert sub_other["scores"]["total"] == 2  # other 映射 2 分
        # 正常分支：必填不足 → 拒绝提交（诚实失败）
        r_miss = svc.start_response(assignment_id=a["assignment_id"],
                                    respondent="field1")
        svc.save_answers(r_miss["response_id"], {
            "q_store_type": {"value": "convenience"}})
        with pytest.raises(SurveyError):
            svc.submit(r_miss["response_id"], actor="field1")
        # 正常分支：补齐可见必填题（含拍照证据）
        r2 = svc.start_response(assignment_id=a["assignment_id"],
                                respondent="field1")
        svc.save_answers(r2["response_id"], {
            "q_store_type": {"value": "convenience"},
            "q_sku_present": {"value": ["SKU-NEW"]},
            "q_shelf_len": {"value": 3.5},
            "q_score_service": {"value": 4}})
        m = svc.attach_media(
            response_id=r2["response_id"], question_id="q_shelf_photo",
            location={"lat": 31.23, "lng": 121.47, "accuracy": 8},
            taken_at="2026-08-11T10:00:00+08:00", device="iphone-test",
            quality={"width": 1080, "blur": 0.02},
            image_b64=IMG, actor="field1")
        # 拍照证据四要素齐全
        assert m["location"]["lat"] == 31.23
        assert m["taken_at"] and m["device"]
        assert m["quality"]["width"] == 1080
        # 识别 suggestion 生成（pending，非 final）
        assert m["suggestion_status"] == "pending"
        assert m["suggestion"]["task_id"]
        sub = svc.submit(r2["response_id"], actor="field1")
        assert sub["status"] == "submitted"
        assert sub["score_version"] == 1
        assert sub["scores"]["total"] == 5 + 4 * 2  # map 5 + rating 4×2
        assert sub["scores"]["inputs"]["q_score_service"] == 4
        # assignment 完成
        assert svc.get_assignment(a["assignment_id"])[
            "status"] == "completed"

    def test_suggestion_requires_human_final(self, env):
        svc = env["svc"]
        sid = _publish_sample(env)
        a = svc.assign(survey_id=sid, customer_id="cust-x",
                       assignee="f", actor="admin")
        r = svc.start_response(assignment_id=a["assignment_id"],
                               respondent="f")
        m = svc.attach_media(response_id=r["response_id"],
                             question_id="q_shelf_photo",
                             image_b64=IMG, actor="f")
        # 未经人工终审：答案里没有 final
        resp = svc.get_response(r["response_id"])
        assert "q_shelf_photo" not in resp["answers"]
        # 拒绝 suggestion → 反馈事件 training_truth=False
        denied = svc.review_suggestion(m["media_id"], decision="rejected",
                                       actor="f")
        assert denied["suggestion_status"] == "rejected"
        events = env["store"].list_events()
        rev = [e for e in events
               if e["event_type"] == "survey.suggestion.reviewed"]
        assert rev
        payload = json.loads(rev[-1]["payload_json"])
        assert payload["training_truth"] is False
        # 修改后 final 生效
        m2 = svc.attach_media(response_id=r["response_id"],
                              question_id="q_shelf_photo",
                              image_b64=IMG, actor="f")
        final = svc.review_suggestion(
            m2["media_id"], decision="modified",
            final_value={"products": [{"name": "SKU-NEW", "count": 1}]},
            actor="f")
        assert final["suggestion_status"] == "modified"
        resp2 = svc.get_response(r["response_id"])
        assert resp2["answers"]["q_shelf_photo"]["final"] is True

    def test_correction_event_and_rescore(self, env):
        svc = env["svc"]
        sid = _publish_sample(env)
        a = svc.assign(survey_id=sid, customer_id="cust-x",
                       assignee="f", actor="admin")
        r = svc.start_response(assignment_id=a["assignment_id"],
                               respondent="f")
        svc.save_answers(r["response_id"], {
            "q_store_type": {"value": "convenience"},
            "q_sku_present": {"value": ["SKU-NEW"]},
            "q_score_service": {"value": 2}})
        svc.attach_media(response_id=r["response_id"],
                         question_id="q_shelf_photo",
                         image_b64=IMG, actor="f")
        sub = svc.submit(r["response_id"], actor="f")
        assert sub["scores"]["total"] == 5 + 2 * 2
        # 无原因修正被拒
        with pytest.raises(SurveyError):
            svc.correct_answer(response_id=r["response_id"],
                               question_id="q_score_service",
                               new_value={"value": 5}, reason="",
                               actor="boss")
        fixed = svc.correct_answer(
            response_id=r["response_id"], question_id="q_score_service",
            new_value={"value": 5}, reason="现场复核评分录入错误",
            actor="boss", approver="admin")
        assert fixed["score_version"] == 2
        assert fixed["scores"]["total"] == 5 + 5 * 2
        corr = svc.list_corrections(r["response_id"])
        assert corr and corr[0]["reason"] == "现场复核评分录入错误"
        assert corr[0]["actor"] == "boss" and corr[0]["approver"]
        # append-only
        with pytest.raises(Exception):
            env["store"]._conn.execute(
                "DELETE FROM survey_answer_correction_v1")
        # 已提交响应不得绕过 correction 直接改
        with pytest.raises(SurveyError):
            svc.save_answers(r["response_id"],
                             {"q_score_service": {"value": 1}})

    def test_report_input_scoped(self, env):
        svc = env["svc"]
        sid = _publish_sample(env)
        for cid in ("cust-x", "cust-y"):
            a = svc.assign(survey_id=sid, customer_id=cid,
                           assignee="f", actor="admin")
            r = svc.start_response(assignment_id=a["assignment_id"],
                                   respondent="f")
            svc.save_answers(r["response_id"], {
                "q_store_type": {"value": "supermarket"},
                "q_sku_present": {"value": ["SKU-OLD"]},
                "q_score_service": {"value": 3}})
            svc.attach_media(response_id=r["response_id"],
                             question_id="q_shelf_photo",
                             image_b64=IMG, actor="f")
            svc.submit(r["response_id"], actor="f")
        rep_x = svc.report(survey_id=sid, customer_id="cust-x")
        rep_y = svc.report(survey_id=sid, customer_id="cust-y")
        assert rep_x["submitted"] == 1 and rep_y["submitted"] == 1
        assert rep_x["avg_score"] == 4 + 3 * 2
        rep_all = svc.report(survey_id=sid)
        assert rep_all["submitted"] == 2
