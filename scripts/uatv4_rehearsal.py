#!/usr/bin/env python3
"""SI2 T8：UAT V4 机器预演（04-UAT-V4-PROTOCOL）。

与 V3 的根本区别（P1-001/P1-002 修复验证）：
- 先 POST /api/v1/test-data/run 建立 Test Run 上下文，再在其内部
  创建全部对象；所有对象结构化携带 test_run_id（禁止先建后补标、
  禁止名称模式）；
- 全链断言：test_run_id 完整率=100%、父子 scope 一致、首页 0
  fixture、归档后全 Domain 泄漏=0、测试中心仍可见完整历史。

用法：python scripts/uatv4_rehearsal.py
"""
from __future__ import annotations

import base64
import http.cookiejar
import json
import random
import re
import string
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = "http://127.0.0.1:8400"
OUT = ROOT / ".eval" / "uat_scope_v2" / "uatv4"
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

NS = "uatv4_" + datetime.now().strftime("%Y%m%d%H%M%S") + "_" + \
    "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
CUST = NS + "_cust"

checks: list[dict] = []
IDS: dict[str, str] = {}


def check(name: str, ok: bool, evidence: str = "") -> None:
    checks.append({"check": name, "ok": bool(ok),
                   "evidence": str(evidence)[:300]})
    print(("  ✓ " if ok else "  ✗ ") + name +
          (f"  [{str(evidence)[:100]}]" if evidence else ""))


