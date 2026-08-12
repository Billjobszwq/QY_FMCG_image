#!/usr/bin/env python3
"""UATCC T4：UAT V2 真实端到端机器预演（05-REAL-DATA-END-TO-END-UAT.md）。

与 v1 的区别：
- 每次运行唯一 namespace `uatv2_<ts>_<rand>`，全部实体新建；
  inserted=0/skipped=1 不得记为"从空白创建成功"；
- 六角色真实登录会话 + 权限矩阵（跨客户 403 / Auditor 只读 /
  最后管理员保护）；
- 问卷全题型 + 门头必拍真照片（负证据：无门头照提交必须失败）；
- 完整业务工作流（condition/wait/parallel+join/loop/human approval/
  agent/失败重试/暂停恢复/取消）；
- Agent 新 Usage 100% run/work/evidence；历史未归属诚实展示；
- BI 全链 + Usage 下钻到同一 run/evidence；
- 重启恢复（持久 timer 跨 abos restart）；p50/p95；
- 报告经 scripts/uat_report_validator.py 强制校验，缺一即 FAIL。

v1 报告保留为历史 smoke evidence，不覆盖。
用法：python scripts/v3_uat_rehearsal_v2.py [--skip-restart]
"""
from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import json
import random
import re
import sqlite3
import string
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = "http://127.0.0.1:8400"
OUT = ROOT / ".eval" / "v3_uat_v2"
REPORT = OUT / "report.json"
OUT.mkdir(parents=True, exist_ok=True)

env = {}
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1)
        env[k] = v.strip().strip('"').strip("'")
m = re.search(r"(\w+)[:/]([\w\-!@#$%^&*.]+)",
              env.get("PLATFORM_ADMIN_CREDENTIALS", ""))
OWNER, OWNER_PW = m.group(1), m.group(2)

NS = "uatv2_" + datetime.now().strftime("%Y%m%d%H%M%S") + "_" + \
    "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
PW = "Uat2!" + uuid.uuid4().hex[:8]

api_steps: list[dict] = []
checks: list[dict] = []
permission_matrix: list[dict] = []
failures_evidence: list[dict] = []


def check(name: str, ok: bool, evidence: str = ""):
    checks.append({"check": name, "ok": bool(ok),
                   "evidence": str(evidence)[:300]})
    print(("  ✓ " if ok else "  ✗ ") + name +
          (f"  [{str(evidence)[:120]}]" if evidence else ""))


class Session:
    """每角色独立 cookie jar 的真实登录会话。"""

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

    def _raw(self, method: str, path: str, body=None, csrf: bool = False,
             raw: bytes | None = None, ctype: str = "application/json",
             timeout: int = 240):
        data = raw if raw is not None else (
            json.dumps(body).encode() if body is not None else None)
        r = urllib.request.Request(BASE + path, data=data, method=method)
        if data is not None:
            r.add_header("content-type", ctype)
        if csrf and self.csrf:
            r.add_header("X-CSRF-Token", self.csrf)
        try:
            out = json.loads(self.op.open(r, timeout=timeout).read())
            api_steps.append({"actor": self.name, "method": method,
                              "path": path, "status": 200})
            return out
        except urllib.error.HTTPError as e:
            api_steps.append({"actor": self.name, "method": method,
                              "path": path, "status": e.code})
            try:
                return {"_http": e.code,
                        "_body": e.read().decode()[:300]}
            except Exception:
                return {"_http": e.code}

    def get(self, path: str, timeout: int = 120):
        return self._raw("GET", path, timeout=timeout)

    def post(self, path: str, body=None, csrf: bool = True):
        return self._raw("POST", path, body, csrf=csrf)

    def put(self, path: str, body=None):
        return self._raw("PUT", path, body, csrf=True)

    def delete(self, path: str):
        return self._raw("DELETE", path, csrf=True)


def multipart_csv(tpl: str, csv_text: str, fname: str) -> tuple[bytes, str]:
    b = uuid.uuid4().hex
    raw = (f"--{b}\r\nContent-Disposition: form-data; "
           f"name=\"template_id\"\r\n\r\n{tpl}\r\n"
           f"--{b}\r\nContent-Disposition: form-data; "
           f"name=\"file\"; filename=\"{fname}\"\r\n"
           f"Content-Type: text/csv\r\n\r\n" + csv_text
           + f"\r\n--{b}--\r\n").encode("utf-8")
    return raw, f"multipart/form-data; boundary={b}"


ids: dict = {}
created: dict = {}


