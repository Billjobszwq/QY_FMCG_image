import re
from pathlib import Path


HTML_PATH = Path(__file__).parents[2] / "docs/promotion/ai-native-business-os-three-audience.html"


def load_html() -> str:
    assert HTML_PATH.exists(), f"missing presentation: {HTML_PATH}"
    return HTML_PATH.read_text(encoding="utf-8")


def extract_css_block(source: str, header: str) -> str:
    header_start = source.find(header)
    assert header_start >= 0, f"missing CSS block: {header}"
    block_start = source.find("{", header_start)
    assert block_start >= 0, f"missing opening brace for CSS block: {header}"

    depth = 0
    for index in range(block_start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[block_start + 1 : index]
    raise AssertionError(f"missing closing brace for CSS block: {header}")


def test_standalone_shell_and_accessibility_contracts() -> None:
    html = load_html()
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert "const CONTENT" in html
    assert all(key in html for key in ("investor", "partner", "customer"))
    assert html.count("data-audience=") >= 3
    assert 'role="tablist"' in html
    assert 'aria-live="polite"' in html
    assert "prefers-reduced-motion" in html
    assert 'aria-current="step"' in html


def test_all_audience_loops_contain_required_stages() -> None:
    html = load_html()
    required = {
        "investor": ["市场需求", "反馈资产", "能力升级", "更多客户与场景"],
        "partner": ["客户目标", "联合执行", "价值确认", "更多合作机会"],
        "customer": ["业务问题", "智能执行", "可验证结果", "下一轮目标"],
    }
    for audience, stages in required.items():
        assert audience in html
        for stage in stages:
            assert stage in html, f"{audience} loop is missing {stage}"


def test_content_shape_and_diagram_families_are_complete() -> None:
    html = load_html()
    for function_name in (
        "renderAudience",
        "renderSection",
        "renderDiagram",
        "setChapter",
        "setMode",
    ):
        assert f"function {function_name}" in html
    for diagram in ("paradigm", "friction", "architecture", "execution", "flywheel", "value"):
        assert diagram in html
    assert html.count("diagram:") == 18
    assert html.count("transition:") == 18


def test_presentation_is_offline_and_does_not_disclose_internal_technology() -> None:
    html = load_html()
    forbidden = (
        "http://",
        "https://",
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "Qwen",
        "YOLO",
        "SAM",
        "DeepSeek",
        "PostgreSQL",
        "Redis",
        "MinIO",
        "Label Studio",
        "FastAPI",
        "React Flow",
        "localhost",
        "/api/",
        "阈值",
        "提示词",
        "路由策略",
        "数据库表",
    )
    for term in forbidden:
        assert term not in html, f"forbidden disclosure or network dependency: {term}"


def test_copy_is_centralized_and_has_editing_guidance() -> None:
    html = load_html()
    assert "普通文案只修改下方 CONTENT 对象" in html
    assert "loop 固定保留 7 个阶段" in html
    assert "hero:" in html
    assert "sections:" in html
    assert "cta:" in html


def test_taas_naming_and_chinese_first_brand_hierarchy() -> None:
    html = load_html()
    assert "TaaS｜词元即服务" in html
    assert "AI 原生业务操作系统" in html
    assert "Token as a Service" in html
    assert "Token as a Severs" not in html
    assert html.index("TaaS｜词元即服务") < html.index("Token as a Service")
    assert "brand:" in html
    assert "concept:" in html
    assert "positioning:" in html
    assert "english:" in html


def test_taas_definition_and_audience_token_roles_are_present() -> None:
    html = load_html()
    assert "词元不再只是智能模型处理内容的计量单位" in html
    assert "驱动业务理解、决策、协同与执行的智能生产要素" in html
    assert html.count("TaaS") >= 4
    for phrase in ("智能生产要素", "伙伴能力", "理解目标和上下文"):
        assert phrase in html


def test_real_qiyun_logo_is_embedded_for_offline_delivery() -> None:
    html = load_html()
    assert 'class="qiyun-logo"' in html
    assert 'src="data:image/png;base64,' in html
    assert 'alt="QIYUN 公司标识，DECISION DATA DRIVE"' in html
    assert "/Users/zhangweiqi/Documents/QY/相关设计文档" not in html
    assert ".brand-mark" not in html


def test_token_flow_and_shared_loop_are_complete() -> None:
    html = load_html()
    for semantic in ("token-flow", "human-gate", "verified-result", "feedback-return"):
        assert semantic in html
    for stage in (
        "业务目标",
        "可执行意图",
        "词元驱动理解与决策",
        "组织人员、数据与能力",
        "持续执行与人工守门",
        "可验证业务结果",
        "反馈、评估与能力进化",
    ):
        assert stage in html


def test_cream_light_theme_contract() -> None:
    root = extract_css_block(load_html(), ":root")
    assert re.search(r"\bcolor-scheme\s*:\s*light\s*;", root)
    assert re.search(r"--canvas\s*:\s*#F3EFE5\s*;", root)
    assert re.search(r"--surface-paper\s*:\s*#FBF8F1\s*;", root)
    assert re.search(r"--ink\s*:\s*#171D24\s*;", root)
    assert not re.search(r"\bcolor-scheme\s*:\s*dark\b", root)


def test_editorial_hero_and_light_diagram_contract() -> None:
    html = load_html()
    hero_parts = (
        'class="hero-copy"',
        'class="hero-statement"',
        'class="hero-loop-summary"',
    )
    positions = [html.find(part) for part in hero_parts]
    assert all(position >= 0 for position in positions)
    assert positions == sorted(positions)

    hero_rule = extract_css_block(html, ".hero")
    assert re.search(
        r"grid-template-columns\s*:\s*minmax\(0,\s*2fr\)\s+minmax\(260px,\s*\.85fr\)\s*;",
        hero_rule,
    )
    diagram_rule = extract_css_block(html, ".diagram")
    assert re.search(r"background\s*:\s*var\(--surface-paper\)\s*;", diagram_rule)


def test_cream_page_keeps_offline_logo_and_mobile_flow() -> None:
    html = load_html()
    assert 'class="hero-flow-mobile"' in html
    mobile_rules = extract_css_block(html, "@media (max-width: 520px)")
    assert re.search(r"\.hero-flow-svg\s*\{[^{}]*\bdisplay\s*:\s*none\s*;", mobile_rules)
    assert re.search(r"\.hero-flow-mobile\s*\{[^{}]*\bdisplay\s*:\s*block\s*;", mobile_rules)
    assert not re.search(r"\.hero-map\s*\{[^{}]*\btransform\s*:\s*scale\s*\(", html)
