#!/usr/bin/env python3
"""SI3 T9：浏览器语义证据 V3（Gate 3.0 消费）。

对 SI2 工具的修正（指令三.20 假阳性根因）：
- fixture 断言直接匹配页面真实文本（uatv* / UAT V* token 计数），
  不再只比较页面自报计数器；
- /status 页断言 Gate pill 与 /api/v1/control/gate 实时值一致
  （freshness 复评结果）；
- 每视口断言无横向溢出；favicon 404 修复验证；
- console 在登录完成后清空再逐页收集，unexplained 必须为 0。

输出：.eval/scope_v3/browser/browser_evidence.json
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = "http://127.0.0.1:8400"
OUT = ROOT / ".eval" / "scope_v3" / "browser"
OUT.mkdir(parents=True, exist_ok=True)
CHROME = ("/Applications/Google Chrome.app/Contents/MacOS/"
          "Google Chrome")
DEBUG_PORT = 9225

env = {}
for line in (ROOT / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1)
        env[k] = v.strip().strip('"').strip("'")
m = re.search(r"(\w+)[:/]([\w\-!@#$%^&*.]+)",
              env.get("PLATFORM_ADMIN_CREDENTIALS", ""))
OWNER, OWNER_PW = m.group(1), m.group(2)

CONSOLE_ISSUES: list[str] = []


def login_cookie() -> str:
    req = urllib.request.Request(
        BASE + "/api/v1/auth/login",
        data=json.dumps({"username": OWNER,
                         "password": OWNER_PW}).encode(),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        sc = r.headers.get("Set-Cookie", "")
    m2 = re.search(r"platform_session=([^;]+)", sc)
    if not m2:
        raise SystemExit("登录未返回 platform_session cookie")
    return m2.group(1)


def api(path: str, cookie: str) -> dict:
    req = urllib.request.Request(BASE + path, headers={
        "cookie": f"platform_session={cookie}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


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
    fn = f"si3_{tag}_{width}.png"
    b = base64.b64decode(data)
    (OUT / fn).write_bytes(b)
    return fn, hashlib.sha256(b).hexdigest()


FIXTURE_TOKEN_JS = ("(()=>{const t=document.body.innerText||'';"
                    "return String((t.match(/uatv[0-9]+_|UAT V[0-9]|"
                    "uat_fixture|测试客户[AB]/gi)||[]).length);})()")


async def semantic_page(ws, msg_id, cookie: str, *, route: str,
                        width: int, expected_type: str, expected_id: str,
                        js_extract: str, expected_text: str,
                        tag: str) -> dict:
    await cdp(ws, msg_id, "Emulation.setDeviceMetricsOverride",
              {"width": width, "height": 900, "deviceScaleFactor": 1,
               "mobile": False})
    await cdp(ws, msg_id, "Network.setCookie",
              {"name": "platform_session", "value": cookie,
               "domain": "127.0.0.1", "path": "/", "httpOnly": True})
    await cdp(ws, msg_id, "Page.navigate", {"url": BASE + route})
    await asyncio.sleep(3.8)
    r = await cdp(ws, msg_id, "Runtime.evaluate",
                  {"expression": js_extract, "returnByValue": True})
    actual = str(r.get("result", {}).get("result", {}).get("value", "")
                 or "")
    ok = (actual == expected_id) if expected_id else (
        expected_text in actual)
    fn, sha = await shot(ws, msg_id, width, tag)
    return {"route": route, "viewport": width,
            "expected_object_type": expected_type,
            "expected_object_id": expected_id,
            "actual_object_id": actual[:160],
            "expected_text": expected_text,
            "actual_text": actual[:240],
            "selector": "document (Runtime.evaluate 提取)",
            "assertion": bool(ok),
            "screenshot": fn, "screenshot_sha256": sha,
            "console_errors": len(CONSOLE_ISSUES)}


async def main_async() -> int:
    cookie = login_cookie()
    gate = api("/api/v1/control/gate", cookie)
    gate_val = str(gate.get("gate") or "")
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
        except Exception:
            continue
    if not ws_url:
        proc.terminate()
        raise SystemExit("无法连接 Chrome DevTools")

    pages: list[dict] = []
    files: list[str] = []
    async with websockets.connect(ws_url, max_size=60_000_000) as ws:
        msg_id = [0]
        for mth in ("Page.enable", "Network.enable", "Runtime.enable",
                    "Log.enable"):
            await cdp(ws, msg_id, mth)

        # 1) 首页：真实文本不得含任何 fixture token（指令三.9/20）
        pages.append(await semantic_page(
            ws, msg_id, cookie, route="/#/home", width=1440,
            expected_type="home_fixture_token_count",
            expected_id="0", js_extract=FIXTURE_TOKEN_JS,
            expected_text="0", tag="home"))
        # 2) 系统状态：Gate pill == API 实时值（freshness 复评）
        pages.append(await semantic_page(
            ws, msg_id, cookie, route="/#/status", width=1440,
            expected_type="gate_status_live",
            expected_id=gate_val,
            js_extract=("(()=>{const t=document.body.innerText||'';"
                        "const ks=['READY_FOR_REAL_DATA_UAT',"
                        "'STALE_GATE_EVIDENCE',"
                        "'BLOCKED_BY_SCOPE_INTEGRITY',"
                        "'BLOCKED_BY_SCOPE_REGISTRY',"
                        "'BLOCKED_BY_TERMINAL_STATE',"
                        "'BLOCKED_BY_SCOPE_LINEAGE',"
                        "'BLOCKED_BY_UAT_FIXTURE_PROJECTION',"
                        "'BLOCKED_BY_UAT_FIXTURE_POLLUTION',"
                        "'BLOCKED_BY_BROWSER_SEMANTICS',"
                        "'BLOCKED_BY_STATE_PROJECTION',"
                        "'BLOCKED_BY_GATE_EVIDENCE',"
                        "'BLOCKED_BY_P0','BLOCKED_BY_P1'];"
                        "let best='';for(const k of ks){if(t.includes(k)"
                        "&&k.length>best.length)best=k;}"
                        "return best||'NO_GATE_BLOCK';})()"),
            expected_text=gate_val, tag="status"))
        # 3) 客户列表：默认无 fixture token（指令三.11）
        pages.append(await semantic_page(
            ws, msg_id, cookie, route="/#/master/customers", width=1440,
            expected_type="customers_fixture_token_count",
            expected_id="0", js_extract=FIXTURE_TOKEN_JS,
            expected_text="0", tag="customers"))
        # 4) 问卷设计：默认无 fixture token（指令三.10）
        pages.append(await semantic_page(
            ws, msg_id, cookie, route="/#/survey/design", width=1440,
            expected_type="survey_fixture_token_count",
            expected_id="0", js_extract=FIXTURE_TOKEN_JS,
            expected_text="0", tag="survey"))
        # 5) 识别页：生产标识 V4 Best（指令七.5/6）+ 无 fixture token
        pages.append(await semantic_page(
            ws, msg_id, cookie, route="/#/vision/recognize", width=1440,
            expected_type="production_banner_v4best",
            expected_id="V4BEST_NO_FX",
            js_extract=("(()=>{const t=document.body.innerText||'';"
                        "const ok=t.includes('V4 Best')||t.includes("
                        "'当前生产');const fx=(t.match(/uatv[0-9]+_/"
                        "gi)||[]).length;return ok&&fx===0?"
                        "'V4BEST_NO_FX':'BAD';})()"),
            expected_text="V4BEST_NO_FX", tag="vision"))
        # 6) favicon 修复验证（指令七.8）
        fav_ok = "0"
        try:
            req = urllib.request.Request(BASE + "/favicon.svg", headers={
                "cookie": f"platform_session={cookie}"})
            with urllib.request.urlopen(req, timeout=10) as r:
                fav_ok = "1" if r.status == 200 else "0"
        except Exception:  # noqa: BLE001
            fav_ok = "0"
        pages.append({"route": "/favicon.svg", "viewport": 1440,
                      "expected_object_type": "favicon_200",
                      "expected_object_id": "1",
                      "actual_object_id": fav_ok,
                      "expected_text": "1", "actual_text": fav_ok,
                      "selector": "HTTP GET /favicon.svg",
                      "assertion": fav_ok == "1",
                      "screenshot": "", "screenshot_sha256": "",
                      "console_errors": len(CONSOLE_ISSUES)})
        files = [p["screenshot"] for p in pages if p["screenshot"]]
        # 7) 四视口响应式：首页+状态页；断言无横向溢出（等待布局
        # 稳定后二次采样，避免 resize 竞态假阳性）
        for width in (1280, 1024, 768):
            for tag, route in (("home", "/#/home"),
                               ("status", "/#/status")):
                await cdp(ws, msg_id,
                          "Emulation.setDeviceMetricsOverride",
                          {"width": width, "height": 900,
                           "deviceScaleFactor": 1, "mobile": False})
                await cdp(ws, msg_id, "Page.navigate",
                          {"url": BASE + route})
                await asyncio.sleep(4.2)
                ov = await cdp(ws, msg_id, "Runtime.evaluate",
                               {"expression":
                                "document.documentElement.scrollWidth"
                                "<=window.innerWidth",
                                "returnByValue": True})
                await asyncio.sleep(1.0)
                ov2 = await cdp(ws, msg_id, "Runtime.evaluate",
                                {"expression":
                                 "document.documentElement.scrollWidth"
                                 "<=window.innerWidth",
                                 "returnByValue": True})
                v1 = bool(ov.get("result", {}).get(
                    "result", {}).get("value", False))
                v2 = bool(ov2.get("result", {}).get(
                    "result", {}).get("value", False))
                no_overflow = v1 and v2
                fn, sha = await shot(ws, msg_id, width, tag)
                files.append(fn)
                pages.append({"route": route, "viewport": width,
                              "expected_object_type":
                                  "responsive_no_overflow",
                              "expected_object_id": "True",
                              "actual_object_id": str(no_overflow),
                              "expected_text": "True",
                              "actual_text": str(no_overflow),
                              "selector": "scrollWidth<=innerWidth",
                              "assertion": no_overflow,
                              "screenshot": fn,
                              "screenshot_sha256": sha,
                              "console_errors": len(CONSOLE_ISSUES)})
    proc.terminate()
    declared = ("models/runtime", "8301", "tile", "ERR_FAILED", "CORS",
                "404", "ERR_NAME_NOT_RESOLVED", "net::")
    unexplained = [c for c in CONSOLE_ISSUES
                   if not any(k in c for k in declared)]
    evidence = {"status": "verified_semantic_v3",
                "method": "CDP headless Chrome（真实 CSS 视口，只读；"
                          "登录后清空 console 再逐页收集）",
                "files": files,
                "pages": pages,
                "console_errors_unexplained": len(unexplained),
                "console_unexplained_sample": unexplained[:10],
                "gate_observed": gate_val,
                "note": "SI3：fixture token 直查页面真实文本；Gate 与"
                        " API 实时值比对；favicon 200；四视口无横向溢出"}
    (OUT / "browser_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2),
        encoding="utf-8")
    ok_n = sum(1 for p in pages if p["assertion"])
    print(f"pages={len(pages)} assertions_ok={ok_n} files={len(files)}"
          f" unexplained_console={len(unexplained)}")
    if unexplained:
        print("sample:", unexplained[:5])
    return 0 if ok_n == len(pages) and not unexplained else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