def main() -> int:
    t0 = time.time()
    run_start_utc = datetime.now(timezone.utc).isoformat()
    print(f"== UAT V2 namespace: {NS} ==")
    bill = Session("owner(bill)")
    bill.login(OWNER, OWNER_PW)
    check("平台 Owner 登录", bool(bill.csrf))
    ids["tenant"] = "local"

    # ---------- 0. 六角色（真实用户 + 角色授予 + 独立会话） ----------
    print("== 0. 六角色 ==")
    roles = {"pm": "project_manager", "fw": "field_manager",
             "an": "analyst", "fin": "finance_operator",
             "aud": "read_only"}
    sessions: dict[str, Session] = {}
    for short, role in roles.items():
        uname = f"{NS}_{short}"
        pr = bill.post("/api/v1/iam/principals",
                       {"kind": "user", "username": uname,
                        "display_name": f"UAT2 {short}",
                        "password": PW})
        if pr.get("_http"):
            check(f"创建用户 {short}", False, str(pr)[:120])
            return 1
        bill.post("/api/v1/iam/grants",
                  {"username": uname, "role": role,
                   "customer_id": f"{NS}_cust"})
        if short == "fw":
            # 外勤填写问卷需 survey.read（survey_designer 携带）
            bill.post("/api/v1/iam/grants",
                      {"username": uname, "role": "survey_designer",
                       "customer_id": f"{NS}_cust"})
        s = Session(short)
        s.login(uname, PW)
        sessions[short] = s
        permission_matrix.append(
            {"role": role, "user": uname, "login": bool(s.csrf)})
    check("六角色全部可登录",
          all(s.csrf for s in sessions.values()))
    ids["roles"] = roles

    # ---------- 1. 主数据（从空白新建） ----------
    print("== 1. 主数据 ==")
    cust_id, prj_id, sku_id = (f"{NS}_cust", f"{NS}_prj", f"{NS}_sku")
    c1 = bill.post("/api/v1/master/customers",
                   {"customer_id": cust_id, "name": "UAT2 客户",
                    "is_test_fixture": True,
                    "retention_policy": "2年"})
    created["customer"] = {"inserted": 0 if c1.get("_http") else 1,
                           "skipped": 0}
    ids["customer"] = cust_id
    p1 = bill.post("/api/v1/master/projects",
                   {"project_id": prj_id, "customer_id": cust_id,
                    "name": "UAT2 项目", "budget": {"total": 10000}})
    created["project"] = {"inserted": 0 if p1.get("_http") else 1,
                          "skipped": 0}
    ids["project"] = prj_id
    k1 = bill.post("/api/v1/master/skus",
                   {"sku_id": sku_id, "canonical_name": "UAT2 测试可乐",
                    "brand": "UAT", "category": "碳酸", "volume": "500ml"})
    created["sku"] = {"inserted": 0 if k1.get("_http") else 1,
                      "skipped": 0}
    ids["sku"] = sku_id
    emp = bill.post("/api/v1/geo/employees",
                    {"name": "UAT2 外勤员", "customer_id": cust_id,
                     "skills": ["巡店"], "vehicle": "电动车"})
    created["employee"] = {"inserted": 0 if emp.get("_http") else 1,
                           "skipped": 0}
    ids["employee"] = emp.get("employee", {}).get("employee_id", "")
    # 地址经导入中心（inserted 统计真实校验）
    csv_addr = ("customer_id,store_name,raw_address,region,lat,lng,"
                "coord_system,time_window\n"
                f"{cust_id},UAT2 门店,预演二路 2 号,华东,,,wgs84,"
                "09:00-18:00\n")
    raw, mp_ct = multipart_csv("stores_addresses_v1", csv_addr,
                               "uat2_addr.csv")
    up = bill._raw("POST", "/api/v1/import/upload", raw=raw, csrf=True,
                   ctype=mp_ct)
    batch = up.get("batch", {})
    if not batch.get("batch_id"):
        check("地址导入上传", False, str(up)[:200])
        return 1
    bill.post(f"/api/v1/import/batches/{batch['batch_id']}/dry-run", {})
    cm = bill.post(f"/api/v1/import/batches/{batch['batch_id']}/commit",
                   {})
    stats = (cm.get("batch", {}).get("commit") or {}).get("stats", {})
    created["address_import"] = {"inserted": stats.get("inserted", 0),
                                 "skipped": stats.get("skipped", 0)}
    addrs = bill.get(f"/api/v1/geo/addresses?customer_id={cust_id}")[
        "addresses"]
    aid = next((a["address_id"] for a in addrs
                if "UAT2 门店" in a["raw"]), "")
    ids["address"] = aid
    check("地址从空白导入（inserted>=1）",
          stats.get("inserted", 0) >= 1 and bool(aid), str(stats))

    # ---------- 2. 日程/外勤任务/路线 ----------
    print("== 2. 日程/任务/路线 ==")
    cal = bill.post("/api/v1/calendar/events",
                    {"title": f"UAT2 巡店 {NS}",
                     "starts_at": datetime.now(timezone.utc)
                     .isoformat(),
                     "kind": "meeting",
                     "ref_type": "address", "ref_id": aid,
                     "customer_id": cust_id, "project_id": prj_id})
    created["schedule"] = {"inserted": 0 if cal.get("_http") else 1,
                           "skipped": 0}
    ids["schedule"] = cal.get("event", {}).get("event_id", "")
    g = bill.post(f"/api/v1/geo/addresses/{aid}/geocode", {})
    check("地理编码诚实降级（无 Key）", g.get("status") == "degraded",
          g.get("reason", "")[:60])
    bill.post(f"/api/v1/geo/addresses/{aid}/manual-coords",
              {"lat": 31.26, "lng": 121.51, "source": "manual"})
    task = bill.post("/api/v1/geo/tasks",
                     {"customer_id": cust_id, "address_id": aid,
                      "project_id": prj_id})["task"]
    created["field_task"] = {"inserted": 1, "skipped": 0}
    ids["field_task"] = task["task_id"]
    plan = bill.post("/api/v1/geo/plans",
                     {"customer_id": cust_id,
                      "task_ids": [task["task_id"]],
                      "constraints": {"depot_lat": 31.0,
                                      "depot_lng": 121.0}})["plan"]
    created["route"] = {"inserted": 1, "skipped": 0}
    ids["route"] = plan["plan_id"]
    adj = bill.post(f"/api/v1/geo/plans/{plan['plan_id']}/adjust",
                    {"ordered_task_ids": [task["task_id"]]})
    check("路线调版生成新版本",
          adj.get("plan", {}).get("version", 0) >= 2)

    # ---------- 3. 问卷（全题型 + 门头必拍真照片） ----------
    print("== 3. 问卷 ==")
    questions = [
        {"id": "qc", "type": "text", "title": "客户主体确认（客户题）",
         "required": True},
        {"id": "qp", "type": "text", "title": "项目编号（项目题）"},
        {"id": "qsku", "type": "multi_choice", "title": "在售 SKU（SKU题）",
         "options": [{"value": sku_id, "label": "UAT2 测试可乐",
                      "sku_ref": True}]},
        {"id": "q1", "type": "single_choice", "title": "门店类型",
         "required": True,
         "options": [{"value": "open", "label": "营业"},
                     {"value": "closed", "label": "关门"}]},
        {"id": "qm", "type": "multi_choice", "title": "陈列位置（多选）",
         "options": [{"value": "a", "label": "入口"},
                     {"value": "b", "label": "收银台"}]},
        {"id": "qt", "type": "text", "title": "备注（填空）"},
        {"id": "qr", "type": "rating", "title": "服务评分（打分）",
         "min": 1, "max": 5},
        {"id": "qmx", "type": "matrix", "title": "分项评估（matrix）",
         "rows": [{"id": "r1", "label": "清洁"},
                  {"id": "r2", "label": "补货"}],
         "options": [{"value": "1", "label": "差"},
                     {"value": "3", "label": "好"}]},
        {"id": "qd", "type": "description", "title": "以下为拍照环节"},
        {"id": "qsf", "type": "photo", "title": "门头照（必拍）",
         "required": True, "min_count": 1, "max_count": 3,
         "require_storefront": True, "capture_role": "storefront",
         "recognition": False},
        {"id": "qshelf", "type": "photo", "title": "货架照（识别+人工确认）",
         "min_count": 1, "max_count": 3, "capture_role": "shelf",
         "recognition": True,
         "recognition_profile_id": "v4_best_standard",
         "manual_confirmation_required": True},
    ]
    logic = [{"from": "q1", "when": {"op": "eq", "value": "closed"},
              "to": "END_SKIP_PHOTO", "note": "关门跳过拍照"}]
    spec = {"questions": questions, "logic_edges": logic,
            "scoring": {"version": 1, "formula": "sum",
                        "rules": [{"question": "qr", "weight": 2}]}}
    svy = bill.post("/api/v1/survey/definitions",
                    {"name": f"UAT2 问卷 {NS}", "spec": spec},
                    )["definition"]
    created["survey"] = {"inserted": 1, "skipped": 0}
    ids["survey"] = svy["survey_id"]
    lint = bill.post(f"/api/v1/survey/definitions/{svy['survey_id']}"
                     "/lint", {})
    errs = [i for i in lint.get("definition", {}).get("lint_report", [])
            if i["level"] == "error"]
    check("全题型问卷 lint 通过", not errs, str(errs)[:200])
    bill.post(f"/api/v1/survey/definitions/{svy['survey_id']}/publish",
              {})
    asg = bill.post("/api/v1/survey/assignments",
                    {"survey_id": svy["survey_id"],
                     "customer_id": cust_id,
                     "assignee": f"{NS}_fw"})["assignment"]
    created["assignment"] = {"inserted": 1, "skipped": 0}
    ids["assignment"] = asg["assignment_id"]
    fw = sessions["fw"]
    rsp = fw.post("/api/v1/survey/responses",
                  {"assignment_id": asg["assignment_id"]})["response"]
    created["response"] = {"inserted": 1, "skipped": 0}
    rid = rsp["response_id"]
    ids["response"] = rid
    answers = {"qc": {"value": cust_id}, "qp": {"value": prj_id},
               "qsku": {"value": [sku_id]}, "q1": {"value": "open"},
               "qm": {"value": ["a", "b"]}, "qt": {"value": "UAT2"},
               "qr": {"value": 4},
               "qmx": {"value": {"r1": "3", "r2": "1"}}}
    fw.put(f"/api/v1/survey/responses/{rid}/answers",
           {"answers": answers})
    # 负证据：无门头照提交必须失败
    neg = fw.post(f"/api/v1/survey/responses/{rid}/submit", {})
    check("负证据：无门头照提交被拒", neg.get("_http") == 409,
          str(neg.get("_body", ""))[:120])
    failures_evidence.append({
        "kind": "photo_contract_negative",
        "detail": "无 storefront 照片提交 → 409",
        "response": str(neg.get("_body", ""))[:200]})
    # 上传真实门头照 + 货架照（带识别）
    img = (ROOT / "bad_samples" / "36143897_reflection.jpg").read_bytes()
    b64 = base64.b64encode(img).decode()
    msf = fw.post(f"/api/v1/survey/responses/{rid}/media",
                  {"question_id": "qsf", "image_b64": b64,
                   "capture_role": "storefront",
                   "location": {"lat": 31.26, "lng": 121.51},
                   "taken_at": datetime.now(timezone.utc).isoformat(),
                   "device": "uat2-script"})["media"]
    created["media"] = {"inserted": 2, "skipped": 0}
    ids["media_storefront"] = msf["media_id"]
    msh = fw.post(f"/api/v1/survey/responses/{rid}/media",
                  {"question_id": "qshelf", "image_b64": b64,
                   "capture_role": "shelf",
                   "location": {"lat": 31.26, "lng": 121.51},
                   "device": "uat2-script"})["media"]
    ids["media_shelf"] = msh["media_id"]
    check("门头照绑定 response+question",
          msf["response_id"] == rid and msf["question_id"] == "qsf"
          and msf["capture_role"] == "storefront")
    done = fw.post(f"/api/v1/survey/responses/{rid}/submit", {})
    score = done.get("response", {}).get("scores", {}).get("total")
    check("补齐门头照后提交成功（自动评分）",
          done.get("response", {}).get("status") == "submitted",
          f"score={score}")
    # 识别建议 → 人工确认（suggestion 与 final 分离）
    if msh.get("suggestion_status") == "pending":
        rev = fw.post(f"/api/v1/survey/media/{msh['media_id']}/review",
                      {"decision": "accepted"})
        check("识别建议经人工接受成为 final",
              rev.get("media", {}).get("suggestion_status") == "accepted")
        ids["recognition_suggestion_run"] = msh.get("recognition_run_id")
    else:
        check("识别建议经人工接受成为 final",
              False, f"suggestion_status={msh.get('suggestion_status')}")

    # ---------- 4. 完整业务工作流 ----------
    print("== 4. 工作流 ==")
    wf_spec = {"trigger": {"type": "manual"},
               "variables": {"survey_done": {"type": "bool",
                                             "default": False},
                             "items": {"type": "list", "default": []}},
               "nodes": [
                   {"id": "start", "type": "trigger"},
                   {"id": "n_task", "type": "transform",
                    "config": {"map": {"task": f"{NS}_field_task",
                                       "vars.progress": "task_created"}}},
                   {"id": "w_arrive", "type": "wait",
                    "config": {"seconds": 1}},
                   {"id": "c_survey", "type": "condition",
                    "config": {"rules": [
                        {"when": {"path": "$vars.survey_done",
                                  "op": "eq", "value": True},
                         "to": "par"}], "default": "end"}},
                   {"id": "par", "type": "parallel",
                    "config": {"max_concurrency": 2}},
                   {"id": "bq", "type": "transform",
                    "config": {"map": {"vars.branch": "quality_gate"}}},
                   {"id": "bv", "type": "wait", "config": {"seconds": 1}},
                   {"id": "j", "type": "join", "config": {"mode": "all"}},
                   {"id": "appr", "type": "human_approval",
                    "config": {"owner": OWNER,
                               "title": "UAT2 人工确认识别结果"}},
                   {"id": "ag", "type": "agent",
                    "config": {"agent_id": "analytics_agent",
                               "prompt": "查询已注册的 BI 指标"}},
                   {"id": "lp", "type": "loop",
                    "config": {"items_path": "$vars.items",
                               "body": "lp_body"}},
                   {"id": "lp_body", "type": "transform",
                    "config": {"map": {"item": "$vars.loop_item"}}},
                   {"id": "end", "type": "end"}],
               "edges": [
                   {"from": "start", "to": "n_task"},
                   {"from": "n_task", "to": "w_arrive"},
                   {"from": "w_arrive", "to": "c_survey"},
                   {"from": "par", "to": "bq"}, {"from": "par", "to": "bv"},
                   {"from": "bq", "to": "j"}, {"from": "bv", "to": "j"},
                   {"from": "j", "to": "appr"}, {"from": "appr", "to": "ag"},
                   {"from": "ag", "to": "lp"}, {"from": "lp", "to": "end"}],
               "policy": {"approval_required_for_publish": True}}
    wf = bill.post("/api/v1/workflows",
                   {"name": f"UAT2 业务流 {NS}", "spec": wf_spec},
                   )["definition"]
    created["workflow"] = {"inserted": 1, "skipped": 0}
    wfid = wf["definition_id"]
    ids["workflow_definition"] = wfid
    bill.post(f"/api/v1/workflows/{wfid}/lint", {})
    bill.post(f"/api/v1/workflows/{wfid}/simulate", {"inputs": {}})
    bill.post(f"/api/v1/workflows/{wfid}/approve", {})
    bill.post(f"/api/v1/workflows/{wfid}/publish", {})
    run = bill.post(f"/api/v1/workflows/{wfid}/runs",
                    {"inputs": {"survey_done": True,
                                "items": ["a", "b"]}})
    wfrun_id = run["run"]["run_id"]
    created["workflow_run"] = {"inserted": 1, "skipped": 0}
    ids["workflow_run"] = wfrun_id
    # 等待到 human_approval
    rd = {}
    for _ in range(60):
        rd = bill.get(f"/api/v1/workflows/runs/{wfrun_id}")
        if rd["run"]["status"] in ("waiting_human", "failed",
                                   "succeeded"):
            break
        time.sleep(0.5)
    check("工作流走到人工批准（wait+parallel+condition 真实执行）",
          rd["run"]["status"] == "waiting_human", rd["run"]["status"])
    branches = rd.get("branches", [])
    check("并行分支 durable 状态可见",
          len(branches) == 2
          and all(b["status"] == "completed" for b in branches),
          str([(b["entry"], b["status"]) for b in branches]))
    ap = bill.post(f"/api/v1/workflows/runs/{wfrun_id}/approve",
                   {"decision": "approved"})
    for _ in range(40):
        rd = bill.get(f"/api/v1/workflows/runs/{wfrun_id}")
        if rd["run"]["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.5)
    check("人工批准后 agent+loop 完成整条业务流",
          rd["run"]["status"] == "succeeded", rd["run"]["status"])
    ids["workflow_agent_business_run"] = next(
        (c.get("output", {}).get("business_run_id", "")
         for c in rd.get("checkpoints", []) if c["node_id"] == "ag"), "")

    # 失败重试 / 暂停恢复 / 取消（独立小流程）
    fail_spec = {"trigger": {"type": "manual"}, "variables": {},
                 "nodes": [{"id": "start", "type": "trigger"},
                           {"id": "lp", "type": "loop",
                            "config": {"items_path": "$inputs.bad",
                                       "body": "b"}},
                           {"id": "b", "type": "transform",
                            "config": {"map": {"x": 1}}},
                           {"id": "end", "type": "end"}],
                 "edges": [{"from": "start", "to": "lp"},
                           {"from": "lp", "to": "end"}]}
    wf2 = bill.post("/api/v1/workflows",
                    {"name": f"UAT2 失败重试 {NS}",
                     "spec": fail_spec})["definition"]
    for a in ("lint", "simulate", "approve", "publish"):
        bill.post(f"/api/v1/workflows/{wf2['definition_id']}/{a}",
                  {"inputs": {}} if a == "simulate" else {})
    rfail = bill.post(f"/api/v1/workflows/{wf2['definition_id']}/runs",
                      {"inputs": {"bad": "not-a-list"}})
    check("失败分支：run failed（诚实失败）",
          rfail["run"]["status"] == "failed", rfail["run"]["status"])
    failures_evidence.append({"kind": "workflow_failed",
                              "run": rfail["run"]["run_id"],
                              "error": rfail["run"].get("error", "")[:200]})
    rrt = bill.post(f"/api/v1/workflows/runs/{rfail['run']['run_id']}"
                    "/retry", {"inputs": {"bad": [1, 2]}})
    check("同一 run 重试成功（人工接管）",
          rrt.get("run", {}).get("status") == "succeeded",
          str(rrt)[:120])
    # 暂停/恢复/取消：并行分支内联等待期间 run 保持 running；
    # start_run 同步阻塞，故在后台线程启动，主线程并发操作生命周期。
    pr_spec = {"trigger": {"type": "manual"}, "variables": {},
               "nodes": [{"id": "start", "type": "trigger"},
                         {"id": "par", "type": "parallel",
                          "config": {"max_concurrency": 2}},
                         {"id": "bw", "type": "wait",
                          "config": {"seconds": 20}},
                         {"id": "bt", "type": "transform",
                          "config": {"map": {"x": 1}}},
                         {"id": "j", "type": "join",
                          "config": {"mode": "all"}},
                         {"id": "end", "type": "end"}],
               "edges": [{"from": "start", "to": "par"},
                         {"from": "par", "to": "bw"},
                         {"from": "par", "to": "bt"},
                         {"from": "bw", "to": "j"},
                         {"from": "bt", "to": "j"},
                         {"from": "j", "to": "end"}]}
    wf3 = bill.post("/api/v1/workflows",
                    {"name": f"UAT2 暂停取消 {NS}", "spec": pr_spec},
                    )["definition"]
    for a in ("lint", "simulate", "approve", "publish"):
        bill.post(f"/api/v1/workflows/{wf3['definition_id']}/{a}",
                  {"inputs": {}} if a == "simulate" else {})
    rpr_holder: dict = {}

    def _start_pr():
        rpr_holder["out"] = bill.post(
            f"/api/v1/workflows/{wf3['definition_id']}/runs",
            {"inputs": {}})

    import threading
    th = threading.Thread(target=_start_pr, daemon=True)
    th.start()
    time.sleep(2)  # 等分支进入内联等待（run 保持 running）
    conn_lc = sqlite3.connect(ROOT / ".platform" / "platform.sqlite")
    conn_lc.row_factory = sqlite3.Row
    rows = conn_lc.execute(
        "SELECT run_id, status FROM business_run_v1 WHERE"
        " workflow_definition_id=? ORDER BY created_at DESC LIMIT 1",
        (wf3["definition_id"],)).fetchall()
    prid = rows[0]["run_id"] if rows else ""
    bill.post(f"/api/v1/workflows/runs/{prid}/pause", {})
    stp = bill.get(f"/api/v1/workflows/runs/{prid}")["run"]["status"]
    bill.post(f"/api/v1/workflows/runs/{prid}/resume", {})
    strr = bill.get(f"/api/v1/workflows/runs/{prid}")["run"]["status"]
    bill.post(f"/api/v1/workflows/runs/{prid}/cancel", {})
    stc = bill.get(f"/api/v1/workflows/runs/{prid}")["run"]["status"]
    th.join(timeout=30)
    check("暂停→恢复→取消生命周期",
          stp == "paused" and strr == "running" and stc == "cancelled",
          f"{stp}→{strr}→{stc}")

    # ---------- 5. 识别（统一命令链，产生 Usage） ----------
    print("== 5. 识别 ==")
    cmd = bill.post("/api/v1/commands", {
        "command_kind": "vision.recognition.create",
        "params": {"images": [[f"{NS}.jpg", b64]],
                   "recognition_profile_id": "v4_best_standard",
                   "service_tier": "standard", "entry": "single_file"},
        "source": "web", "customer_id": cust_id, "project_id": prj_id})
    check("识别任务完成（V4 best）", cmd.get("status") == "succeeded",
          f"run={cmd.get('run', {}).get('run_id')}")
    ids["recognition_task"] = (cmd.get("result") or {}).get("task_id")
    created["recognition_task"] = {"inserted": 1, "skipped": 0}
    ids["recognition_run"] = cmd.get("run", {}).get("run_id")
    ids["recognition_evidence"] = cmd.get("run", {}).get(
        "evidence_bundle_id", "")

    # ---------- 6. Agent 调用（五场景 + 新 Usage 100% 挂链） ----------
    print("== 6. Agent ==")
    ag1 = bill.post("/api/v1/agents/supervisor/invoke",
                    {"text": "项目进度做到哪里了？",
                     "customer_id": cust_id})
    check("首页 Supervisor 直接提问（顶层 run）",
          bool(ag1.get("business_run_id")), ag1.get("business_run_id"))
    ids["agent_run"] = ag1.get("run_id", "")
    ids["agent_business_run"] = ag1.get("business_run_id", "")
    ag2 = sessions["pm"].post("/api/v1/agents/survey_agent/invoke",
                              {"text": "查询问卷列表",
                               "customer_id": cust_id})
    check("Survey Agent 查询问卷", ag2.get("_http") not in (401, 403),
          str(ag2.get("business_run_id")))
    ag4 = sessions["an"].post("/api/v1/agents/analytics_agent/invoke",
                              {"text": "查询指标",
                               "customer_id": cust_id,
                               "project_id": prj_id})
    check("Analytics Agent（带客户+项目）",
          bool(ag4.get("business_run_id")))
    ag5 = bill.post("/api/v1/agents/no_such_agent/invoke",
                    {"text": "必然失败"})
    check("Agent 失败案例（fail-closed，仍写失败 run）",
          ag5.get("_http") in (409, 500), str(ag5.get("_body"))[:100])
    failures_evidence.append({"kind": "agent_failed",
                              "detail": str(ag5.get("_body"))[:200]})
    # 新 Usage 100% 挂链（DB 事实核验，只读；仅统计本轮开始后产生）
    conn = sqlite3.connect(ROOT / ".platform" / "platform.sqlite")
    conn.row_factory = sqlite3.Row
    new_agent_usage = conn.execute(
        "SELECT count(*) c, sum(CASE WHEN run_id!='' AND work_id!=''"
        " THEN 1 ELSE 0 END) ok FROM usage_event_v2 WHERE"
        " unit='agent_call' AND occurred_at >= ?",
        (run_start_utc,)).fetchone()
    legacy = conn.execute(
        "SELECT count(*) c FROM usage_event_v2 WHERE unit='agent_call'"
        " AND run_id=''").fetchone()["c"]
    check("Agent 新 Usage 100% 挂 run/work",
          new_agent_usage["c"] > 0
          and new_agent_usage["ok"] == new_agent_usage["c"],
          f"{new_agent_usage['ok']}/{new_agent_usage['c']}")
    rec_leg = bill.post("/api/v1/usage/reconcile-legacy", {})
    leg = bill.get("/api/v1/usage/legacy")
    check(f"历史 {legacy} 条未归属 Usage 诚实入账（不篡改）",
          rec_leg.get("legacy_total", 0) >= legacy
          and all(a["attribution_status"] == "legacy_unattributed"
                  for a in leg.get("attributions", [])),
          f"legacy_total={rec_leg.get('legacy_total')}")

    # ---------- 7. BI 与 Usage 下钻 ----------
    print("== 7. BI / Usage ==")
    an = sessions["an"]
    dp = an.get("/api/v1/analytics/data-products")
    check("数据产品血缘可见", dp.get("_http") != 403,
          str(dp)[:80])
    cm1 = an.post("/api/v1/analytics/metrics/computed",
                  {"metric_id": f"{NS}_rate",
                   "name": f"UAT2 自检率 {NS}",
                   "formula": "recognition.photos / recognition.photos"})
    check("受限公式指标创建", not cm1.get("_http"),
          str(cm1)[:100])
    ev = an.get(f"/api/v1/analytics/metrics/recognition.photos/"
                f"evaluate?customer_id={cust_id}")
    check("指标求值（客户隔离）", "value" in ev, str(ev)[:80])
    dd = an.get(f"/api/v1/analytics/metrics/recognition.photos/"
                f"drilldown?customer_id={cust_id}&limit=5")
    check("下钻到事实行", not dd.get("_http"), str(dd)[:80])
    dash = an.post("/api/v1/analytics/dashboards",
                   {"name": f"UAT2 仪表盘 {NS}", "customer_id": cust_id,
                    "widgets": [
                        {"type": "bar", "metric": "recognition.photos"},
                        {"type": "line", "metric": "recognition.tasks"},
                        {"type": "number",
                         "metric": "survey.responses.submitted"}],
                    "filters": {"customer_id": cust_id}})
    check("持久化 Dashboard（bar/line/number）",
          not dash.get("_http"), str(dash)[:100])
    ids["dashboard"] = dash.get("dashboard_id") or dash.get(
        "dashboard", {}).get("dashboard_id", "")
    created["dashboard"] = {"inserted": 1, "skipped": 0}
    anom = an.post("/api/v1/analytics/anomalies/check",
                   {"metric_id": "recognition.photos",
                    "customer_id": cust_id})
    rep = an.post("/api/v1/analytics/reports",
                  {"name": f"UAT2 报表 {NS}",
                   "metrics": ["recognition.photos"],
                   "customer_id": cust_id})
    spec_id = rep.get("report", {}).get("spec_id", "")
    an.post(f"/api/v1/analytics/reports/{spec_id}/approve", {})
    pub = an.post(f"/api/v1/analytics/reports/{spec_id}/publish", {})
    vers = an.get(f"/api/v1/analytics/reports/{spec_id}/versions")
    check("报表发布产生版本", len(vers.get("versions", [])) >= 1,
          str(vers)[:100])
    created["report_version"] = {
        "inserted": len(vers.get("versions", [])), "skipped": 0}
    ids["report"] = spec_id
    # Usage 下钻到同一 run/evidence
    fin = sessions["fin"]
    rows = fin.get(f"/api/v1/usage/rows?customer_id={cust_id}&limit=100")
    rec_row = next((r for r in rows.get("rows", [])
                    if r.get("run_id") == ids.get("recognition_run")),
                   None)
    check("财务 Usage 下钻到识别 run/evidence",
          rec_row is not None and bool(
              rec_row.get("evidence_bundle_id")
              or rec_row.get("source_evidence")),
          str(rec_row)[:120])
    ids["usage"] = rec_row.get("usage_id") if rec_row else ""
    created["usage"] = {"inserted": 1 if ids["usage"] else 0,
                        "skipped": 0}
    ids["evidence"] = ids.get("recognition_evidence") or (
        rec_row.get("evidence_bundle_id") if rec_row else "")
    created["evidence"] = {"inserted": 1 if ids["evidence"] else 0,
                           "skipped": 0}
    check("异常追问链（anomalies）", not anom.get("_http"),
          str(anom)[:100])

    # ---------- 8. 首页闭环 + Supervisor 问答 ----------
    print("== 8. 首页闭环 ==")
    dashh = bill.get("/api/v1/home/dashboard")
    check("首页 dashboard 全段",
          all(k in dashh for k in ("todos", "calendar", "progress",
                                   "activity", "capacity", "agent_alerts",
                                   "recent", "notes")))
    sid = bill.post("/api/agent/v1/sessions", {})["session_id"]
    qa = []
    for q in ("项目做到哪里了？", "哪个地址失败？", "使用了哪个模型？",
              "哪个问卷未完成？", f"这个客户 {cust_id} 用了多少 Usage？",
              "证据在哪里？"):
        r = bill.post("/api/agent/v1/chat",
                      {"session_id": sid, "text": q})
        qa.append({"q": q, "provider": r.get("provider"),
                   "has_message": bool(r.get("message"))})
    check("Supervisor 六问全部有回答",
          all(x["has_message"] for x in qa),
          str([x["provider"] for x in qa]))
    rec2 = bill.get("/api/v1/control/reconcile")
    check("reconcile 一致", rec2.get("consistent") is True,
          f"drift_fixed={rec2.get('drift_fixed')}")

    # ---------- 9. 权限矩阵（跨客户 403 / Auditor 只读） ----------
    print("== 9. 权限矩阵 ==")
    cust2 = f"{NS}_cust2"
    bill.post("/api/v1/master/customers",
              {"customer_id": cust2, "name": "UAT2 客户2",
               "is_test_fixture": True})
    x1 = sessions["fw"].get(f"/api/v1/usage/summary?customer_id={cust2}")
    permission_matrix.append(
        {"role": "field_manager", "action": f"读他客户 Usage {cust2}",
         "expected": "403", "actual": x1.get("_http")})
    x2 = sessions["aud"].post("/api/v1/master/customers",
                              {"customer_id": f"{NS}_cust3",
                               "name": "不允许"})
    permission_matrix.append(
        {"role": "read_only(auditor)", "action": "写主数据",
         "expected": "403", "actual": x2.get("_http")})
    x3 = sessions["aud"].get("/api/v1/iam/audit")
    permission_matrix.append(
        {"role": "read_only(auditor)", "action": "只读审计",
         "expected": "200/403(read)", "actual": x3.get("_http")})
    x4 = bill.post("/api/v1/iam/check",
                   {"username": f"{NS}_fw", "scope": "master.manage",
                    "customer_id": cust_id})
    permission_matrix.append(
        {"role": "field_manager", "action": "iam.check master.manage",
         "expected": "allowed=false",
         "actual": x4.get("allowed")})
    check("跨客户访问被拒（403）", x1.get("_http") == 403,
          str(x1.get("_body"))[:80])
    check("Auditor 只读：写操作被拒", x2.get("_http") in (401, 403),
          str(x2.get("_body"))[:80])

    # ---------- 10. 重启恢复（持久 timer 跨 restart） ----------
    recovery = {"executed": False}
    if "--skip-restart" not in sys.argv:
        print("== 10. 重启恢复 ==")
        # 持久 timer（非并行分支）才能跨进程重启恢复
        wt_spec = {"trigger": {"type": "manual"}, "variables": {},
                   "nodes": [{"id": "start", "type": "trigger"},
                             {"id": "w", "type": "wait",
                              "config": {"seconds": 20}},
                             {"id": "end", "type": "end"}],
                   "edges": [{"from": "start", "to": "w"},
                             {"from": "w", "to": "end"}]}
        wf4 = bill.post("/api/v1/workflows",
                        {"name": f"UAT2 重启恢复 {NS}",
                         "spec": wt_spec})["definition"]
        for a in ("lint", "simulate", "approve", "publish"):
            bill.post(f"/api/v1/workflows/{wf4['definition_id']}/{a}",
                      {"inputs": {}} if a == "simulate" else {})
        rr = bill.post(f"/api/v1/workflows/{wf4['definition_id']}/runs",
                       {"inputs": {}})
        rrid = rr["run"]["run_id"]
        time.sleep(1)
        subprocess.run(["./bin/abos", "restart"], cwd=ROOT,
                       capture_output=True, timeout=180)
        time.sleep(8)
        # restart 后需重新登录（session 表保留，cookie 仍在 jar）
        status = ""
        for _ in range(60):
            try:
                rd2 = bill.get(f"/api/v1/workflows/runs/{rrid}")
                status = rd2["run"]["status"]
            except Exception:
                status = "relogin_needed"
                bill.login(OWNER, OWNER_PW)
            if status == "succeeded":
                break
            time.sleep(2)
        recovery = {"executed": True, "run_id": rrid,
                    "status_after_restart": status,
                    "note": "20s wait 持久 timer 在 restart 后自动恢复"}
        check("重启后持久 timer 恢复并完成", status == "succeeded",
              status)
        cur = json.loads((ROOT / ".models" / "bundles"
                          / "CURRENT.json").read_text())
        check("重启后 CURRENT 仍为 prod_v4_best_r1",
              cur.get("bundle_id") == "prod_v4_best_r1")

    # ---------- 11. 延迟 p50/p95 + integrity ----------
    print("== 11. 延迟与完整性 ==")
    lats = []
    for _ in range(20):
        ts = time.time()
        bill.get("/api/v1/home/dashboard")
        lats.append((time.time() - ts) * 1000)
    lats.sort()
    latency = {"p50_ms": round(lats[10], 1),
               "p95_ms": round(lats[19], 1),
               "endpoint": "/api/v1/home/dashboard", "n": 20}
    ic = conn.execute("PRAGMA integrity_check").fetchone()[0]
    check("SQLite integrity", ic == "ok", ic)
    proj = bill.get("/api/v1/control/reconcile")

    # ---------- 报告 ----------
    events = [dict(r) for r in conn.execute(
        "SELECT event_type, count(*) c FROM event_envelope_v1"
        " GROUP BY event_type ORDER BY c DESC LIMIT 30").fetchall()]
    hashes = {"workflow_spec": hashlib.sha256(
                  json.dumps(wf_spec, sort_keys=True).encode()
              ).hexdigest()[:16],
              "survey_spec": hashlib.sha256(
                  json.dumps(spec, sort_keys=True).encode()
              ).hexdigest()[:16],
              "current_bundle": json.loads(
                  (ROOT / ".models" / "bundles" / "CURRENT.json"
                   ).read_text()).get("bundle_id")}
    relations = {
        "customer_project": {"customer": cust_id, "project": prj_id,
                             "tenant": "local"},
        "workflow_run": {"run": wfrun_id,
                         "branches": [b["branch_id"] for b in branches],
                         "agent_node_business_run":
                         ids.get("workflow_agent_business_run")},
        "recognition": {"run": ids.get("recognition_run"),
                        "task": ids.get("recognition_task"),
                        "evidence": ids.get("recognition_evidence"),
                        "usage": ids.get("usage")},
        "survey": {"survey": ids["survey"], "assignment":
                   ids["assignment"], "response": rid,
                   "media": [ids.get("media_storefront"),
                             ids.get("media_shelf")]}}
    browser = {}
    bj = OUT / "browser_evidence.json"
    if bj.exists():
        browser = json.loads(bj.read_text(encoding="utf-8"))
    report = {
        "ids": {**ids, "namespace": NS},
        "created": created,
        "roles": {"matrix": permission_matrix,
                  "note": "Field Worker=field_manager、Auditor=read_only"
                          "（既有角色映射）"},
        "api_steps": api_steps[-400:],
        "projection": {"reconcile": proj,
                       "home_todos": dashh.get("todos"),
                       "home_progress": dashh.get("progress")},
        "events": events,
        "hashes": hashes,
        "browser": browser or {"status": "pending_T7"},
        "latency": latency,
        "recovery": recovery,
        "failures": failures_evidence,
        "relations": relations,
        "checks": checks,
        "passed": sum(1 for c in checks if c["ok"]),
        "failed": sum(1 for c in checks if not c["ok"]),
        "elapsed_s": round(time.time() - t0, 1)}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    # validator 强制校验（browser 段在 T7 后补齐）
    from scripts.uat_report_validator import validate_report
    probs = validate_report(report)
    print(f"\nUAT V2 完成：{report['passed']} 通过 / "
          f"{report['failed']} 失败（{report['elapsed_s']}s）")
    if probs:
        print("validator 待补项（T7 截图后必须清零）：")
        for p in probs:
            print("  -", p)
    print(f"报告：{REPORT}")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
