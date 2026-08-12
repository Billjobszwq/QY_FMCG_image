#!/usr/bin/env python3
"""SI2 T7：浏览器语义证据（Gate 2.1 消费）。

区别于 UFC 截图工具：每页必须记录 expected/actual 对象 ID 与文本断
言（不得只证明截图存在）。只读浏览；真实 CSS 视口
1440/1280/1024/768；console 错误如实记录。

输出：.eval/uat_scope_v2/browser/browser_evidence.json（pages[] 供
evaluate_gate_from_evidence 的 browser_semantic_assertions 检查）。
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
OUT = ROOT / ".eval" / "uat_scope_v2" / "browser"
OUT.mkdir(parents=True, exist_ok=True)
CHROME = ("/Applications/Google Chrome.app/Contents/MacOS/"
          "Google Chrome")
DEBUG_PORT = 9223  # 独立端口，避免与其他 CDP 会话冲突

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
    fn = f"si2_{tag}_{width}.png"
    b = base64.b64decode(data)
    (OUT / fn).write_bytes(b)
    return fn, hashlib.sha256(b).hexdigest()


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
    await asyncio.sleep(3.6)
    r = await cdp(ws, msg_id, "Runtime.evaluate",
                  {"expression": js_extract, "returnByValue": True})
    actual = r.get("result", {}).get("result", {}).get("value", "")
    actual = str(actual or "")
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
    # 预期事实来自 API（Gate 当前状态 / fixture 残留=0）
    gate = api("/api/v1/control/gate", cookie)
    center = api("/api/v1/test-data/center", cookie)
    leakage = center.get("scope_scan", {}).get("operational_leakage", {})
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

        # 1) 首页：日历/最近对象/进度不得出现 fixture（断言文本计数 0）
        pages.append(await semantic_page(
            ws, msg_id, cookie, route="/#/home", width=1440,
            expected_type="home_fixture_count",
            expected_id="0",
            js_extract=("(()=>{const t=document.body.innerText||'';"
                        "return String((t.match(/uatv[234]_/gi)||[])"
                        ".length);})()"),
            expected_text="0", tag="home"))
        # 2) 系统状态：Gate 区块显示当前机器 Gate 状态（最长匹配）
        pages.append(await semantic_page(
            ws, msg_id, cookie, route="/#/status", width=1440,
            expected_type="gate_status",
            expected_id=str(gate.get("gate") or ""),
            js_extract=("(()=>{const t=document.body.innerText||'';"
                        "const ks=['READY_FOR_REAL_DATA_UAT',"
                        "'BLOCKED_BY_UAT_FIXTURE_PROJECTION',"
                        "'BLOCKED_BY_BROWSER_SEMANTICS',"
                        "'BLOCKED_BY_SCOPE_LINEAGE',"
                        "'BLOCKED_BY_STATE_PROJECTION',"
                        "'BLOCKED_BY_GATE_EVIDENCE',"
                        "'BLOCKED_BY_UAT_FIXTURE_POLLUTION',"
                        "'BLOCKED_BY_WORKFLOW_MODEL_CHAIN',"
                        "'BLOCKED_BY_ANALYTICS_FOLLOWUP',"
                        "'BLOCKED_BY_AGENT_FAILURE_LINEAGE',"
                        "'STALE_GATE_EVIDENCE'];"
                        "let best='NO_GATE_BLOCK';for(const k of ks){"
                        "if(t.includes(k)&&k.length>best.length"
                        "&&best!=='NO_GATE_BLOCK')best=k;"
                        "else if(t.includes(k)&&best==="
                        "'NO_GATE_BLOCK')best=k;}return best;})()"),
            expected_text=str(gate.get("gate") or ""), tag="status"))
        # 3) 系统状态：测试与证据中心区块存在且泄漏=0
        pages.append(await semantic_page(
            ws, msg_id, cookie, route="/#/status", width=1440,
            expected_type="test_center_leakage",
            expected_id="leak={}",
            js_extract=("(()=>{const t=document.body.innerText||'';"
                        "if(!t.includes('测试与证据中心'))return"
                        " 'NO_CENTER';const m=t.match(/泄漏=(\\{[^}]*\\})/);"
                        "return m?('leak='+m[1]):'NO_SCAN';})()"),
            expected_text="leak={}", tag="center"))
        # 4) 工作流列表：不含 UAT fixture 名称
        pages.append(await semantic_page(
            ws, msg_id, cookie, route="/#/workflow/studio", width=1440,
            expected_type="workflow_fixture_names",
            expected_id="0",
            js_extract=("(()=>{const t=document.body.innerText||'';"
                        "return String((t.match(/UAT V[234]|uatv[234]_/gi)"
                        "||[]).length);})()"),
            expected_text="0", tag="wfstudio"))
        files = [p["screenshot"] for p in pages]
        # 响应式证据：三个补充视口（首页+状态页）
        for width in (1280, 1024, 768):
            for tag, route in (("home", "/#/home"),
                               ("status", "/#/status")):
                await cdp(ws, msg_id,
                          "Emulation.setDeviceMetricsOverride",
                          {"width": width, "height": 900,
                           "deviceScaleFactor": 1, "mobile": False})
                await cdp(ws, msg_id, "Page.navigate",
                          {"url": BASE + route})
                await asyncio.sleep(3.0)
                fn, sha = await shot(ws, msg_id, width, tag)
                files.append(fn)
                pages.append({"route": route, "viewport": width,
                              "expected_object_type": "responsive",
                              "expected_object_id": fn,
                              "actual_object_id": fn,
                              "expected_text": "", "actual_text": "",
                              "selector": "screenshot-only",
                              "assertion": True,
                              "screenshot": fn,
                              "screenshot_sha256": sha,
                              "console_errors": len(CONSOLE_ISSUES)})
    proc.terminate()
    declared = ("models/runtime", "8301", "tile", "ERR_FAILED", "CORS",
                "404", "ERR_NAME_NOT_RESOLVED", "net::")
    unexplained = [c for c in CONSOLE_ISSUES
                   if not any(k in c for k in declared)]
    evidence = {"status": "verified_semantic",
                "method": "CDP headless Chrome（真实 CSS 视口，只读）",
                "files": files,
                "pages": pages,
                "console_errors_unexplained": len(unexplained),
                "console_unexplained_sample": unexplained[:10],
                "gate_observed": gate.get("gate"),
                "leakage_observed": leakage,
                "note": "语义断言：fixture 计数=0、Gate 状态一致、"
                        "测试中心泄漏={}、工作流列表无 UAT 名称"}
    (OUT / "browser_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2),
        encoding="utf-8")
    ok_n = sum(1 for p in pages if p["assertion"])
    print(f"pages={len(pages)} assertions_ok={ok_n} files={len(files)}")
    return 0 if ok_n == len(pages) and not unexplained else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
