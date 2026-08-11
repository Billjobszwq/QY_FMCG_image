"""ABOSV3 T6 红测试：从空白自定义问卷（matrix/description + Builder API）。

- 新增题型 matrix（rows+options）与 description（不作答）；
- lint 对不完整矩阵 fail-closed；
- matrix 必填校验逐行；matrix map 计分逐行求和；
- 从空白创建 → PUT 更新 draft → lint → 发布 → 分配 → 填写 → 提交
  全链（不依赖样板模板）；
- 已发布不可原地改，只能新版本。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.api.app import create_app

PW = "v3-survey-pw"


class _OkRecognition:
    def recognize(self, data: bytes, conf: float = 0.25):
        return {"count": 0, "products": []}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PLATFORM_ADMIN_PASSWORD", PW)
    adapter = _OkRecognition()
    bundle = build_production_bundle(
        db_path=tmp_path / "p.sqlite", cas_root=tmp_path / "cas",
        recognition_adapter=adapter, probe=lambda spec: None)
    build_profiles_service(bundle)
    app = create_app(services=(), probe=lambda spec: None,
                     bundle=bundle, recognition_adapter=adapter,
                     web_dist=Path("/nonexistent-dist"))
    c = TestClient(app)
    r = c.post("/api/v1/auth/login",
               json={"username": "admin", "password": PW})
    h = {"X-CSRF-Token": r.json()["csrf_token"]}
    return c, h, bundle


BLANK = {"questions": [], "logic_edges": [],
         "scoring": {"version": 1, "rules": [], "formula": "sum"}}


class TestBlankBuilderE2E:
    def test_blank_to_published_to_response(self, client):
        c, h, _b = client
        # 1) 从空白创建（不指定 template）
        d = c.post("/api/v1/survey/definitions", headers=h,
                   json={"name": "UAT 自建问卷",
                         "spec": BLANK}).json()["definition"]
        sid = d["survey_id"]
        assert d["status"] == "draft"
        # 2) Builder 添加题目（PUT 更新 draft）
        spec = {
            "questions": [
                {"id": "q1", "type": "single_choice", "title": "门店类型",
                 "required": True,
                 "options": [{"value": "a", "label": "A"},
                             {"value": "b", "label": "B"}]},
                {"id": "q2", "type": "matrix", "title": "逐项评价",
                 "required": True,
                 "rows": [{"id": "r1", "label": "陈列"},
                          {"id": "r2", "label": "价格"}],
                 "options": [{"value": "good", "label": "好"},
                             {"value": "bad", "label": "差"}]},
                {"id": "q3", "type": "description",
                 "title": "感谢填写", "text": "请继续"},
            ],
            "logic_edges": [],
            "scoring": {"version": 1, "formula": "sum",
                        "rules": [{"question": "q2",
                                   "map": {"good": 5, "bad": 1}}]}}
        u = c.put(f"/api/v1/survey/definitions/{sid}", headers=h,
                  json={"spec": spec, "name": ""})
        assert u.status_code == 200, u.text
        # 3) lint → 发布
        lint = c.post(f"/api/v1/survey/definitions/{sid}/lint",
                      headers=h).json()["definition"]
        assert not any(i["level"] == "error"
                       for i in lint["lint_report"]), lint["lint_report"]
        pub = c.post(f"/api/v1/survey/definitions/{sid}/publish",
                     headers=h).json()["definition"]
        assert pub["status"] == "published"
        # 4) 已发布不可原地改
        blocked = c.put(f"/api/v1/survey/definitions/{sid}", headers=h,
                        json={"spec": BLANK, "name": ""})
        assert blocked.status_code == 409
        # 5) 新版本可用
        nv = c.post(f"/api/v1/survey/definitions/{sid}/new-version",
                    headers=h).json()["definition"]
        assert nv["version"] == 2 and nv["status"] == "draft"
        # 6) 分配并填写（matrix 未填全 → 拒绝提交；填全 → 计分）
        from src.platform.iam import IAMService, MasterDataService
        from src.platform.survey import SurveyService
        svc = SurveyService(_b.store)
        iam = IAMService(_b.store)
        md = MasterDataService(_b.store, iam)
        md.create_customer(customer_id="svy-cust", name="问卷客户",
                           created_by="admin")
        asg = svc.assign(survey_id=sid, customer_id="svy-cust",
                         assignee="field1", actor="admin")
        r = svc.start_response(assignment_id=asg["assignment_id"],
                               respondent="field1")
        rid = r["response_id"]
        svc.save_answers(rid, {"q1": {"value": "a"},
                               "q2": {"value": {"r1": "good"}}})
        with pytest.raises(Exception) as ei:
            svc.submit(rid, actor="field1")
        assert "矩阵未填全" in str(ei.value)
        svc.save_answers(rid, {"q2": {"value": {"r1": "good",
                                                "r2": "good"}}})
        done = svc.submit(rid, actor="field1")
        assert done["status"] == "submitted"
        # matrix map 逐行计分：5+5=10（description 题不计分不作答）
        assert done["scores"]["total"] == 10.0


class TestMatrixLint:
    def test_incomplete_matrix_fail_closed(self, client):
        c, h, _b = client
        spec = {"questions": [{"id": "m1", "type": "matrix",
                               "title": "缺行的矩阵"}],
                "logic_edges": [], "scoring": None}
        d = c.post("/api/v1/survey/definitions", headers=h,
                   json={"name": "矩阵lint", "spec": spec}
                   ).json()["definition"]
        lint = c.post(f"/api/v1/survey/definitions/{d['survey_id']}/lint",
                      headers=h).json()["definition"]
        assert any(i["code"] == "matrix_incomplete"
                   for i in lint["lint_report"])
        assert lint["status"] == "draft"  # 有 error 不得进入 linted

    def test_description_not_required_answer(self, client):
        from src.platform.survey import SurveyService
        c, h, _b = client
        spec = {"questions": [{"id": "d1", "type": "description",
                               "title": "说明", "required": True}],
                "logic_edges": [],
                "scoring": {"version": 1, "rules": [], "formula": "sum"}}
        d = c.post("/api/v1/survey/definitions", headers=h,
                   json={"name": "说明卷", "spec": spec}
                   ).json()["definition"]
        lint = c.post(f"/api/v1/survey/definitions/{d['survey_id']}/lint",
                      headers=h).json()["definition"]
        assert lint["status"] == "linted"
        c.post(f"/api/v1/survey/definitions/{d['survey_id']}/publish",
               headers=h)
        svc = SurveyService(_b.store)
        from src.platform.iam import IAMService, MasterDataService
        md = MasterDataService(_b.store, IAMService(_b.store))
        md.create_customer(customer_id="desc-cust", name="D",
                           created_by="admin")
        asg = svc.assign(survey_id=d["survey_id"],
                         customer_id="desc-cust", assignee="f",
                         actor="admin")
        r = svc.start_response(assignment_id=asg["assignment_id"],
                               respondent="f")
        done = svc.submit(r["response_id"], actor="f")
        assert done["status"] == "submitted"
