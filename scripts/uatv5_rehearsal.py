#!/usr/bin/env python3
"""SI3 T8：UAT V5 全领域链机器预演（04-UAT-V5-PROTOCOL）。

与 V4 的区别：
- report.json 的 ids 必须非空且覆盖全领域关键对象（validator
  fail-closed）；
- 领域链补齐：围栏/差旅、matrix/description/引用题/跳题 DAG/自动
  评分、六角色+跨客户 403、异常→追问→人工回答→报表 v2、Usage
  下钻且 fixture 不进运营计费；
- 结尾做泄漏注入负例：改 DB 制造泄漏 → Gate 必须 STALE/BLOCKED →
  修复并复评后才恢复。

用法：python3 scripts/uatv5_rehearsal.py
"""
from __future__ import annotations

import base64
import http.cookiejar
import json
import random
import re
import sqlite3
import string
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = "http://127.0.0.1:8400"
DB = ROOT / ".platform" / "platform.sqlite"
OUT = ROOT / ".eval" / "scope_v3" / "uatv5"
OUT.mkdir(parents=True, exist_ok=True)
REPORT = OUT / "report.json"

env = {}
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1)
        env[k] = v.strip().strip('"').strip("'")
m = re.search(r"(\w+)[:/]([\w\-!@#$%^&*.]+)",
              env.get("PLATFORM_ADMIN_CREDENTIALS", ""))
OWNER, OWNER_PW = m.group(1), m.group(2)
USER_PW = "UatV5-pw-123"

NS = "uatv5_" + datetime.now().strftime("%Y%m%d%H%M%S") + "_" + \
    "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
CUST = NS + "_cust"
CUST2 = NS + "_cust_b"
PRJ = NS + "_prj"

checks: list[dict] = []
IDS: dict[str, str] = {"test_run": NS}


def check(name: str, ok: bool, evidence: str = "") -> None:
    checks.append({"check": name, "ok": bool(ok),
                   "evidence": str(evidence)[:300]})
    print(("  ✓ " if ok else "  ✗ ") + name +
          (f"  [{str(evidence)[:100]}]" if evidence else ""))


def _png(w=8, h=8) -> bytes:
    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(
            ">I", zlib.crc32(c) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x80\x80\x80" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class Session:
    def __init__(self, name: str):
        self.name = name
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj))
        self.csrf = ""

    def login(self, username: str, password: str) -> dict:
        r = self._raw("POST", "/api/v1/auth/login",
                      {"username": username, "password": password})
        self.csrf = r.get("csrf_token", "")
        return r

    def _raw(self, method, path, body=None, csrf=False, timeout=180):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(BASE + path, data=data, method=method)
        if data is not None:
            r.add_header("content-type", "application/json")
        if csrf and self.csrf:
            r.add_header("X-CSRF-Token", self.csrf)
        try:
            return json.loads(self.op.open(r, timeout=timeout).read())
        except urllib.error.HTTPError as e:
            return {"_http": e.code,
                    "_body": (e.read() or b"").decode()[:200]}

    def get(self, path, timeout=120):
        return self._raw("GET", path, timeout=timeout)

    def post(self, path, body=None, csrf=True):
        return self._raw("POST", path, body, csrf=csrf)

    def put(self, path, body=None, csrf=True):
        return self._raw("PUT", path, body, csrf=csrf)


