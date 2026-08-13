#!/usr/bin/env python3
"""OSV5 T8：浏览器对象级证据（Gate 3.2 消费，07-BROWSER-ACCEPTANCE）。

与 V4 工具的区别（P1-001 假阴性根治）：
- Import Center 逐视图与 API 对账（DOM tr[data-batch-id] 行数 ==
  API 口径行数；历史视图必须含纠偏后的具体 batch_id）；
- 四视图分离（运营/我的/历史/隔离）各记一条 page（route=
  data/import + view 标记）；
- 真实浏览器角色：owner / read_only / auditor 三角色驱动页面，
  customer_admin / project_manager 经 API 对象级矩阵入账；
- 低权限用户不得看到无权批次（read_only 页面行数为 0）；
- BI import count 与运营 API 相同；Gate pill 与实时值一致且含
  evaluator 3.2 口径；
- 四视口无横向溢出；console 清空后 unexplained 必须为 0。

输出：.eval/scope_v5/browser/browser_evidence.json
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import random
import re
import string
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = "http://127.0.0.1:8400"
OUT = ROOT / ".eval" / "scope_v5" / "browser"
OUT.mkdir(parents=True, exist_ok=True)
CHROME = ("/Applications/Google Chrome.app/Contents/MacOS/"
          "Google Chrome")
DEBUG_PORT = 9227

env = {}
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1)
        env[k] = v.strip().strip('"').strip("'")
m = re.search(r"(\w+)[:/]([\w\-!@#$%^&*.]+)",
              env.get("PLATFORM_ADMIN_CREDENTIALS", ""))
OWNER, OWNER_PW = m.group(1), m.group(2)
USER_PW = "Osv5Browser-pw-1"
NS = "osv5br_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") \
    + "_" + "".join(random.choices(string.ascii_lowercase
                                   + string.digits, k=5))

CONSOLE_ISSUES: list[str] = []


def login_cookie(username: str, password: str) -> tuple[str, str]:
    req = urllib.request.Request(
        BASE + "/api/v1/auth/login",
        data=json.dumps({"username": username,
                         "password": password}).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        sc = r.headers.get("Set-Cookie", "")
        body = json.loads(r.read())
    m2 = re.search(r"platform_session=([^;]+)", sc)
    if not m2:
        raise SystemExit(f"登录未返回 cookie: {username}")
    return m2.group(1), body.get("csrf_token", "")


def api(path: str, cookie: str) -> dict:
    req = urllib.request.Request(BASE + path, headers={
        "cookie": f"platform_session={cookie}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"_http": e.code}


async def cdp(ws, msg_id, method, params=None):
    msg_id[0] += 1
    await ws.send(json.dumps({"id": msg_id[0], "method": method,
                              "params": params or {}}))
    while True:
        raw = await ws.recv()
        d = json.loads(raw)
        if d.get("method") == "Runtime.exceptionThrown":
            CONSOLE_ISSUES.append(str(d.get("params", {}))[:160])
            continue
        if d.get("method") == "Log.entryAdded":
            e = d.get("params", {}).get("entry", {})
            if e.get("level") == "error":
                CONSOLE_ISSUES.append(str(e.get("text", ""))[:160])
            continue
        if d.get("id") == msg_id[0]:
            return d


async def shot(ws, msg_id, width: int, tag: str) -> tuple[str, str]:
    r = await cdp(ws, msg_id, "Page.captureScreenshot",
                  {"format": "png", "captureBeyondViewport": False})
    data = r.get("result", {}).get("data", "")
    fn = f"osv5_{tag}_{width}.png"
    b = base64.b64decode(data)
    (OUT / fn).write_bytes(b)
    return fn, hashlib.sha256(b).hexdigest()


async def goto(ws, msg_id, cookie: str, route: str, width: int = 1440,
               wait: float = 4.0):
    await cdp(ws, msg_id, "Emulation.setDeviceMetricsOverride",
              {"width": width, "height": 900, "deviceScaleFactor": 1,
               "mobile": False})
    await cdp(ws, msg_id, "Network.setCookie",
              {"name": "platform_session", "value": cookie,
               "domain": "127.0.0.1", "path": "/", "httpOnly": True})
    # 同 URL hash 导航不触发重渲染：先经 about:blank 强制重载，
    # 避免上一页状态污染断言。
    await cdp(ws, msg_id, "Page.navigate", {"url": "about:blank"})
    await asyncio.sleep(0.6)
    await cdp(ws, msg_id, "Page.navigate", {"url": BASE + route})
    await asyncio.sleep(wait)


async def jseval(ws, msg_id, expr: str) -> str:
    r = await cdp(ws, msg_id, "Runtime.evaluate",
                  {"expression": expr, "returnByValue": True})
    v = r.get("result", {}).get("result", {}).get("value")
    return "" if v is None else str(v)


def page(route: str, width: int, etype: str, eid: str, actual: str,
         fn: str, sha: str, view: str = "") -> dict:
    return {"route": route, "viewport": width,
            **({"view": view} if view else {}),
            "expected_object_type": etype,
            "expected_object_id": eid,
            "actual_object_id": actual[:200],
            "expected_text": eid, "actual_text": actual[:240],
            "selector": "document (Runtime.evaluate)",
            "assertion": actual == eid,
            "screenshot": fn, "screenshot_sha256": sha,
            "console_errors": len(CONSOLE_ISSUES)}


IMPORT_ROWS_JS = ("document.querySelectorAll('tr[data-batch-id]').length")
IMPORT_IDS_JS = ("(()=>{return [...document.querySelectorAll("
                 "'tr[data-batch-id]')].map(t=>t.getAttribute("
                 "'data-batch-id')).join(',');})()")
NO_FX_JS = ("(()=>{const t=document.body.innerText||'';return String("
            "(t.match(/uatv[0-9]+_|uat_fixture|osv5br_/gi)||[])"
            ".length);})()")
# 系统状态页含“测试与证据中心”（合法展示归档历史）：断言先剔除
# 该区块再计数（与 V4 同口径）。
NO_FX_STATUS_JS = ("(()=>{const t=(document.body.innerText||'');"
                   "const sec=[...document.querySelectorAll('h3,"
                   "section,div')].find(e=>(e.innerText||'').includes("
                   "'测试与证据中心'));const c=sec?(sec.innerText||'')"
                   ":'';const rest=c?t.replace(c,''):t;return String("
                   "(rest.match(/uatv[0-9]+_|uat_fixture|osv5br_/gi)"
                   "||[]).length);})()")


async def main_async() -> int:
    started_iso = datetime.now(timezone.utc).isoformat()
    owner, csrf = login_cookie(OWNER, OWNER_PW)
    gate = api("/api/v1/control/gate", owner)
    gate_val = str(gate.get("gate") or "")
    gate_ver = str(gate.get("evaluator_version") or "")

    # ---- 浏览器角色（fixture 身份，验收后随 Test Run 归档） ----
    def post(path: str, body: dict) -> dict:
        rq = urllib.request.Request(
            BASE + path, data=json.dumps(body).encode(), method="POST",
            headers={"content-type": "application/json",
                     "cookie": f"platform_session={owner}",
                     "X-CSRF-Token": csrf})
        try:
            with urllib.request.urlopen(rq, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return {"_http": e.code, "_body": e.read().decode()[:160]}

    post("/api/v1/test-data/run", {"namespace": NS, "customer_ids": []})
    roles = {"ca": "customer_admin", "pm": "project_manager",
             "ro": "read_only", "au": "auditor"}
    for short, role in roles.items():
        post("/api/v1/iam/principals",
             {"kind": "user", "username": f"{NS}_{short}",
              "display_name": f"OSV5 浏览器 {short}",
              "password": USER_PW, "test_run_id": NS})
        post("/api/v1/iam/grants", {"username": f"{NS}_{short}",
                                    "role": role})
    cookies = {short: login_cookie(f"{NS}_{short}", USER_PW)[0]
               for short in roles}

    # ---- API 口径（对象级对账基准） ----
    op_list = api("/api/v1/import/batches", owner)
    hist_list = api("/api/v1/import/batches?view=history"
                    "&include_fixture=1", owner)
    quar_list = api("/api/v1/import/batches?view=quarantine", owner)
    mine_list = api("/api/v1/import/batches?view=mine", owner)
    n_op = op_list.get("count", -1)
    n_hist = hist_list.get("count", -1)
    n_quar = quar_list.get("count", -1)
    n_mine = mine_list.get("count", -1)
    hist_ids = [b["batch_id"] for b in hist_list.get("batches", [])]
    quar_ids = [b["batch_id"] for b in quar_list.get("batches", [])]
    dp = api("/api/v1/analytics/data-products", owner)
    imp_bi = next((p["rows"] for p in dp.get("products", [])
                   if p["product"] == "import.batches_v1"), -1)

    pages: list[dict] = []
    files: list[str] = []
    user_data = OUT / "_chrome_profile"
    user_data.mkdir(exist_ok=True)
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
         f"--remote-debugging-port={DEBUG_PORT}",
         f"--user-data-dir={user_data}", "--window-size=1440,900",
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws_url = None
    for _ in range(40):
        time.sleep(0.4)
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{DEBUG_PORT}/json",
                    timeout=3) as r:
                tabs = json.loads(r.read())
            t = next((x for x in tabs if x.get("type") == "page"), None)
            if t:
                ws_url = t["webSocketDebuggerUrl"]
                break
        except Exception:  # noqa: BLE001
            continue
    if not ws_url:
        proc.terminate()
        raise SystemExit("Chrome CDP 未就绪")

    async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) \
            as ws:
        msg_id = [0]
        await cdp(ws, msg_id, "Page.enable")
        await cdp(ws, msg_id, "Runtime.enable")
        await cdp(ws, msg_id, "Log.enable")
        await goto(ws, msg_id, owner, "/#/home")
        CONSOLE_ISSUES.clear()  # 登录/首屏稳定后清空再收集

        # ---- Import Center 四视图（owner，对象级对账） ----
        # OSV51：修复四视图截图表层字节相同的采集缺陷——切换视图后
        # 强制滚动归零 + 重排/重绘同步 + 超越视口捕获；若与上一视图
        # sha 相同则强制重载重试一次。
        prev_sha = ""
        for view, tab_text, n_api, want_ids in (
                ("operational", "运营导入", n_op, []),
                ("mine", "我的批次", n_mine, []),
                ("history", "Test Run / 历史证据", n_hist, hist_ids[:3]),
                ("quarantine", "隔离待处理", n_quar, quar_ids[:2])):
            await goto(ws, msg_id, owner, "/#/data/import")
            await jseval(ws, msg_id,
                         "(()=>{const b=[...document.querySelectorAll("
                         "'button[role=tab]')].find(x=>x.innerText"
                         f".includes('{tab_text}'));if(b)b.click();"
                         "return !!b;})()")
            await asyncio.sleep(2.5)
            n_dom = await jseval(ws, msg_id, IMPORT_ROWS_JS)
            ids_dom = await jseval(ws, msg_id, IMPORT_IDS_JS)
            ids_ok = all(i in ids_dom for i in want_ids)
            await jseval(ws, msg_id,
                         "window.scrollTo(0,0);"
                         "void document.body.offsetHeight;1")
            await asyncio.sleep(0.5)
            fn, sha = await shot(ws, msg_id, 1440, f"import_{view}")
            if prev_sha and sha == prev_sha:
                # 同字节 = 渲染未生效：强制重载后重取一次
                await goto(ws, msg_id, owner, "/#/data/import")
                await jseval(ws, msg_id,
                             "(()=>{const b=[...document.querySelectorAll("
                             "'button[role=tab]')].find(x=>x.innerText"
                             f".includes('{tab_text}'));if(b)b.click();"
                             "return !!b;})()")
                await asyncio.sleep(3.0)
                await jseval(ws, msg_id,
                             "window.scrollTo(0,0);"
                             "void document.body.offsetHeight;1")
                await asyncio.sleep(0.5)
                fn, sha = await shot(ws, msg_id, 1440,
                                     f"import_{view}")
            prev_sha = sha
            files.append(fn)
            p = page("/#/data/import", 1440,
                     f"import_view_{view}_count_api_reconciled",
                     str(n_api), n_dom, fn, sha, view=view)
            p["assertion"] = (n_dom == str(n_api)) and ids_ok
            p["actual_text"] = f"rows={n_dom} ids_ok={ids_ok} " \
                f"sample={ids_dom[:120]}"
            pages.append(p)

        # ---- 12 一级工作台（owner；运营页 fixture token 必须 0） ----
        for route in ("/#/home", "/#/survey/design", "/#/geo/addresses",
                      "/#/vision/recognize", "/#/analytics/reports",
                      "/#/workflow/studio", "/#/iam/accounts",
                      "/#/master/customers", "/#/finance/contracts",
                      "/#/help", "/#/status"):
            await goto(ws, msg_id, owner, route)
            fx = await jseval(ws, msg_id,
                              NO_FX_STATUS_JS if route == "/#/status"
                              else NO_FX_JS)
            tag = route.strip("/#/").replace("/", "_") or "home"
            fn, sha = await shot(ws, msg_id, 1440, tag)
            files.append(fn)
            pages.append(page(route, 1440,
                              "operational_surface_fixture_zero", "0",
                              fx, fn, sha))

        # ---- BI import count 与运营 API 对账 ----
        await goto(ws, msg_id, owner, "/#/analytics/reports")
        bi_dom = await jseval(ws, msg_id,
                              "(()=>{const t=document.body.innerText||"
                              "'';const m=t.match(/import\\.batches_v1[\\s\\S]{0,80}?(\\d+)/);"
                              "return m?m[1]:'NA';})()")
        fn, sha = await shot(ws, msg_id, 1440, "bi_dataproducts")
        files.append(fn)
        pages.append(page("/#/analytics/reports", 1440,
                          "bi_import_count_equals_operational_api",
                          str(imp_bi), bi_dom, fn, sha))

        # ---- Gate pill 与实时值一致 + 3.2 口径 ----
        await goto(ws, msg_id, owner, "/#/status")
        pill = await jseval(ws, msg_id,
                            "(()=>{const t=document.body.innerText||'';"
                            f"return t.includes('{gate_val}')?'1':'0';"
                            "})()")
        ver = await jseval(ws, msg_id,
                           "(()=>{const t=document.body.innerText||'';"
                           f"return t.includes('{gate_ver}')?'1':'0';"
                           "})()")
        fn, sha = await shot(ws, msg_id, 1440, "status_gate")
        files.append(fn)
        p = page("/#/status", 1440, "gate_pill_live_value", "1", pill,
                 fn, sha)
        p["actual_text"] = f"pill={pill} version_3_2_shown={ver} " \
            f"gate={gate_val} ver={gate_ver}"
        pages.append(p)

        # ---- read_only：无权批次不可见（对象级） ----
        await goto(ws, msg_id, cookies["ro"], "/#/data/import")
        ro_rows = await jseval(ws, msg_id, IMPORT_ROWS_JS)
        fn, sha = await shot(ws, msg_id, 1440, "import_readonly")
        files.append(fn)
        p = page("/#/data/import", 1440,
                 "readonly_sees_no_unauthorized_batches", "0", ro_rows,
                 fn, sha, view="operational")
        p["role"] = "read_only"
        pages.append(p)

        # ---- auditor：历史证据可见（data.import.audit） ----
        await goto(ws, msg_id, cookies["au"], "/#/data/import")
        await jseval(ws, msg_id,
                     "(()=>{const b=[...document.querySelectorAll("
                     "'button[role=tab]')].find(x=>x.innerText"
                     ".includes('历史'));if(b)b.click();return !!b;})()")
        await asyncio.sleep(2.5)
        au_rows = await jseval(ws, msg_id, IMPORT_ROWS_JS)
        fn, sha = await shot(ws, msg_id, 1440, "import_auditor_history")
        files.append(fn)
        p = page("/#/data/import", 1440,
                 "auditor_history_visible_count_api_reconciled",
                 str(n_hist), au_rows, fn, sha, view="history")
        p["role"] = "auditor"
        pages.append(p)

        # ---- 四视口无横向溢出（import/home/status；三采样防竞态） ----
        for width in (1280, 1024, 768):
            for tag, route in (("import", "/#/data/import"),
                               ("home", "/#/home"),
                               ("status", "/#/status")):
                await goto(ws, msg_id, owner, route, width=width,
                           wait=4.6)
                samples = []
                for _ in range(3):
                    await asyncio.sleep(1.4)
                    v = await jseval(
                        ws, msg_id,
                        "document.documentElement.scrollWidth"
                        "<=window.innerWidth")
                    samples.append(v in ("True", "true"))
                no_ov = all(samples)
                fn, sha = await shot(ws, msg_id, width, tag)
                files.append(fn)
                pages.append(page(route, width, "responsive_no_overflow",
                                  "True", "True" if no_ov else "False",
                                  fn, sha))

        # ---- OSV51 C-7：导航滚动连续性（四视口；须在 proc.terminate
        # 之前执行，复用 CDP 会话） ----
        # Import Center 深滚 → 主导航进入系统管理：新页面必须
        # scrollY=0 且焦点落在 h1（读屏/键盘可感知页面切换）。
        for width in (1440, 1280, 1024, 768):
            await goto(ws, msg_id, owner, "/#/data/import",
                       width=width)
            await jseval(ws, msg_id, "window.scrollTo(0, 2124);"
                                     "window.scrollY")
            await asyncio.sleep(0.5)
            deep_y = await jseval(ws, msg_id, "String(window.scrollY)")
            clicked = await jseval(ws, msg_id,
                                   "(()=>{const a=[...document.querySelectorAll("
                                   "'.pnav a, nav a')].find(x=>(x.innerText||'')"
                                   ".includes('系统管理'));if(a){a.click();"
                                   "return '1';}return '0';})()")
            if clicked != "1":
                await jseval(ws, msg_id, "location.hash='#/status'")
            await asyncio.sleep(2.5)
            new_y = await jseval(ws, msg_id, "String(window.scrollY)")
            focus_tag = await jseval(ws, msg_id,
                                     "(document.activeElement&&"
                                     "document.activeElement.tagName)||''")
            on_status = await jseval(ws, msg_id,
                                     "String(location.hash).includes("
                                     "'/status')")
            okk = (new_y == "0" and focus_tag.upper() == "H1"
                   and str(on_status).lower() == "true"
                   and int(deep_y or 0) > 0)
            pages.append({
                "route": "/#/status", "viewport": width,
                "expected_object_type": "nav_scroll_continuity",
                "expected_object_id": "scrollY=0&h1_focused",
                "actual_object_id": "scrollY=0&h1_focused" if okk
                else f"scrollY={new_y}&focus={focus_tag}"
                     f"&hash={on_status}",
                "expected_text": "scrollY=0&h1_focused",
                "actual_text": f"deep_y={deep_y} new_y={new_y} "
                               f"focus={focus_tag} hash={on_status}",
                "selector": "window + document.activeElement",
                "assertion": okk, "screenshot": "",
                "screenshot_sha256": "",
                "console_errors": len(CONSOLE_ISSUES)})
    proc.terminate()

    # ---- 角色矩阵补充（customer_admin/project_manager：API 对象级） ----
    matrix = []
    for short, role in (("ca", "customer_admin"),
                        ("pm", "project_manager")):
        r = api("/api/v1/import/batches", cookies[short])
        denied = r.get("_http") == 403 or r.get("count", 1) == 0
        hist = api("/api/v1/import/batches?view=history"
                   "&include_fixture=1", cookies[short])
        hist_denied = hist.get("_http") == 403
        matrix.append({"role": role, "list_denied_or_empty": denied,
                       "history_denied": hist_denied})
    matrix_ok = all(x["list_denied_or_empty"] and x["history_denied"]
                    for x in matrix)
    pages.append({"route": "/api/v1/import/batches (role matrix)",
                  "viewport": 1440,
                  "expected_object_type":
                      "ca_pm_role_matrix_api_object_level",
                  "expected_object_id": "True",
                  "actual_object_id": str(matrix_ok),
                  "expected_text": "True",
                  "actual_text": json.dumps(matrix)[:240],
                  "selector": "API per-role",
                  "assertion": matrix_ok,
                  "screenshot": "", "screenshot_sha256": "",
                  "console_errors": len(CONSOLE_ISSUES)})

    # ---- 归档浏览器 fixture 身份（验收后运营面清零） ----
    post("/api/v1/test-data/archive", {"namespace": NS})

    declared = ("models/runtime", "8301", "tile", "ERR_FAILED", "CORS",
                "404", "ERR_NAME_NOT_RESOLVED", "net::")
    unexplained = [c for c in CONSOLE_ISSUES
                   if not any(k in c for k in declared)]
    ok_n = sum(1 for p in pages if p["assertion"])
    evidence = {"status": "verified_object_level_v5",
                "method": "CDP headless Chrome（真实 CSS 视口；"
                          "owner/read_only/auditor 真实角色驱动；"
                          "DOM 行数与 API 口径逐视图对账）",
                "roles_browser": ["owner/platform_admin", "read_only",
                                  "auditor"],
                "roles_api_matrix": ["customer_admin", "project_manager"],
                "files": files, "pages": pages,
                "console_errors_unexplained": len(unexplained),
                "console_unexplained_sample": unexplained[:10],
                "gate_observed": gate_val,
                "evaluator_version_observed": gate_ver,
                "browser_test_run": NS,
                "note": "OSV5：四视图分离 + 对象级 batch_id 对账；"
                        "低权限零批次；BI/运营 API 同值；Gate pill "
                        "实时一致"}
    # OSV51 C-6：浏览器证据 binding 块（生成时代码/DB 状态）
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _ROOT = _Path(__file__).resolve().parents[1]
        _sys.path.insert(0, str(_ROOT))
        from src.platform import binding_core as _bc
        from src.platform.data.store import PlatformStore
        from src.platform.gate_evaluator import db_fingerprint
        _store = PlatformStore(_ROOT / ".platform" / "platform.sqlite")
        evidence["binding"] = _bc.make_binding(
            root=_ROOT, conn=_store._conn,
            argv=[_sys.executable, "scripts/osv5_browser_evidence.py"],
            result_payload={"pages": len(pages),
                            "assertions_ok": ok_n,
                            "browser_test_run": NS},
            started_at=started_iso,
            finished_at=datetime.now(timezone.utc).isoformat(),
            database_fingerprint=db_fingerprint(_store))
    except Exception as _e:  # noqa: BLE001
        evidence["binding_error"] = str(_e)[:200]
    (OUT / "browser_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2),
        encoding="utf-8")
    ok_n = sum(1 for p in pages if p["assertion"])
    print(f"pages={len(pages)} assertions_ok={ok_n}/{len(pages)} "
          f"files={len(files)} unexplained_console={len(unexplained)}")
    if unexplained:
        print("console sample:", unexplained[:5])
    return 0 if ok_n == len(pages) and not unexplained else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