def _png(w=8, h=8) -> bytes:
    """最小合法 PNG（货架替身；识别诚实 0 检出也可）。"""
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
    print(f"[SI2-T8] UAT V4 namespace = {NS}")

    # ---- 0) Test Run 上下文必须先于一切对象 ----
    ctx = bill.post("/api/v1/test-data/run",
                    {"namespace": NS, "customer_ids": [CUST]})
    check("test_run_context_first", ctx.get("test_run_id") == NS, ctx)

    # ---- 1) fixture 主数据（全部显式携带 test_run_id） ----
    c = bill.post("/api/v1/master/customers",
                  {"customer_id": CUST, "name": "UAT V4 门店",
                   "test_run_id": NS})
    check("fixture_customer_scoped",
          c.get("customer", {}).get("customer_id") == CUST, c)
    pj = bill.post("/api/v1/master/projects",
                   {"project_id": NS + "_prj", "customer_id": CUST,
                    "name": "UAT V4 项目", "test_run_id": NS})
    check("fixture_project_scoped",
          pj.get("project", {}).get("project_id") == NS + "_prj", pj)
    sku = bill.post("/api/v1/master/skus",
                    {"sku_id": NS + "_sku1", "canonical_name": "乌龙茶",
                     "brand": "三得利", "test_run_id": NS})
    check("fixture_sku_scoped",
          sku.get("sku", {}).get("sku_id") == NS + "_sku1", sku)
    emp = bill.post("/api/v1/geo/employees",
                    {"customer_id": CUST, "name": "外勤小王",
                     "test_run_id": NS})
    check("fixture_employee_scoped",
          bool(emp.get("employee", {}).get("employee_id")), emp)
    addr = bill.post("/api/v1/geo/addresses",
                     {"customer_id": CUST, "raw": "上海市南京西路 1 号",
                      "test_run_id": NS})
    addr_id = addr.get("address", {}).get("address_id", "")
    check("fixture_address_scoped", bool(addr_id), addr)
    # 手工坐标（degraded geocoder 诚实路径）
    mc = bill.post(f"/api/v1/geo/addresses/{addr_id}/manual-coords",
                   {"lat": 31.23, "lng": 121.47, "source": "manual"})
    check("manual_coords_ok", bool(mc.get("address")), mc)

    # ---- 2) 外勤任务 + 路线 ----
    task = bill.post("/api/v1/geo/tasks",
                     {"customer_id": CUST, "address_id": addr_id,
                      "project_id": NS + "_prj", "kind": "visit",
                      "survey_id": "", "test_run_id": NS})
    task_id = task.get("task", {}).get("task_id", "")
    check("fixture_field_task_scoped", bool(task_id), task)
    plan = bill.post("/api/v1/geo/plans",
                     {"customer_id": CUST, "task_ids": [task_id],
                      "test_run_id": NS})
    check("fixture_route_plan_scoped",
          bool(plan.get("plan", {}).get("plan_id")
               or plan.get("plan", {}).get("plan")), str(plan)[:120])

    # ---- 3) 问卷（全题型 + 门头契约） ----
    svy = bill.post("/api/v1/survey/definitions", {
        "name": f"UAT V4 问卷 {NS}",
        "spec": {"questions": [
            {"id": "q_text", "type": "text", "title": "门店备注",
             "required": False},
            {"id": "q_single", "type": "single_choice",
             "title": "陈列位置",
             "options": ["货架", "冷柜", "收银台"]},
            {"id": "q_multi", "type": "multi_choice", "title": "促销活动",
             "options": ["买赠", "折扣", "无"]},
            {"id": "q_score", "type": "rating", "title": "整洁度",
             "min": 1, "max": 5},
            {"id": "q_photo", "type": "photo", "title": "门头照",
             "required": True, "min_count": 1, "max_count": 3,
             "require_storefront": True, "capture_role": "storefront"}]},
        "test_run_id": NS})
    survey_id = svy.get("definition", {}).get("survey_id", "")
    check("fixture_survey_scoped", bool(survey_id), svy)
    bill.post(f"/api/v1/survey/definitions/{survey_id}/lint", {})
    pub = bill.post(f"/api/v1/survey/definitions/{survey_id}/publish", {})
    check("survey_published", "_http" not in pub, pub)
    asg = bill.post("/api/v1/survey/assignments",
                    {"survey_id": survey_id, "customer_id": CUST,
                     "project_id": NS + "_prj", "assignee": OWNER})
    assignment_id = asg.get("assignment", {}).get("assignment_id", "")
    check("fixture_assignment_scoped", bool(assignment_id), asg)
    rsp = bill.post("/api/v1/survey/responses",
                    {"assignment_id": assignment_id})
    response_id = rsp.get("response", {}).get("response_id", "")
    check("fixture_response_scoped", bool(response_id), rsp)
    # 门头契约负例：未传门头照直接提交必须被拒（submit guard）
    neg = bill.post(f"/api/v1/survey/responses/{response_id}/submit", {})
    check("storefront_negative_rejected",
          neg.get("_http") in (400, 409, 422), neg)
    # 正例：带门头照提交
    photo = base64.b64encode(_png()).decode()
    media = bill.post(f"/api/v1/survey/responses/{response_id}/media",
                      {"question_id": "q_photo", "image_b64": photo,
                       "capture_role": "storefront"})
    check("storefront_media_attached", "_http" not in media, media)
    pos = bill.put(f"/api/v1/survey/responses/{response_id}/answers",
                   {"answers": {"q_single": {"value": "货架"},
                                "q_score": {"value": 4}}})
    sub = bill.post(f"/api/v1/survey/responses/{response_id}/submit", {})
    check("storefront_positive_submitted",
          "_http" not in sub
          and sub.get("response", {}).get("status") == "submitted",
          f"{str(pos)[:80]} {str(sub)[:120]}")

    # ---- 4) 工作流（wait/parallel/join/loop/approval/command/agent） ----
    spec = {"trigger": {"type": "manual"}, "variables": {},
            "nodes": [
                {"id": "start", "type": "trigger"},
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
                 "config": {"owner": OWNER, "title": "UAT V4 确认"}},
                {"id": "ag", "type": "agent",
                 "config": {"agent_id": "analytics_agent",
                            "prompt": "查询已注册的 BI 指标"}},
                {"id": "lp", "type": "loop",
                 "config": {"items_path": "$inputs.items",
                            "body": "lb"}},
                {"id": "lb", "type": "transform",
                 "config": {"map": {"it": "$vars.loop_item"}}},
                {"id": "end", "type": "end"}],
            "edges": [
                {"from": "start", "to": "w"}, {"from": "w", "to": "par"},
                {"from": "par", "to": "b1"}, {"from": "par", "to": "b2"},
                {"from": "b1", "to": "j"}, {"from": "b2", "to": "j"},
                {"from": "j", "to": "rec"}, {"from": "rec", "to": "appr"},
                {"from": "appr", "to": "ag"}, {"from": "ag", "to": "lp"},
                {"from": "lp", "to": "end"}],
            "policy": {"approval_required_for_publish": True}}
    wf = bill.post("/api/v1/workflows",
                   {"name": f"UAT V4 主工作流 {NS}", "spec": spec,
                    "test_run_id": NS})
    did = wf.get("definition", {}).get("definition_id", "")
    check("fixture_workflow_scoped", bool(did), wf)
    bill.post(f"/api/v1/workflows/{did}/lint", {})
    bill.post(f"/api/v1/workflows/{did}/simulate", {"inputs": {}})
    bill.post(f"/api/v1/workflows/{did}/approve", {})
    bill.post(f"/api/v1/workflows/{did}/publish", {})
    img_b64 = base64.b64encode(_png()).decode()
    run = bill.post(f"/api/v1/workflows/{did}/runs",
                    {"inputs": {"images": [["shelf.png", img_b64]],
                                "items": [1, 2]},
                     "customer_id": CUST, "project_id": NS + "_prj",
                     "test_run_id": NS})
    rid = run.get("run", {}).get("run_id", "")
    check("workflow_run_started", bool(rid), str(run)[:160])
    # 等待进入 human_approval
    rd: dict = {}
    for _ in range(60):
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
    # 等待终态
    for _ in range(60):
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

    # ---- 5) Agent（含失败账本）与识别命令 ----
    ag = bill.post("/api/v1/agents/supervisor/invoke",
                   {"text": "UAT V4 汇总当前工作进展",
                    "customer_id": CUST, "test_run_id": NS})
    check("agent_invoke_scoped",
          "_http" not in ag, str(ag)[:160])
    agf = bill.post("/api/v1/agents/no_such_agent_v4/invoke",
                    {"text": "故意失败", "customer_id": CUST,
                     "test_run_id": NS})
    check("agent_failure_ledger_recorded",
          agf.get("_http") in (409,), agf)

    # ---- 6) UAT 进行中：普通首页 0 fixture ----
    cal = bill.get("/api/v1/calendar/events").get("events", [])
    fx_events = [e for e in cal
                 if "uatv4" in json.dumps(e, ensure_ascii=False)]
    check("home_zero_fixture_during_uat", not fx_events,
          f"calendar={len(cal)} fixture={len(fx_events)}")
    wfs = bill.get("/api/v1/workflows").get("definitions", [])
    check("workflow_list_zero_fixture",
          not any(NS in (w.get("name") or "") + (w.get("definition_id")
                                                 or "")
                  for w in wfs), f"visible={len(wfs)}")

    # ---- 7) 归档（结构化）+ 全 Domain 泄漏=0 ----
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
    # 测试中心仍能查到本轮完整历史
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

    failed = [c for c in checks if not c["ok"]]
    report = {"namespace": NS, "customer_id": CUST,
              "checks": checks, "failed": len(failed),
              "duration_seconds": round(time.time() - t0, 1),
              "run_started_utc": datetime.now(timezone.utc).isoformat(),
              "ids": IDS}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"\n{'✅ UAT V4 全链通过' if not failed else '❌ 存在失败'}"
          f"（{len(checks) - len(failed)}/{len(checks)}），"
          f"报告：{REPORT}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
