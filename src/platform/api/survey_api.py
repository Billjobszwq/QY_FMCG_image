"""ABOSV2 Phase E：问卷域 API（设计/分配/填写/拍照/修正/报表输入）。

作用域：survey.read/survey.manage scope + customer 作用域（fail-closed）；
模型 suggestion 必须人工终审；后台修正只走 correction 通道。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..auth import AuthService, require_principal
from ..iam import IAMService
from ..scope import bind_fixture_scope
from ..survey import SurveyError, SurveyService


class DraftBody(BaseModel):
    name: str = ""
    spec: dict | None = None
    template_id: str | None = None
    test_run_id: str = ""


class AssignBody(BaseModel):
    survey_id: str
    customer_id: str
    project_id: str = ""
    assignee: str = ""
    test_run_id: str = ""


class StartBody(BaseModel):
    assignment_id: str


class AnswersBody(BaseModel):
    answers: dict = {}


class MediaBody(BaseModel):
    question_id: str
    location: dict = {}
    taken_at: str = ""
    device: str = ""
    quality: dict = {}
    image_b64: str = ""
    capture_role: str | None = None  # UATCC T1：门头/货架/自拍/商品/其他


class ReviewBody(BaseModel):
    decision: str
    final_value: Any = None


class CorrectionBody(BaseModel):
    question_id: str
    new_value: Any = None
    reason: str
    approver: str = ""


def _platform(iam: IAMService, actor: str, session_role: str) -> bool:
    if session_role == "admin":
        return True
    roles = set(iam.roles_of(actor))
    return "platform_admin" in roles or "owner" in roles


def _guard(iam: IAMService, actor: str, session_role: str, scope: str,
           customer_id: str = "") -> None:
    if _platform(iam, actor, session_role):
        return
    if not iam.authorize(actor, scope, customer_id=customer_id):
        raise HTTPException(
            403, f"权限不足：{actor} 缺少 {scope}"
                 + (f"（customer={customer_id}）" if customer_id else "")
                 + " 作用域")


def create_survey_router(store: Any, survey: SurveyService,
                         iam: IAMService,
                         auth: AuthService | None) -> APIRouter:
    router = APIRouter(tags=["survey"])

    def _err(fn):
        def wrap(*a, **kw):
            try:
                return fn(*a, **kw)
            except SurveyError as e:
                raise HTTPException(409, str(e))
        return wrap

    # ---- 定义生命周期 ----

    @router.post("/api/v1/survey/definitions")
    def create(body: DraftBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], "survey.manage")
        try:
            out = survey.create_draft(
                name=body.name, spec=body.spec, actor=p["actor"],
                from_template=body.template_id)
            if body.test_run_id:
                bind_fixture_scope(store, "survey_definition_v1",
                                   out["survey_id"], body.test_run_id)
            return {"definition": out}
        except SurveyError as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/survey/definitions")
    def list_defs(request: Request) -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], "survey.read")
        defs = survey.list_surveys()
        return {"count": len(defs), "definitions": defs}

    @router.get("/api/v1/survey/definitions/{survey_id}")
    def get_def(survey_id: str, request: Request,
                version: int | None = None) -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], "survey.read")
        try:
            return {"definition": survey.get_survey(survey_id, version)}
        except SurveyError as e:
            raise HTTPException(404, str(e))

    @router.put("/api/v1/survey/definitions/{survey_id}")
    def update_def(survey_id: str, body: DraftBody,
                   request: Request) -> dict:
        """ABOSV3 T6：Builder 保存草稿（已发布不可原地改）。"""
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], "survey.manage")
        try:
            return {"definition": survey.update_draft(
                survey_id, spec=body.spec,
                name=body.name or None)}
        except SurveyError as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/survey/definitions/{survey_id}/lint")
    def lint(survey_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], "survey.manage")
        try:
            return {"definition": survey.lint(survey_id)}
        except SurveyError as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/survey/definitions/{survey_id}/publish")
    def publish(survey_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], "survey.manage")
        try:
            return {"definition": survey.publish(survey_id,
                                                 actor=p["actor"])}
        except SurveyError as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/survey/definitions/{survey_id}/new-version")
    def new_version(survey_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], "survey.manage")
        try:
            return {"definition": survey.new_version(survey_id,
                                                     actor=p["actor"])}
        except SurveyError as e:
            raise HTTPException(409, str(e))

    # ---- 分配与填写 ----

    @router.post("/api/v1/survey/assignments")
    def assign(body: AssignBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], "survey.manage",
               customer_id=body.customer_id)
        try:
            out = survey.assign(
                survey_id=body.survey_id, customer_id=body.customer_id,
                project_id=body.project_id, assignee=body.assignee,
                actor=p["actor"])
            trid = body.test_run_id
            if not trid:
                # 继承问卷定义的 scope（唯一事实源）
                row = store._conn.execute(
                    "SELECT COALESCE(data_scope,'operational') ds,"
                    " COALESCE(test_run_id,'') tr FROM"
                    " survey_definition_v1 WHERE survey_id=?",
                    (body.survey_id,)).fetchone()
                if row and row["ds"] == "uat_fixture":
                    trid = row["tr"]
            if trid:
                bind_fixture_scope(store, "survey_assignment_v1",
                                   out["assignment_id"], trid)
            return {"assignment": out}
        except SurveyError as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/survey/assignments")
    def list_assignments(request: Request,
                         customer_id: str = "") -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], "survey.read",
               customer_id=customer_id)
        rows = survey.list_assignments(customer_id=customer_id)
        if not _platform(iam, p["actor"], p["role"]) and not customer_id:
            # ABOSV3-P1-015：多客户授权全部可见，不得只取第一个
            limit = iam.visible_customers(p["actor"]) or []
            rows = [r for r in rows if r.get("customer_id") in limit]
        return {"count": len(rows), "assignments": rows}

    @router.post("/api/v1/survey/responses")
    def start(body: StartBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            r = survey.start_response(assignment_id=body.assignment_id,
                                      respondent=p["actor"])
        except SurveyError as e:
            raise HTTPException(409, str(e))
        # SI2：response 继承 assignment 的 scope（含 fixture）
        try:
            arow = store._conn.execute(
                "SELECT COALESCE(data_scope,'operational') ds,"
                " COALESCE(test_run_id,'') tr FROM survey_assignment_v1"
                " WHERE assignment_id=?",
                (body.assignment_id,)).fetchone()
            if arow and arow["ds"] == "uat_fixture" and arow["tr"] \
                    and r.get("response_id"):
                bind_fixture_scope(store, "survey_response_v1",
                                   r["response_id"], arow["tr"])
        except Exception:
            pass
        _guard(iam, p["actor"], p["role"], "survey.read",
               customer_id=r["customer_id"])
        return {"response": r}

    @router.put("/api/v1/survey/responses/{response_id}/answers")
    def save_answers(response_id: str, body: AnswersBody,
                     request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            return {"response": survey.save_answers(response_id,
                                                    body.answers)}
        except SurveyError as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/survey/responses/{response_id}/submit")
    def submit(response_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            return {"response": survey.submit(response_id,
                                              actor=p["actor"])}
        except SurveyError as e:
            raise HTTPException(409, str(e))

    @router.get("/api/v1/survey/responses")
    def list_responses(request: Request, survey_id: str = "",
                       customer_id: str = "") -> dict:
        p = require_principal(auth, request, csrf=False)
        _guard(iam, p["actor"], p["role"], "survey.read",
               customer_id=customer_id)
        rows = survey.list_responses(survey_id=survey_id,
                                     customer_id=customer_id)
        if not _platform(iam, p["actor"], p["role"]) and not customer_id:
            limit = iam.visible_customers(p["actor"]) or []
            rows = [r for r in rows if r.get("customer_id") in limit]
        return {"count": len(rows), "responses": rows}

    # ---- 拍照题 ----

    @router.post("/api/v1/survey/responses/{response_id}/media")
    def attach_media(response_id: str, body: MediaBody,
                     request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            return {"media": survey.attach_media(
                response_id=response_id, question_id=body.question_id,
                location=body.location, taken_at=body.taken_at,
                device=body.device, quality=body.quality,
                image_b64=body.image_b64, actor=p["actor"],
                capture_role=body.capture_role)}
        except SurveyError as e:
            raise HTTPException(409, str(e))

    @router.delete("/api/v1/survey/media/{media_id}")
    def delete_media(media_id: str, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            return {"media": survey.delete_media(media_id,
                                                 actor=p["actor"])}
        except SurveyError as e:
            raise HTTPException(409, str(e))

    @router.post("/api/v1/survey/media/{media_id}/review")
    def review(media_id: str, body: ReviewBody, request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        try:
            return {"media": survey.review_suggestion(
                media_id, decision=body.decision,
                final_value=body.final_value, actor=p["actor"])}
        except SurveyError as e:
            raise HTTPException(409, str(e))

    # ---- 后台修正 ----

    @router.post("/api/v1/survey/responses/{response_id}/corrections")
    def correct(response_id: str, body: CorrectionBody,
                request: Request) -> dict:
        p = require_principal(auth, request, csrf=True)
        _guard(iam, p["actor"], p["role"], "survey.manage")
        try:
            r = survey.correct_answer(
                response_id=response_id, question_id=body.question_id,
                new_value=body.new_value, reason=body.reason,
                actor=p["actor"], approver=body.approver)
        except SurveyError as e:
            raise HTTPException(409, str(e))
        corrections = survey.list_corrections(response_id)
        return {"response": r, "corrections": corrections}

    # ---- 报表输入 ----

    @router.get("/api/v1/survey/report")
    def report(request: Request, survey_id: str,
               customer_id: str = "") -> dict:
        p = require_principal(auth, request, csrf=False)
        if not _platform(iam, p["actor"], p["role"]):
            if not iam.authorize(p["actor"], "survey.read",
                                 customer_id=customer_id or None):
                raise HTTPException(403, "无权访问该客户的问卷报表")
            if not customer_id:
                limit = iam.visible_customers(p["actor"]) or []
                if len(limit) != 1:
                    raise HTTPException(
                        400, "多客户作用域用户必须指定 customer_id"
                             "（不得跨客户混合汇总）")
                customer_id = limit[0]
        try:
            return survey.report(survey_id=survey_id,
                                 customer_id=customer_id)
        except SurveyError as e:
            raise HTTPException(409, str(e))

    return router
