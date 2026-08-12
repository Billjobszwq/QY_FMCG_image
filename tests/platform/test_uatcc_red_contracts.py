"""UATCC T0 红测试：真实业务契约断点（先 RED 后 GREEN）。

10 项（指令第五节）：
1. require_storefront=true 无照片提交必须失败；
2. 门头题无 storefront 角色照片必须失败；
3. 被跳题隐藏的门头题不得阻断提交（防过度修复守卫）；
4. Agent 调用 Usage 必须具备 run/work/evidence 下钻链；
5. Workflow parallel 不得以纯串行冒充（wall-time 证明）；
6. UAT 报告缺关键 ID 必须失败（validator）；
7. inserted=0/skipped=1 不得当作“从空白创建成功”（validator）；
8. V4 shadow 必须读取 sku_name（不得全 '?'）；
9. Rate limit 未实现时不得通过（登录限流 429）；
10. Gate evaluator：存在 P0/P1 或缺必填场景必须拒绝
   READY_FOR_REAL_DATA_UAT。
"""
from __future__ import annotations

import base64
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.composition.build import (build_production_bundle,
                                   build_profiles_service)
from src.platform.api.app import create_app

PW = "uatcc-red-pw"


class _OkRecognition:
    def recognize(self, data: bytes, conf: float = 0.25):
        return {"count": 1, "products": [
            {"sku_id": "SKU-X", "sku_name": "测试SKU",
             "confidence": 0.9}]}


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


IMG_B64 = base64.b64encode(b"\xff\xd8fake-jpeg").decode()


def _make_survey(client, *, require_storefront=True, min_count=0,
                 skip=False):
    """建问卷+分配+响应草稿；skip=True 时门头题被跳题隐藏。"""
    c, h, _b = client
    questions = [
        {"id": "q1", "type": "single_choice", "title": "门店类型",
         "required": True,
         "options": [{"value": "open", "label": "营业"},
                     {"value": "closed", "label": "关门"}]}]
    logic = []
    if not skip:
        questions.append(
            {"id": "qsf", "type": "photo", "title": "门头照",
             "required": True, "min_count": min_count,
             "require_storefront": require_storefront,
             "capture_role": "storefront"})
    else:
        questions.append(
            {"id": "qsf", "type": "photo", "title": "门头照",
             "required": True, "min_count": 1,
             "require_storefront": require_storefront,
             "capture_role": "storefront"})
        logic.append({"from": "q1",
                      "when": {"op": "eq", "value": "closed"},
                      "to": "END_SKIP_SF"})
    spec = {"questions": questions, "logic_edges": logic,
            "scoring": {"version": 1, "rules": [], "formula": "sum"}}
    d = c.post("/api/v1/survey/definitions",
               json={"name": f"red-{time.time_ns()}", "spec": spec},
               headers=h).json()["definition"]
    sid = d["survey_id"]
    c.post(f"/api/v1/survey/definitions/{sid}/lint", json={}, headers=h)
    c.post(f"/api/v1/survey/definitions/{sid}/publish", json={},
           headers=h)
    from src.platform.iam import IAMService, MasterDataService
    from src.platform.survey import SurveyService
    svc = SurveyService(_b.store)
    iam = IAMService(_b.store)
    md = MasterDataService(_b.store, iam)
    try:
        md.create_customer(customer_id="red-cust", name="R",
                           created_by="admin")
    except Exception:
        pass
    asg = svc.assign(survey_id=sid, customer_id="red-cust",
                     assignee="field", actor="admin")
    r = svc.start_response(assignment_id=asg["assignment_id"],
                           respondent="field")
    return svc, sid, r["response_id"]


class TestPhotoContract:
    def test_require_storefront_no_photo_submit_fails(self, client):
        """RED-1：require_storefront=true 且无照片不得提交成功。"""
        svc, sid, rid = _make_survey(client, require_storefront=True,
                                     min_count=0)
        svc.save_answers(rid, {"q1": {"value": "open"}})
        with pytest.raises(Exception) as ei:
            svc.submit(rid, actor="field")
        assert "门头" in str(ei.value) or "storefront" in str(ei.value)

    def test_photo_without_storefront_role_fails(self, client):
        """RED-2：只有非门头角色照片时不得满足门头必拍。"""
        svc, sid, rid = _make_survey(client, require_storefront=True,
                                     min_count=1)
        svc.save_answers(rid, {"q1": {"value": "open"}})
        # 上传一张 shelf 角色照片（不是 storefront）
        svc.attach_media(response_id=rid, question_id="qsf",
                         image_b64=IMG_B64, actor="field",
                         capture_role="shelf")
        with pytest.raises(Exception) as ei:
            svc.submit(rid, actor="field")
        assert "门头" in str(ei.value) or "storefront" in str(ei.value)

    def test_skipped_storefront_does_not_block(self, client):
        """守卫-3：被跳题隐藏的门头题不得错误阻断提交。"""
        svc, sid, rid = _make_survey(client, require_storefront=True,
                                     min_count=1, skip=True)
        svc.save_answers(rid, {"q1": {"value": "closed"}})
        done = svc.submit(rid, actor="field")
        assert done["status"] == "submitted"


