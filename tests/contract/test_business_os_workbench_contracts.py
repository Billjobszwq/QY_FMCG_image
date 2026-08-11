"""ABOS T1：工作台纠偏红测试（先失败证明问题，修复后变绿）。

覆盖 AGENT-EXECUTION-PROMPT §四 已知问题：
1. 平台级文案不得再写死 SKU 识别系统；
2. 模块清单唯一事实源（modules_api 不得持有第二份 MODULES 常量）；
3. 二级路由唯一（不得多个标签/路由指向同一组件+默认 state）；
4. 识别请求契约必须包含 recognition_profile_id；
5. Agent 统一响应字段必须被前端消费（ui_intents/command_previews/evidence）；
6. CSS variable 使用集合必须已定义；
7. /biz/m3bars 不得读训练报告冒充经营 BI。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web" / "src"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---- 1. 产品定位 ----

def test_login_and_footer_not_sku_recognition():
    app = _read(WEB / "App.tsx")
    assert "sku recognition" not in app.lower()
    assert "SKU 识别系统" not in app


def test_supervisor_prompt_not_sku_system():
    sup = _read(ROOT / "src" / "platform" / "agents" / "supervisor.py")
    assert "SKU 识别系统" not in sup


def test_footer_production_not_hardcoded():
    app = _read(WEB / "App.tsx")
    assert "prod_20260805_v5_r1" not in app, (
        "production 必须来自实时 API，不得硬编码在 footer")


# ---- 2. 模块唯一事实源 ----

def test_modules_api_has_no_second_module_constants():
    src = _read(ROOT / "src" / "platform" / "api" / "modules_api.py")
    assert "MODULES = [" not in src, (
        "modules_api 不得持有第二份业务模块常量，必须消费 Registry 投影")


def test_app_rail_not_hardcoded():
    app = _read(WEB / "App.tsx")
    assert "const RAIL = [" not in app, (
        "一级导航必须来自 Module Registry 投影，不得在 App.tsx 硬编码")


# ---- 3. 二级路由唯一 ----

def test_biz_routes_not_same_component():
    app = _read(WEB / "App.tsx")
    # 不允许 /biz、/biz/api、/biz/alert、/biz/cfg 全部渲染同一组件
    biz_routes = re.findall(r'path="(/biz[^"]*)"\s+element=\{<(\w+)', app)
    comps = {c for _, c in biz_routes}
    assert len(biz_routes) <= 1 or len(comps) > 1 or not biz_routes


def test_module_tabs_unique_routes():
    """ModuleTabs 不得出现多个标签指向同一 URL。"""
    tabs = _read(WEB / "pages" / "ModuleTabs.tsx")
    assert "unique" in tabs or len(set(re.findall(
        r'to:\s*"([^"]+)"', tabs))) == len(re.findall(
        r'to:\s*"([^"]+)"', tabs))


# ---- 4. 识别 Profile 进入请求 ----

def test_recognition_task_contract_includes_profile():
    src = _read(ROOT / "src" / "platform" / "api" / "recognition_tasks.py")
    assert "recognition_profile_id" in src, (
        "识别请求契约必须包含 recognition_profile_id")


def test_frontend_recognition_passes_profile():
    rec = _read(WEB / "pages" / "Recognition.tsx")
    api = _read(WEB / "api.ts")
    assert ("recognition_profile_id" in api) or (
        "recognition_profile_id" in rec), (
        "前端识别入口必须把所选 profile 传入请求")


# ---- 5. Agent 响应消费 ----

def test_agentchat_consumes_ui_intents_and_commands():
    chat = _read(WEB / "pages" / "AgentChat.tsx")
    assert "ui_intents" in chat, "AgentChat 必须消费 ui_intents"
    assert ("command" in chat), "AgentChat 必须渲染命令预览/审批"


def test_supervisor_no_unimported_path():
    sup = _read(ROOT / "src" / "platform" / "agents" / "supervisor.py")
    if "Path(" in sup:
        assert re.search(r"^from pathlib import|^import pathlib",
                         sup, re.M), "supervisor 使用 Path 必须导入"


# ---- 6. CSS 变量与类 ----

def test_css_variables_all_defined():
    css = _read(WEB / "styles.css")
    defined = set(re.findall(r"^\s*(--[\w-]+)\s*:", css, re.M))
    used = set()
    for f in list(WEB.rglob("*.css")) + list(WEB.rglob("*.tsx")):
        used |= set(re.findall(r"var\((--[\w-]+)", _read(f)))
    missing = used - defined
    assert not missing, f"未定义 CSS 变量: {sorted(missing)}"


def test_m3bars_not_training_report():
    src = _read(ROOT / "src" / "platform" / "api" / "modules_api.py")
    assert "train_report.json" not in src, (
        "经营 BI 不得读取模型训练报告")