def main() -> int:
    t0 = time.time()
    bill = Session("owner")
    bill.login(OWNER, OWNER_PW)
    print(f"[SI3-T8] UAT V5 namespace = {NS}")

    # ---- 0) Test Run 上下文先于一切对象 ----
    ctx = bill.post("/api/v1/test-data/run",
                    {"namespace": NS, "customer_ids": [CUST, CUST2]})
    check("test_run_context_first", ctx.get("test_run_id") == NS, ctx)

    # ---- 1) 主数据（全部显式 test_run_id） ----
    c = bill.post("/api/v1/master/customers",
                  {"customer_id": CUST, "name": "UAT V5 门店 A",
                   "test_run_id": NS})
    IDS["customer"] = c.get("customer", {}).get("customer_id", "")
    check("fixture_customer_scoped", IDS["customer"] == CUST, c)
    c2 = bill.post("/api/v1/master/customers",
                   {"customer_id": CUST2, "name": "UAT V5 门店 B",
                    "test_run_id": NS})
    check("fixture_customer_b_scoped",
          c2.get("customer", {}).get("customer_id") == CUST2, c2)
    pj = bill.post("/api/v1/master/projects",
                   {"project_id": PRJ, "customer_id": CUST,
                    "name": "UAT V5 项目", "test_run_id": NS})
    IDS["project"] = pj.get("project", {}).get("project_id", "")
    check("fixture_project_scoped", IDS["project"] == PRJ, pj)
    sku = bill.post("/api/v1/master/skus",
                    {"sku_id": NS + "_sku1", "canonical_name": "乌龙茶",
                     "brand": "三得利", "test_run_id": NS})
    IDS["sku"] = sku.get("sku", {}).get("sku_id", "")
    check("fixture_sku_scoped", bool(IDS["sku"]), sku)
    emp = bill.post("/api/v1/geo/employees",
                    {"customer_id": CUST, "name": "外勤小王",
                     "test_run_id": NS})
    IDS["employee"] = emp.get("employee", {}).get("employee_id", "")
    check("fixture_employee_scoped", bool(IDS["employee"]), emp)
    addr = bill.post("/api/v1/geo/addresses",
                     {"customer_id": CUST, "raw": "上海市南京西路 1 号",
                      "test_run_id": NS})
    addr_id = addr.get("address", {}).get("address_id", "")
    IDS["address"] = addr_id
    check("fixture_address_scoped", bool(addr_id), addr)
    mc = bill.post(f"/api/v1/geo/addresses/{addr_id}/manual-coords",
                   {"lat": 31.23, "lng": 121.47, "source": "manual"})
    check("manual_coords_ok", bool(mc.get("address")), mc)

    # ---- 2) 外勤任务 + 路线 + 围栏 + 差旅 ----
    task = bill.post("/api/v1/geo/tasks",
                     {"customer_id": CUST, "address_id": addr_id,
                      "project_id": PRJ, "kind": "visit",
                      "survey_id": "", "test_run_id": NS})
    task_id = task.get("task", {}).get("task_id", "")
    IDS["field_task"] = task_id
    check("fixture_field_task_scoped", bool(task_id), task)
    plan = bill.post("/api/v1/geo/plans",
                     {"customer_id": CUST, "task_ids": [task_id],
                      "test_run_id": NS})
    IDS["route"] = str(plan.get("plan", {}).get("plan_id")
                       or plan.get("plan", {}).get("plan") or "")
    check("fixture_route_plan_scoped", bool(IDS["route"]),
          str(plan)[:120])
    fence = bill.post("/api/v1/geo/fences",
                      {"customer_id": CUST, "name": f"门店围栏 {NS}",
                       "kind": "circle", "lat": 31.23, "lng": 121.47,
                       "radius_m": 200, "test_run_id": NS})
    IDS["geofence"] = str(fence.get("fence", {}).get("fence_id")
                          or fence.get("geofence", {}).get("fence_id")
                          or "")
    check("fixture_geofence_scoped", bool(IDS["geofence"]),
          str(fence)[:120])
    # 差旅：到场 + 完成触发 travel_cost（诚实派生）
    bill.post(f"/api/v1/geo/tasks/{task_id}/dispatch", {})
    arr = bill.post(f"/api/v1/geo/tasks/{task_id}/arrive",
                    {"lat": 31.23, "lng": 121.47})
    comp = bill.post(f"/api/v1/geo/tasks/{task_id}/complete", {})
    IDS["travel"] = str((comp.get("travel_cost") or {}).get("cost_id",
                                                            ""))
    check("travel_cost_derived", "_http" not in comp,
          str(comp)[:140])

    # ---- 3) 六角色 + 跨客户 403 ----
    roles = {"pm": "project_manager", "fw": "field_manager",
             "an": "analyst", "fin": "finance_operator",
             "aud": "read_only"}
    sessions: dict[str, Session] = {}
    for short, role in roles.items():
        uname = f"{NS}_{short}"
        bill.post("/api/v1/iam/principals",
                  {"kind": "user", "username": uname,
                   "display_name": f"UAT V5 {short}",
                   "password": USER_PW})
        bill.post("/api/v1/iam/grants",
                  {"username": uname, "role": role,
                   "customer_id": CUST})
        s = Session(short)
        s.login(uname, USER_PW)
        sessions[short] = s
    check("six_roles_login", len(sessions) == 5
          and all(s.csrf for s in sessions.values())
          and bool(bill.csrf), "owner+5 roles")
    fw = sessions["fw"]
    pm = sessions["pm"]
    cross = fw.get(f"/api/v1/master/customers/{CUST2}/overview")
    check("cross_customer_403", cross.get("_http") == 403,
          str(cross)[:100])
    cross_pm = pm.get(f"/api/v1/master/projects?customer_id={CUST2}")
    check("cross_customer_403_pm", cross_pm.get("_http") == 403,
          str(cross_pm)[:100])

    # ---- 4) 问卷（全题型：引用/单选/多选/填空/打分/matrix/
    #      description + 跳题 DAG + 自动评分 + 门头契约） ----
    svy = bill.post("/api/v1/survey/definitions", {
        "name": f"UAT V5 问卷 {NS}",
        "spec": {"questions": [
            {"id": "q_desc", "type": "description",
             "title": "巡检说明（本卷覆盖门店全项）"},
            {"id": "q_cust_ref", "type": "customer_ref",
             "title": "所属客户"},
            {"id": "q_prj_ref", "type": "project_ref",
             "title": "所属项目"},
            {"id": "q_sku_ref", "type": "sku_ref", "title": "重点 SKU"},
            {"id": "q_single", "type": "single_choice",
             "title": "陈列位置", "options": ["货架", "冷柜", "收银台"]},
            {"id": "q_multi", "type": "multi_choice", "title": "促销活动",
             "options": ["买赠", "折扣", "无"]},
            {"id": "q_text", "type": "text", "title": "门店备注",
             "required": False},
            {"id": "q_score", "type": "rating", "title": "整洁度",
             "min": 1, "max": 5},
            {"id": "q_matrix", "type": "matrix", "title": "分区评分",
             "rows": ["入口", "货架"], "columns": ["好", "中", "差"]},
            {"id": "q_photo", "type": "photo", "title": "门头照",
             "required": True, "min_count": 1, "max_count": 3,
             "require_storefront": True, "capture_role": "storefront"},
            {"id": "q_follow", "type": "text", "title": "冷柜补充说明",
             "required": False}],
            "logic_edges": [{"from": "q_single", "to": "q_follow",
                             "when": {"equals": "冷柜"}}],
            "auto_score": {"weights": {"q_score": 1.0}}},
        "test_run_id": NS})
    survey_id = svy.get("definition", {}).get("survey_id", "")
    IDS["survey"] = survey_id
    check("fixture_survey_scoped", bool(survey_id), svy)
    lint = bill.post(f"/api/v1/survey/definitions/{survey_id}/lint", {})
    bill.post(f"/api/v1/survey/definitions/{survey_id}/publish", {})
    asg = bill.post("/api/v1/survey/assignments",
                    {"survey_id": survey_id, "customer_id": CUST,
                     "project_id": PRJ, "assignee": OWNER,
                     "test_run_id": NS})
    assignment_id = asg.get("assignment", {}).get("assignment_id", "")
    IDS["assignment"] = assignment_id
    check("fixture_assignment_scoped", bool(assignment_id), asg)
    rsp = fw.post("/api/v1/survey/responses",
                  {"assignment_id": assignment_id})
    response_id = rsp.get("response", {}).get("response_id", "")
    IDS["response"] = response_id
    check("fixture_response_scoped", bool(response_id), rsp)
    neg = fw.post(f"/api/v1/survey/responses/{response_id}/submit", {})
    check("storefront_negative_rejected",
          neg.get("_http") in (400, 409, 422), neg)
    photo = base64.b64encode(_png()).decode()
    media = fw.post(f"/api/v1/survey/responses/{response_id}/media",
                    {"question_id": "q_photo", "image_b64": photo,
                     "capture_role": "storefront"})
    IDS["media"] = media.get("media", {}).get("media_id", "")
    check("storefront_media_attached", "_http" not in media, media)
    fw.put(f"/api/v1/survey/responses/{response_id}/answers",
           {"answers": {"q_single": {"value": "货架"},
                        "q_score": {"value": 4},
                        "q_matrix": {"value": {"入口": "好",
                                               "货架": "中"}}}})
    sub = fw.post(f"/api/v1/survey/responses/{response_id}/submit", {})
    check("storefront_positive_submitted",
          "_http" not in sub
          and sub.get("response", {}).get("status") == "submitted",
          str(sub)[:140])
    # 媒体继承 response scope（SI3 契约直查）
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    mrow = dict(conn.execute(
        "SELECT data_scope, test_run_id FROM survey_media_v1 WHERE"
        " media_id=?", (IDS["media"],)).fetchone())
    check("media_inherits_response_scope",
          mrow["data_scope"] == "uat_fixture"
          and mrow["test_run_id"] == NS, mrow)

    # ---- 5) 主工作流（trigger/transform/condition/wait/parallel/
    #      join/loop/approval/agent/command） ----
    spec = {"trigger": {"type": "manual"}, "variables": {},
            "nodes": [
                {"id": "start", "type": "trigger"},
                {"id": "tf", "type": "transform",
                 "config": {"map": {"n": 1}}},
                {"id": "cond", "type": "condition",
                 "config": {"test": "$vars.n == 1"}},
                {"id": "w", "type": "wait", "config": {"seconds": 1}},
                {"id": "par", "type": "parallel",
                 "config": {"max_concurrency": 2}},
                {"id": "b1", "type": "wait", "config": {"seconds": 1}},
                {"id": "b2", "type": "transform",
                 "config": {"map": {"x": 1}}},
                {"id": "j", "type": "join", "config": {"mode": "all"}},
                {"id": "rec", "type": "command",
                 "capability": "vision.recognition.create",
                 "inputs": {"images": "$inputs.images",
                            "recognition_profile_id":
                                "v4_best_standard",
                            "service_tier": "standard",
                            "entry": "workflow"}},
                {"id": "appr", "type": "human_approval",
                 "config": {"owner": OWNER, "title": "UAT V5 确认"}},
                {"id": "ag", "type": "agent",
                 "config": {"agent_id": "analytics_agent",
                            "prompt": "生成报表草稿"}},
                {"id": "lp", "type": "loop",
                 "config": {"items_path": "$inputs.items",
                            "body": "lb"}},
                {"id": "lb", "type": "transform",
                 "config": {"map": {"it": "$vars.loop_item"}}},
                {"id": "end", "type": "end"}],
            "edges": [
                {"from": "start", "to": "tf"}, {"from": "tf",
                 "to": "cond"}, {"from": "cond", "to": "w"},
                {"from": "w", "to": "par"},
                {"from": "par", "to": "b1"}, {"from": "par", "to": "b2"},
                {"from": "b1", "to": "j"}, {"from": "b2", "to": "j"},
                {"from": "j", "to": "rec"}, {"from": "rec", "to": "appr"},
                {"from": "appr", "to": "ag"}, {"from": "ag", "to": "lp"},
                {"from": "lp", "to": "end"}],
            "policy": {"approval_required_for_publish": True}}
    wf = bill.post("/api/v1/workflows",
                   {"name": f"UAT V5 主工作流 {NS}", "spec": spec,
                    "test_run_id": NS})
    did = wf.get("definition", {}).get("definition_id", "")
    IDS["workflow_def"] = did
    check("fixture_workflow_scoped", bool(did), wf)
    bill.post(f"/api/v1/workflows/{did}/lint", {})
    bill.post(f"/api/v1/workflows/{did}/simulate", {"inputs": {}})
    bill.post(f"/api/v1/workflows/{did}/approve", {})
    bill.post(f"/api/v1/workflows/{did}/publish", {})
    img_b64 = base64.b64encode(_png()).decode()
    run = bill.post(f"/api/v1/workflows/{did}/runs",
                    {"inputs": {"images": [["shelf.png", img_b64]],
                                "items": [1, 2]},
                     "customer_id": CUST, "project_id": PRJ,
                     "test_run_id": NS})
    rid = run.get("run", {}).get("run_id", "")
    IDS["run"] = rid
    IDS["work"] = run.get("run", {}).get("work_id", "")
    check("workflow_run_started", bool(rid), str(run)[:160])
    rd: dict = {}
    for _ in range(90):
        rd = bill.get(f"/api/v1/workflows/runs/{rid}")
        st = rd.get("run", {}).get("status")
        if st in ("waiting_human", "succeeded", "failed"):
            break
        time.sleep(0.5)
    check("workflow_reached_approval_or_terminal",
          rd.get("run", {}).get("status") in
          ("waiting_human", "succeeded", "failed"),
          rd.get("run", {}).get("status"))
    if rd.get("run", {}).get("status") == "waiting_human":
        bill.post(f"/api/v1/workflows/runs/{rid}/approve",
                  {"decision": "approved"})
    for _ in range(90):
        rd = bill.get(f"/api/v1/workflows/runs/{rid}")
        if rd.get("run", {}).get("status") in (
                "succeeded", "failed", "partial_failed"):
            break
        time.sleep(0.5)
    check("workflow_terminal",
          rd.get("run", {}).get("status") in
          ("succeeded", "partial_failed"),
          rd.get("run", {}).get("status"))
    check("workflow_run_scope_inherited",
          rd.get("run", {}).get("data_scope") == "uat_fixture"
          and rd.get("run", {}).get("test_run_id") == NS,
          {"data_scope": rd.get("run", {}).get("data_scope"),
           "test_run_id": rd.get("run", {}).get("test_run_id")})
    # 识别任务 ID（经 run 关联回查）
    rec_row = conn.execute(
        "SELECT task_id FROM recognition_task WHERE run_id IN (SELECT"
        " run_id FROM business_run_v1 WHERE parent_run_id=? OR"
        " run_id=?) LIMIT 1", (rid, rid)).fetchone()
    IDS["recognition_task"] = rec_row["task_id"] if rec_row else ""

    # ---- 6) Agent BI 草稿继承 scope + 失败账本 ----
    ag = bill.post("/api/v1/agents/analytics_agent/invoke",
                   {"text": "生成报表草稿", "customer_id": CUST,
                    "test_run_id": NS})
    IDS["agent_run"] = ag.get("run_id", "") or ag.get(
        "agent_run_id", "")
    check("agent_invoke_scoped", "_http" not in ag, str(ag)[:160])
    bi_row = conn.execute(
        "SELECT spec_id, data_scope, test_run_id FROM bi_report_spec_v1"
        " WHERE created_at >= datetime('now','-15 minutes') ORDER BY"
        " created_at DESC LIMIT 1").fetchone()
    IDS["bi_report"] = bi_row["spec_id"] if bi_row else ""
    check("agent_bi_draft_inherits_scope",
          bi_row is not None and bi_row["data_scope"] == "uat_fixture"
          and bi_row["test_run_id"] == NS,
          dict(bi_row) if bi_row else None)
    agf = bill.post("/api/v1/agents/no_such_agent_v5/invoke",
                    {"text": "故意失败", "customer_id": CUST,
                     "test_run_id": NS})
    fail_row = conn.execute(
        "SELECT run_id, data_scope, test_run_id FROM business_run_v1"
        " WHERE command_kind='agent.invoke' AND status IN"
        " ('failed','partial_failed') ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    IDS["agent_failed_run"] = fail_row["run_id"] if fail_row else ""
    check("agent_failure_ledger_recorded",
          agf.get("_http") in (409,) and fail_row is not None
          and fail_row["data_scope"] == "uat_fixture"
          and fail_row["test_run_id"] == NS,
          dict(fail_row) if fail_row else agf)

    # ---- 7) 异常 → Agent 追问 → 真人回答 → 报表 v2 ----
    an = bill.post("/api/v1/analytics/anomalies/check",
                   {"metric_id": "recognition.photos",
                    "customer_id": CUST, "op": "ge", "threshold": 0,
                    "test_run_id": NS})
    ano = an.get("anomaly") or {}
    IDS["anomaly"] = ano.get("anomaly_id", "")
    check("anomaly_triggered", an.get("hit") is True
          and bool(IDS["anomaly"]), str(an)[:140])
    rep = bill.post("/api/v1/analytics/reports",
                    {"name": f"UAT V5 报表 {NS}",
                     "metrics": ["recognition.photos"],
                     "customer_id": CUST, "test_run_id": NS})
    spec_id = rep.get("report", {}).get("spec_id", "")
    bill.post(f"/api/v1/analytics/reports/{spec_id}/approve", {})
    bill.post(f"/api/v1/analytics/reports/{spec_id}/publish", {})
    if IDS["anomaly"]:
        ans = bill.post(f"/api/v1/analytics/anomalies/"
                        f"{IDS['anomaly']}/answer",
                        {"answer": "UAT V5：反光误检，已安排重拍"})
        check("anomaly_answered_resolved",
              ans.get("anomaly", {}).get("status") == "resolved",
              str(ans)[:120])
    vers = bill.get(f"/api/v1/analytics/reports/{spec_id}/versions")
    nv = len(vers.get("versions", []))
    check("report_new_version_after_answer", nv >= 2,
          f"versions={nv}")

    # ---- 8) Usage 下钻 + fixture 不进运营口径 ----
    rows = bill.get(f"/api/v1/usage/rows?customer_id={CUST}")
    usage_rows = rows.get("rows", [])
    IDS["usage"] = usage_rows[0]["usage_id"] if usage_rows else ""
    ev_row = conn.execute(
        "SELECT evidence_id FROM evidence_bundle_v1 WHERE run_id IN"
        " (SELECT run_id FROM business_run_v1 WHERE test_run_id=?)"
        " LIMIT 1", (NS,)).fetchone()
    IDS["evidence"] = ev_row["evidence_id"] if ev_row else ""
    check("usage_drilldown_with_run_evidence",
          bool(usage_rows)
          and any(r.get("run_status") for r in usage_rows)
          and bool(IDS["evidence"]), f"rows={len(usage_rows)}")
    summ = bill.get("/api/v1/usage/summary")
    fx_units = sum(u["total"] for u in summ.get("by_unit", []))
    op_rows = bill.get("/api/v1/usage/rows")
    check("operational_usage_excludes_fixture",
          all(r.get("run_id", "") not in {rid} for r in
              op_rows.get("rows", [])),
          f"summary_total={fx_units}")

    # ---- 9) UAT 进行中：运营端 0 fixture ----
    cal = bill.get("/api/v1/calendar/events").get("events", [])
    check("home_zero_fixture_during_uat",
          not any(NS in json.dumps(e, ensure_ascii=False)
                  for e in cal), f"calendar={len(cal)}")
    custs = bill.get("/api/v1/master/customers").get("customers", [])
    check("customer_list_zero_fixture",
          not any(c0.get("customer_id") in (CUST, CUST2)
                  for c0 in custs), f"visible={len(custs)}")
    wfs = bill.get("/api/v1/workflows").get("definitions", [])
    check("workflow_list_zero_fixture",
          not any(NS in (w.get("name") or "") for w in wfs),
          f"visible={len(wfs)}")

    # ---- 10) 归档 + 全 Domain 泄漏=0 + 中心保留历史 ----
    arc = bill.post("/api/v1/test-data/archive", {"namespace": NS})
    check("archive_ok", bool(arc.get("archived_at")), arc)
    center = bill.get("/api/v1/test-data/center")
    scan = center.get("scope_scan", {})
    check("post_archive_leakage_zero",
          scan.get("operational_leakage") == {},
          scan.get("operational_leakage"))
    check("post_archive_test_run_full",
          scan.get("fixture_missing_test_run") == 0,
          scan.get("fixture_missing_test_run"))
    check("post_archive_parent_child_ok",
          scan.get("parent_child_mismatch") == 0,
          scan.get("parent_child_mismatch"))
    my_run = next((r for r in center.get("test_runs", [])
                   if r["test_run_id"] == NS), None)
    check("center_keeps_history", my_run is not None
          and my_run.get("status") == "archived"
          and (my_run.get("objects", {}).get("runs", 0) >= 1),
          my_run.get("objects") if my_run else None)
    cal2 = bill.get("/api/v1/calendar/events").get("events", [])
    check("home_zero_fixture_after_archive",
          not any(NS in json.dumps(e, ensure_ascii=False)
                  for e in cal2), f"calendar={len(cal2)}")

    # ---- 11) 泄漏注入负例：Gate freshness 必须 STALE/BLOCKED ----
    gate_before = bill.get("/api/v1/control/gate")
    leak_wid = "work-" + NS + "-leak"
    conn.execute(
        "INSERT INTO work_item_v2 (work_id, run_id, customer_id,"
        " status, title, visibility, created_at, updated_at)"
        " VALUES (?,?,?,'running','泄漏注入 SI3','current',"
        "datetime('now'),datetime('now'))", (leak_wid, rid, CUST))
    conn.commit()
    gate_leak = bill.get("/api/v1/control/gate")
    check("gate_reacts_to_leak_injection",
          gate_leak.get("gate") != "READY_FOR_REAL_DATA_UAT"
          and gate_leak.get("gate") != gate_before.get("gate", ""),
          f"{gate_before.get('gate')} → {gate_leak.get('gate')}")
    # 修复：把注入行结构性归档为 fixture
    conn.execute(
        "UPDATE work_item_v2 SET data_scope='uat_fixture',"
        " visibility='history', superseded_at=datetime('now') WHERE"
        " work_id=?", (leak_wid,))
    conn.commit()
    gate_fixed = bill.get("/api/v1/control/gate")
    check("gate_recovers_after_repair",
          gate_fixed.get("gate") != "BLOCKED_BY_SCOPE_INTEGRITY"
          or "db_fingerprint" in json.dumps(
              gate_fixed.get("reasons", [])),
          gate_fixed.get("gate"))
    conn.close()

    failed = [c for c in checks if not c["ok"]]
    report = {"protocol": "uatv5", "namespace": NS,
              "customer_id": CUST,
              "checks": checks, "failed": len(failed),
              "duration_seconds": round(time.time() - t0, 1),
              "run_started_utc": datetime.now(timezone.utc).isoformat(),
              "ids": IDS}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"\n{'✅ UAT V5 全链通过' if not failed else '❌ 存在失败'}"
          f"（{len(checks) - len(failed)}/{len(checks)}），"
          f"报告：{REPORT}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
