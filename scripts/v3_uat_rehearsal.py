#!/usr/bin/env python3
"""ABOSV3 T12：05-REAL-DATA-END-TO-END-UAT.md 机器预演。

以明确标记 uat_fixture_v3 的数据走完整 API 链（不直接写 SQLite）：
导入 → 地址/坐标 → 路线 → 问卷从空白 → 发布填写 → 工作流运行 →
识别（v4_best_standard）→ BI/Usage → 首页闭环 → 对账。

输出：.eval/v3_uat_rehearsal_report.json（不可手填：全部来自 API/DB）。
用法：python scripts/v3_uat_rehearsal.py
"""
from __future__ import annotations

import base64
import http.cookiejar
import json
import re
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
REPORT = ROOT / ".eval" / "v3_uat_rehearsal_report.json"

env = {}
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1)
        env[k] = v.strip().strip('"').strip("'")
m = re.search(r"(\w+)[:/]([\w\-!@#$%^&*.]+)",
              env.get("PLATFORM_ADMIN_CREDENTIALS", ""))
USER, PW = m.group(1), m.group(2)

cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
CSRF = {"token": ""}
checks: list[dict] = []


def req(method: str, path: str, body=None, csrf: bool = False,
        timeout: int = 120, raw: bytes | None = None,
        ctype: str = "application/json"):
    data = raw if raw is not None else (
        json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        r.add_header("content-type", ctype)
    if csrf:
        r.add_header("X-CSRF-Token", CSRF["token"])
    try:
        return json.loads(op.open(r, timeout=timeout).read())
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_body": e.read().decode()[:400]}


def check(name: str, ok: bool, evidence: str = ""):
    checks.append({"check": name, "ok": bool(ok),
                   "evidence": str(evidence)[:300]})
    print(("  ✓ " if ok else "  ✗ ") + name +
          (f"  [{evidence}]" if evidence else ""))


def req_bytes(path: str, timeout: int = 60) -> bytes:
    r = urllib.request.Request(BASE + path)
    return op.open(r, timeout=timeout).read()


def multipart(fields: dict, fname: str, content: bytes) -> tuple:
    b = uuid.uuid4().hex
    buf = []
    for k, v in fields.items():
        buf.append(f"--{b}\r\nContent-Disposition: form-data; "
                   f"name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    buf.append(f"--{b}\r\nContent-Disposition: form-data; "
               f"name=\"files\"; filename=\"{fname}\"\r\n"
               f"Content-Type: image/jpeg\r\n\r\n".encode())
    buf.append(content)
    buf.append(f"\r\n--{b}--\r\n".encode())
    return b"".join(buf), f"multipart/form-data; boundary={b}"


def main() -> int:
    t0 = time.time()
    ids: dict = {"at": datetime.now(timezone.utc).isoformat()}
    r = req("POST", "/api/v1/auth/login",
            {"username": USER, "password": PW})
    CSRF["token"] = r["csrf_token"]
    print("== 1. 初始化：模板下载 + fixture 导入（含故意错误） ==")
    for tpl in ("customers_v1", "projects_v1", "skus_v1",
                "employees_v1", "stores_addresses_v1"):
        d = req_bytes(f"/api/v1/import/templates/{tpl}/download?fmt=csv")
        check(f"模板下载 {tpl}", len(d) > 50, f"{len(d)} bytes")

    def upload_csv(tpl: str, csv_text: str, fname: str) -> dict:
        b = uuid.uuid4().hex
        raw = (f"--{b}\r\nContent-Disposition: form-data; "
               f"name=\"template_id\"\r\n\r\n{tpl}\r\n"
               f"--{b}\r\nContent-Disposition: form-data; "
               f"name=\"file\"; filename=\"{fname}\"\r\n"
               f"Content-Type: text/csv\r\n\r\n"
               + csv_text + f"\r\n--{b}--\r\n").encode("utf-8")
        up = req("POST", "/api/v1/import/upload",
                 raw=raw, csrf=True,
                 ctype=f"multipart/form-data; boundary={b}")
        return up.get("batch", {})

    bad = ("customer_id,name,payment_terms,retention_policy,tags\n"
           "uat_fixture_v3_cust,UAT预演客户,月结30天,2年,uat_fixture_v3\n"
           "uat_fixture_v3_cust2,,月结,,uat_fixture_v3\n")
    b1 = upload_csv("customers_v1", bad, "uat_bad.csv")
    d1 = req("POST", f"/api/v1/import/batches/{b1['batch_id']}/dry-run",
             {}, csrf=True)
    check("故意错误被 dry-run 捕获",
          d1["batch"]["status"] == "validation_failed",
          str(d1["batch"]["errors"][:1]))
    good = ("customer_id,name,payment_terms,retention_policy,tags\n"
            "uat_fixture_v3_cust,UAT预演客户,月结30天,2年,uat_fixture_v3\n")
    b2 = upload_csv("customers_v1", good, "uat_good.csv")
    req("POST", f"/api/v1/import/batches/{b2['batch_id']}/dry-run", {},
        csrf=True)
    c2 = req("POST", f"/api/v1/import/batches/{b2['batch_id']}/commit",
             {}, csrf=True)
    check("客户导入提交（幂等）",
          c2["batch"]["status"] in ("committed", "partial_failed"),
          json.dumps(c2["batch"]["commit"].get("stats")))
    ids["import_batch"] = b2["batch_id"]
    prj = ("project_id,customer_id,name,start_date,end_date,owner,"
           "budget\nuat_fixture_v3_prj,uat_fixture_v3_cust,UAT预演项目,"
           "2026-08-01,2026-09-30,bill,50000\n")
    b3 = upload_csv("projects_v1", prj, "uat_prj.csv")
    req("POST", f"/api/v1/import/batches/{b3['batch_id']}/dry-run", {},
        csrf=True)
    req("POST", f"/api/v1/import/batches/{b3['batch_id']}/commit", {},
        csrf=True)
    addr = ("customer_id,store_name,raw_address,region,lat,lng,"
            "coord_system,time_window\nuat_fixture_v3_cust,UAT预演门店,"
            "预演路 1 号,华东,,,wgs84,09:00-18:00\n")
    b4 = upload_csv("stores_addresses_v1", addr, "uat_addr.csv")
    req("POST", f"/api/v1/import/batches/{b4['batch_id']}/dry-run", {},
        csrf=True)
    req("POST", f"/api/v1/import/batches/{b4['batch_id']}/commit", {},
        csrf=True)
    addrs = req("GET", "/api/v1/geo/addresses?customer_id="
                "uat_fixture_v3_cust")["addresses"]
    check("地址导入落库", any("UAT预演门店" in a["raw"] for a in addrs),
          f"{len(addrs)} 地址")
    aid = next(a["address_id"] for a in addrs
               if "UAT预演门店" in a["raw"])
    ids["address"] = aid

    print("== 2. 坐标（无 Provider 诚实降级 + 手工坐标）与路线 ==")
    g = req("POST", f"/api/v1/geo/addresses/{aid}/geocode", {},
            csrf=True)
    check("获取坐标诚实降级（无 Key）", g.get("status") == "degraded",
          g.get("reason", "")[:60])
    req("POST", f"/api/v1/geo/addresses/{aid}/manual-coords",
        {"lat": 31.25, "lng": 121.50, "source": "import"}, csrf=True)
    task = req("POST", "/api/v1/geo/tasks",
               {"customer_id": "uat_fixture_v3_cust",
                "address_id": aid, "project_id": "uat_fixture_v3_prj"},
               csrf=True)["task"]
    ids["field_task"] = task["task_id"]
    plan = req("POST", "/api/v1/geo/plans",
               {"customer_id": "uat_fixture_v3_cust",
                "task_ids": [task["task_id"]],
                "constraints": {"depot_lat": 31.0, "depot_lng": 121.0,
                                "travel_unit_price": 2.0}},
               csrf=True)["plan"]
    check("路线规划（启发式诚实标注）",
          plan["constraints"].get("solver") ==
          "nearest_neighbor_heuristic", plan["plan_id"])
    ids["route_plan"] = plan["plan_id"]
    adj = req("POST", f"/api/v1/geo/plans/{plan['plan_id']}/adjust",
              {"ordered_task_ids": [task["task_id"]]}, csrf=True)
    check("人工调整路线 → 新版本",
          adj.get("plan", {}).get("version", 0) >= 2,
          f"v{adj.get('plan', {}).get('version')}")
    md = req("GET", "/api/v1/geo/map-data?customer_id="
             "uat_fixture_v3_cust")
    check("地图数据（点位/路线/未分配）",
          len(md["points"]) >= 1 and len(md["plans"]) >= 1,
          f"points={len(md['points'])} plans={len(md['plans'])}")

    print("== 3. 从空白创建问卷 → 发布 → 填写 ==")
    svy = req("POST", "/api/v1/survey/definitions",
              {"name": "UAT预演问卷 uat_fixture_v3",
               "spec": {"questions": [], "logic_edges": [],
                        "scoring": {"version": 1, "rules": [],
                                    "formula": "sum"}}},
              csrf=True)["definition"]
    ids["survey"] = svy["survey_id"]
    spec = {"questions": [
        {"id": "q1", "type": "single_choice", "title": "门店类型",
         "required": True,
         "options": [{"value": "a", "label": "A"},
                     {"value": "b", "label": "B"}]},
        {"id": "q2", "type": "rating", "title": "服务评分",
         "min": 1, "max": 5},
        {"id": "q3", "type": "photo", "title": "门头照",
         "min_count": 0, "require_storefront": True,
         "recognition": True}],
        "logic_edges": [],
        "scoring": {"version": 1, "formula": "sum",
                    "rules": [{"question": "q2", "weight": 2}]}}
    req("PUT", f"/api/v1/survey/definitions/{svy['survey_id']}",
        {"spec": spec, "name": ""}, csrf=True)
    lint = req("POST", f"/api/v1/survey/definitions/{svy['survey_id']}"
               "/lint", {}, csrf=True)["definition"]
    check("问卷 lint 通过", lint["status"] == "linted",
          str([i["code"] for i in lint["lint_report"]][:3]))
    req("POST", f"/api/v1/survey/definitions/{svy['survey_id']}/publish",
        {}, csrf=True)
    asg = req("POST", "/api/v1/survey/assignments",
              {"survey_id": svy["survey_id"],
               "customer_id": "uat_fixture_v3_cust",
               "assignee": "uat-field"}, csrf=True)["assignment"]
    rsp = req("POST", "/api/v1/survey/responses",
              {"assignment_id": asg["assignment_id"]},
              csrf=True)["response"]
    req("PUT", f"/api/v1/survey/responses/{rsp['response_id']}/answers",
        {"answers": {"q1": {"value": "a"}, "q2": {"value": 4}}},
        csrf=True)
    done = req("POST",
               f"/api/v1/survey/responses/{rsp['response_id']}/submit",
               {}, csrf=True)
    check("问卷提交并计分", done.get("response", {}).get("status")
          == "submitted",
          f"score={done.get('response', {}).get('scores', {}).get('total')}")
    ids["response"] = rsp["response_id"]

    print("== 4. 工作流（画布 spec：wait+join+agent）==")
    wf_spec = {"trigger": {"type": "manual"}, "variables": {},
               "nodes": [
                   {"id": "start", "type": "trigger",
                    "ui": {"x": 40, "y": 100}},
                   {"id": "par", "type": "parallel",
                    "ui": {"x": 160, "y": 100}},
                   {"id": "b1", "type": "transform",
                    "config": {"map": {"x": 1}},
                    "ui": {"x": 300, "y": 40}},
                   {"id": "b2", "type": "wait",
                    "config": {"seconds": 1},
                    "ui": {"x": 300, "y": 160}},
                   {"id": "j", "type": "join",
                    "config": {"mode": "all"},
                    "ui": {"x": 460, "y": 100}},
                   {"id": "end", "type": "end",
                    "ui": {"x": 600, "y": 100}}],
               "edges": [{"from": "start", "to": "par"},
                         {"from": "par", "to": "b1"},
                         {"from": "par", "to": "b2"},
                         {"from": "b1", "to": "j"},
                         {"from": "b2", "to": "j"},
                         {"from": "j", "to": "end"}],
               "policy": {"approval_required_for_publish": True}}
    wf = req("POST", "/api/v1/workflows",
             {"name": "UAT预演流程 uat_fixture_v3", "spec": wf_spec},
             csrf=True)["definition"]
    ids["workflow"] = wf["definition_id"]
    req("POST", f"/api/v1/workflows/{wf['definition_id']}/lint", {},
        csrf=True)
    req("POST", f"/api/v1/workflows/{wf['definition_id']}/simulate",
        {"inputs": {}}, csrf=True)
    req("POST", f"/api/v1/workflows/{wf['definition_id']}/approve", {},
        csrf=True)
    req("POST", f"/api/v1/workflows/{wf['definition_id']}/publish", {},
        csrf=True)
    run = req("POST", f"/api/v1/workflows/{wf['definition_id']}/runs",
              {"inputs": {}}, csrf=True)
    time.sleep(12)  # 等待 wait timer（1s）经轮询恢复
    rd = req("GET", f"/api/v1/workflows/runs/{run['run']['run_id']}")
    check("工作流 wait+join 真实运行",
          rd["run"]["status"] == "succeeded",
          f"run={run['run']['run_id']} status={rd['run']['status']}")
    ids["workflow_run"] = run["run"]["run_id"]

    print("== 5. 识别（v4_best_standard，统一命令链含 Usage）==")
    img = (ROOT / "bad_samples" / "36143897_reflection.jpg").read_bytes()
    cmd = req("POST", "/api/v1/commands", {
        "command_kind": "vision.recognition.create",
        "params": {"images": [["uat_fixture_v3.jpg",
                                base64.b64encode(img).decode()]],
                   "recognition_profile_id": "v4_best_standard",
                   "service_tier": "standard", "entry": "single_file"},
        "source": "web", "customer_id": "uat_fixture_v3_cust",
        "project_id": "uat_fixture_v3_prj"}, csrf=True, timeout=240)
    check("识别任务完成（V4 best）",
          cmd.get("status") == "succeeded",
          f"run={cmd.get('run', {}).get('run_id')} "
          f"task={(cmd.get('result') or {}).get('task_id')}")
    ids["recognition_task"] = (cmd.get("result") or {}).get("task_id")
    ids["recognition_run"] = cmd.get("run", {}).get("run_id")

    print("== 6. BI 与 Usage ==")
    ev2 = req("GET", "/api/v1/analytics/metrics/recognition.photos/"
              "evaluate?customer_id=uat_fixture_v3_cust")
    check("BI 指标求值", "value" in ev2, json.dumps(ev2))
    usage = req("GET", "/api/v1/usage/summary?customer_id="
                "uat_fixture_v3_cust")
    check("Usage 汇总", len(usage["by_unit"]) >= 1,
          json.dumps([(u["unit"], u["total"])
                      for u in usage["by_unit"]]))
    csvd = req_bytes("/api/v1/usage/export.csv?customer_id="
                     "uat_fixture_v3_cust")
    check("Usage CSV 导出", len(csvd) > 20, f"{len(csvd)} bytes")

    print("== 7. 首页闭环 + 主管 + 对账 ==")
    dash = req("GET", "/api/v1/home/dashboard")
    check("首页 dashboard 全段", all(
        k in dash for k in ("todos", "calendar", "progress", "activity",
                            "capacity", "agent_alerts", "recent",
                            "notes")), f"todos={dash['todos']}")
    sid = req("POST", "/api/agent/v1/sessions", {}, csrf=True)[
        "session_id"]
    chat = req("POST", "/api/agent/v1/chat",
               {"session_id": sid, "text": "项目进度做到哪里了？"},
               csrf=True)
    check("主管走真实工具循环",
          any(t.get("tool") == "work.progress.query"
              for t in chat.get("tool_trace", [])),
          str([t.get("tool") for t in chat.get("tool_trace", [])]))
    rec2 = req("GET", "/api/v1/control/reconcile")
    check("reconcile 一致（含业务事实对账）",
          rec2.get("consistent") is True
          and rec2.get("business_facts_checked") is True,
          f"drift_fixed={rec2.get('drift_fixed')}")
    import sqlite3
    conn = sqlite3.connect(ROOT / ".platform" / "platform.sqlite")
    ic = conn.execute("PRAGMA integrity_check").fetchone()[0]
    check("SQLite integrity", ic == "ok", ic)

    ids["elapsed_s"] = round(time.time() - t0, 1)
    report = {"ids": ids, "checks": checks,
              "passed": sum(1 for c in checks if c["ok"]),
              "failed": sum(1 for c in checks if not c["ok"])}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"\n预演完成：{report['passed']} 通过 / "
          f"{report['failed']} 失败（{ids['elapsed_s']}s）")
    print(f"报告：{REPORT}")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