class TestAgentUsageLineage:
    def test_agent_usage_has_run_work_evidence(self, client):
        """RED-4：Agent invoke 的 Usage 必须有统一 run/work 可下钻。"""
        c, h, _b = client
        r = c.post("/api/v1/agents/supervisor/invoke", headers=h,
                   json={"text": "项目进度做到哪里了？",
                         "customer_id": "red-cust"})
        assert r.status_code == 200, r.text
        row = _b.store._conn.execute(
            "SELECT * FROM usage_event_v2 WHERE unit='agent_call'"
            " ORDER BY occurred_at DESC LIMIT 1").fetchone()
        assert row is not None, "Agent 调用必须产生 agent_call Usage"
        assert row["run_id"], "Usage 必须挂统一 BusinessRun（可下钻）"
        assert row["work_id"], "Usage 必须挂 WorkItem"
        run = _b.store._conn.execute(
            "SELECT evidence_bundle_id FROM business_run_v1"
            " WHERE run_id=?", (row["run_id"],)).fetchone()
        assert run is not None and run["evidence_bundle_id"], \
            "Agent run 必须有证据 bundle"


class TestParallelRealConcurrency:
    def test_parallel_walltime_proves_concurrency(self, client):
        """RED-5：两个各等 2s 的独立分支：串行≈4s，真并行应≈2s。"""
        c, h, _b = client
        spec = {"trigger": {"type": "manual"}, "variables": {},
                "nodes": [
                    {"id": "start", "type": "trigger"},
                    {"id": "par", "type": "parallel"},
                    {"id": "b1", "type": "wait",
                     "config": {"seconds": 2}},
                    {"id": "b2", "type": "wait",
                     "config": {"seconds": 2}},
                    {"id": "j", "type": "join",
                     "config": {"mode": "all"}},
                    {"id": "end", "type": "end"}],
                "edges": [{"from": "start", "to": "par"},
                          {"from": "par", "to": "b1"},
                          {"from": "par", "to": "b2"},
                          {"from": "b1", "to": "j"},
                          {"from": "b2", "to": "j"},
                          {"from": "j", "to": "end"}]}
        d = c.post("/api/v1/workflows",
                   json={"name": "red-parallel", "spec": spec},
                   headers=h).json()["definition"]
        did = d["definition_id"]
        c.post(f"/api/v1/workflows/{did}/lint", json={}, headers=h)
        c.post(f"/api/v1/workflows/{did}/approve", json={}, headers=h)
        c.post(f"/api/v1/workflows/{did}/publish", json={}, headers=h)
        t0 = time.monotonic()
        run = c.post(f"/api/v1/workflows/{did}/runs",
                     json={"inputs": {}}, headers=h).json()["run"]
        rid = run["run_id"]
        status = run["status"]
        deadline = t0 + 40
        while status not in ("succeeded", "failed", "cancelled") \
                and time.monotonic() < deadline:
            time.sleep(0.3)
            status = c.get(f"/api/v1/workflows/runs/{rid}"
                           ).json()["run"]["status"]
        wall = time.monotonic() - t0
        assert status == "succeeded", f"run 未成功: {status}"
        assert wall < 3.5, (
            f"parallel wall-time {wall:.1f}s ≈ 串行（两分支各 2s 应 ≈2s，"
            "真并行必须显著小于 4s）")


class TestUatReportValidator:
    def test_missing_required_ids_fails(self):
        """RED-6：UAT 报告缺关键 ID 必须判失败。"""
        from scripts.uat_report_validator import validate_report
        problems = validate_report({"ids": {"customer": "c1"}})
        assert problems, "缺关键 ID 必须失败"

    def test_inserted_zero_not_counted_as_created(self):
        """RED-7：inserted=0/skipped=1 不得记为从空白创建成功。"""
        from scripts.uat_report_validator import check_created
        ok, reason = check_created({"inserted": 0, "skipped": 1})
        assert ok is False and reason
        ok2, _ = check_created({"inserted": 1, "skipped": 0})
        assert ok2 is True


class TestShadowSkuName:
    def test_shadow_extracts_sku_name(self):
        """RED-8：shadow 提取必须读 sku_name，不得输出 '?'。"""
        from scripts.recognition_shadow_compare import extract_products
        up = {"count": 2, "products": [
            {"sku_id": "QY_1", "sku_name": "可乐500",
             "confidence": 0.9, "margin": 0.5,
             "box": [1, 2, 3, 4], "status": "ok"},
            {"sku_id": "QY_2", "sku_name": "雪碧500",
             "confidence": 0.8, "margin": 0.4,
             "box": [5, 6, 7, 8], "status": "ok"}]}
        names = extract_products(up)
        assert "?" not in names and names == ["可乐500", "雪碧500"]


class TestRateLimit:
    def test_login_rate_limited(self, client):
        """RED-9：登录暴力尝试必须被限流（429 + Retry-After）。"""
        c, _h, _b = client
        got_429 = False
        for _ in range(15):
            r = c.post("/api/v1/auth/login",
                       json={"username": "admin",
                             "password": "wrong-password"})
            if r.status_code == 429:
                got_429 = True
                assert r.headers.get("Retry-After"), \
                    "429 必须带 Retry-After"
                break
        assert got_429, "15 次错误登录未触发限流（rate limit 未实现）"


class TestGateEvaluator:
    def test_rejects_when_p0_open(self):
        """RED-10：存在 P0 或缺必填场景必须拒绝 READY gate。"""
        from src.platform.gate_evaluator import evaluate_gate
        gate, reasons = evaluate_gate(
            p0_open=1, p1_open=0, rate_limit_ok=True,
            scenarios_ok=True, parallel_ok=True)
        assert gate != "READY_FOR_REAL_DATA_UAT"
        assert reasons

    def test_accepts_when_all_clear(self):
        from src.platform.gate_evaluator import evaluate_gate
        gate, reasons = evaluate_gate(
            p0_open=0, p1_open=0, rate_limit_ok=True,
            scenarios_ok=True, parallel_ok=True)
        assert gate == "READY_FOR_REAL_DATA_UAT"
