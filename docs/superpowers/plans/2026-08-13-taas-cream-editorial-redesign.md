# TaaS Cream Editorial Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 TaaS 三受众单文件推广页重构为米白底战略编辑式页面，同时保持闭环叙事、离线运行和全部交互能力。

**Architecture:** 保留现有单 HTML、内容数据对象和渲染函数，以 CSS 设计令牌和少量语义化标记完成视觉重构。先用静态契约测试锁定浅色主题与版式要求，再逐层修改首屏、闭环、章节图表和响应式规则，最后执行浏览器与全仓回归。

**Tech Stack:** HTML5、CSS3、原生 JavaScript、内嵌 SVG、pytest、Playwright

---

## 文件结构

- Modify: `docs/promotion/ai-native-business-os-three-audience.html` — 页面结构、浅色设计令牌、图表和响应式实现。
- Modify: `tests/promotion/test_three_audience_html.py` — 米白主题、编辑式结构、浅色图表和离线资产契约。
- Modify: `docs/promotion/ai-native-business-os-architecture-narrative.md` — 增加米白版视觉修改说明。
- Reference: `docs/superpowers/specs/2026-08-13-taas-cream-editorial-redesign.md` — 已确认设计规格。

### Task 1: 锁定米白主题与编辑式布局契约

**Files:**
- Modify: `tests/promotion/test_three_audience_html.py`
- Test: `tests/promotion/test_three_audience_html.py`

- [x] **Step 1: 添加浅色主题测试**

新增测试，要求 HTML 包含 `color-scheme: light`、米白画布 `#F3EFE5`、纸白 `#FBF8F1`、深墨文字 `#171D24`，并禁止根主题继续使用 `color-scheme: dark`。

```python
def test_cream_light_theme_contract():
    html = HTML_PATH.read_text(encoding="utf-8")
    assert "color-scheme: light" in html
    assert "#F3EFE5" in html
    assert "#FBF8F1" in html
    assert "#171D24" in html
    assert "color-scheme: dark" not in html
```

- [x] **Step 2: 添加战略编辑式结构测试**

要求首屏包含独立战略判断节点，桌面首屏闭环位于双栏内容之后，并存在轻量章节表面类名。

```python
def test_editorial_hero_and_light_diagram_contract():
    html = HTML_PATH.read_text(encoding="utf-8")
    assert 'class="hero-statement"' in html
    assert 'class="hero-loop-summary"' in html
    assert "--surface-paper" in html
    assert ".diagram" in html
```

- [x] **Step 3: 添加浅色 Logo 和移动布局测试**

要求继续使用内嵌 PNG，移动端出现专用纵向首屏闭环，并禁止通过 `transform: scale` 压缩 `.hero-map`。

```python
def test_cream_page_keeps_offline_logo_and_mobile_flow():
    html = HTML_PATH.read_text(encoding="utf-8")
    assert 'src="data:image/png;base64,' in html
    assert 'class="hero-flow-mobile"' in html
    assert ".hero-map { transform: scale" not in html
```

- [x] **Step 4: 运行测试确认 RED**

Run: `pytest -q tests/promotion/test_three_audience_html.py`

Expected: 新增的主题与结构测试失败，既有行为测试继续通过。

- [x] **Step 5: 提交测试契约**

```bash
git add tests/promotion/test_three_audience_html.py
git commit -m "test: define TaaS cream editorial contracts"
```

### Task 2: 重建设计令牌与全局页面表面

**Files:**
- Modify: `docs/promotion/ai-native-business-os-three-audience.html`
- Test: `tests/promotion/test_three_audience_html.py`

- [x] **Step 1: 替换根设计令牌**

将根变量改为以下浅色体系，并将现有语义变量映射到新令牌：

```css
:root {
  color-scheme: light;
  --canvas-cream: #F3EFE5;
  --surface-paper: #FBF8F1;
  --ink: #171D24;
  --muted: #69675F;
  --line: #D8D0C1;
  --line-strong: #B7AE9E;
  --token-violet: #7200FF;
  --drive-cyan: #079C94;
  --value-gold: #C58A00;
  --decision-red: #D92B55;
  --paper: var(--ink);
  --ocean-0: var(--canvas-cream);
  --ocean-1: var(--surface-paper);
  --ocean-2: #EAE3D6;
}
```

- [x] **Step 2: 清除深色背景效果**

将 `html`、`body`、粘性顶栏和工作区导航改成米白/纸白表面。移除深色径向光晕与高对比网格，保留极淡的纸张网格作为结构提示。

- [x] **Step 3: 统一正文与控件状态**

将正文、辅助文字、按钮、焦点、当前受众和当前章节状态调整为浅色背景可读的深墨/紫/青组合；交互状态不得依赖颜色透明度过低的白色文字。

- [x] **Step 4: 运行契约测试**

Run: `pytest -q tests/promotion/test_three_audience_html.py`

Expected: 浅色主题测试通过，尚未实现的编辑式结构测试仍失败。

- [x] **Step 5: 提交主题基础**

```bash
git add docs/promotion/ai-native-business-os-three-audience.html
git commit -m "style: establish TaaS cream light theme"
```

### Task 3: 重排首屏为战略编辑式结构

**Files:**
- Modify: `docs/promotion/ai-native-business-os-three-audience.html`
- Test: `tests/promotion/test_three_audience_html.py`

- [x] **Step 1: 调整首屏语义标记**

将首屏组织为 `hero-copy`、`hero-statement` 和 `hero-loop-summary` 三个明确区域。战略判断使用当前受众的 closing 文案，主文案区保留品牌名、定位、英文辅助名、标题和解释。

```html
<section class="shell hero">
  <div class="hero-copy">…</div>
  <aside class="hero-statement"><p id="hero-closing"></p></aside>
  <div class="hero-loop-summary">…</div>
</section>
```

- [x] **Step 2: 将桌面首屏闭环简化为水平证据链**

首屏只显示“业务目标 → 词元驱动 → 人工守门 → 可验证业务结果”，治理线位于其下，反馈线返回起点。删除抢夺主标题注意力的复杂波浪路径和运动粒子。

- [x] **Step 3: 调整首屏排版比例**

桌面端使用 `grid-template-columns: minmax(0, 2fr) minmax(260px, .85fr)`；闭环横跨全宽。主标题控制最大宽度，战略判断使用细黑竖线和较大正文，不制作卡片。

- [x] **Step 4: 完成移动端首屏顺序**

520px 以下按“品牌定义 → 受众标题 → 战略判断 → 纵向闭环”的顺序排列，纵向闭环使用真实块级布局，不缩放 SVG。

- [x] **Step 5: 运行契约测试**

Run: `pytest -q tests/promotion/test_three_audience_html.py`

Expected: 所有静态契约测试通过。

- [x] **Step 6: 提交首屏重排**

```bash
git add docs/promotion/ai-native-business-os-three-audience.html tests/promotion/test_three_audience_html.py
git commit -m "feat: reshape TaaS hero as editorial thesis"
```

### Task 4: 统一闭环轨道与六章图表语言

**Files:**
- Modify: `docs/promotion/ai-native-business-os-three-audience.html`
- Test: `tests/promotion/test_three_audience_html.py`

- [x] **Step 1: 将闭环轨道改为纸面蓝图**

节点使用纸白底与深墨文字；轨道使用暖灰线；词元、治理、人工、结果节点分别使用紫、青、金、双紫线表达。删除轨道独立深色带。

- [x] **Step 2: 统一章节容器**

所有章节使用一致的十二栏比例与留白。图表容器使用 `--surface-paper`，只保留一层细边框和轻微阴影；删除装饰性内框、切角和深色渐变。

- [x] **Step 3: 重绘范式与摩擦图**

范式图突出从“功能入口”到“结果闭环”的结构变化；摩擦图将分散痛点以细线汇聚到 TaaS，不使用多个同权重深色卡片。

- [x] **Step 4: 重绘架构与执行图**

架构图使用清晰的垂直层级；执行图使用单向水平流程，并将可信治理作为贯穿底轨，人工守门只在关键节点出现。

- [x] **Step 5: 重绘飞轮与价值图**

飞轮保留一个中心和五个外围阶段，使用细线圆环；价值图使用阶梯式结果证据，最后明确反馈到词元能力进化。

- [x] **Step 6: 检查所有 SVG 与动态生成颜色**

搜索硬编码深色值 `#081426`、`#060c17`、`rgba(8,20,38`、`rgba(5,11,22`，将 SVG 填充和 JavaScript 模板中的颜色全部迁移到浅色体系。

- [x] **Step 7: 运行契约测试**

Run: `pytest -q tests/promotion/test_three_audience_html.py`

Expected: 全部通过。

- [x] **Step 8: 提交图表统一**

```bash
git add docs/promotion/ai-native-business-os-three-audience.html
git commit -m "style: unify TaaS diagrams as light business blueprints"
```

### Task 5: 响应式、交互与说明文档

**Files:**
- Modify: `docs/promotion/ai-native-business-os-three-audience.html`
- Modify: `docs/promotion/ai-native-business-os-architecture-narrative.md`
- Test: `tests/promotion/test_three_audience_html.py`

- [x] **Step 1: 校准 1024 与 820 像素断点**

1024px 以下收紧双栏间距；820px 以下将章节变成单列，并确保图表文本不低于 12px、控制区可换行。

- [x] **Step 2: 校准 520 像素断点**

顶栏允许 Logo 和受众切换分行；导航按钮使用可换行网格；闭环与六类图表采用单列专用布局；禁止整体 `scale()` 适配。

- [x] **Step 3: 检查键盘和减少动态效果**

保留 `:focus-visible`，确保当前受众和章节具有非颜色唯一状态；`prefers-reduced-motion` 下禁用过渡和滚动动画。

- [x] **Step 4: 更新使用说明**

在叙事说明文档增加“米白战略编辑版”章节，记录色彩语义、首屏结构和修改文案时不应破坏的闭环规则。

- [x] **Step 5: 运行静态测试**

Run: `pytest -q tests/promotion/test_three_audience_html.py`

Expected: 全部通过。

- [x] **Step 6: 提交响应式与说明**

```bash
git add docs/promotion/ai-native-business-os-three-audience.html docs/promotion/ai-native-business-os-architecture-narrative.md
git commit -m "docs: document TaaS cream editorial presentation"
```

### Task 6: 浏览器视觉回归与最终验证

**Files:**
- Verify: `docs/promotion/ai-native-business-os-three-audience.html`
- Verify: `tests/promotion/test_three_audience_html.py`

- [x] **Step 1: 执行四档视口检查**

使用 Playwright 在 `1440x1000`、`1024x900`、`768x900`、`390x844` 打开本地 HTML，断言：

```javascript
document.documentElement.scrollWidth === innerWidth
document.querySelectorAll('.audience-tab').length === 3
document.querySelectorAll('.chapter').length === 6
```

- [x] **Step 2: 执行交互回归**

依次切换三类受众，进入演示模式，使用下一章按钮到达第六章；每一步要求只有一个 `.chapter.is-active`，标题和图表均存在。

- [x] **Step 3: 执行离线检查**

监听浏览器请求，要求除 `file:` 与 `data:` 外无其他请求；验证 Logo 自然尺寸大于零。

- [x] **Step 4: 截图并人工检查**

至少保存并检查桌面首屏、桌面章节、移动首屏和移动闭环四张截图，重点确认：米白底、TaaS 层级、战略判断、图表文字、章节留白与无裁切。

- [x] **Step 5: 运行完整测试**

Run: `pytest -q`

Expected: 全仓测试通过；若出现与本改版无关的既有失败，记录具体测试和堆栈，不擅自修改无关用户代码。

- [x] **Step 6: 检查差异质量**

Run:

```bash
git diff --check -- \
  docs/promotion/ai-native-business-os-three-audience.html \
  docs/promotion/ai-native-business-os-architecture-narrative.md \
  tests/promotion/test_three_audience_html.py
```

Expected: 无输出，退出码 0。

- [x] **Step 7: 提交最终改版**

```bash
git add docs/promotion/ai-native-business-os-three-audience.html \
  docs/promotion/ai-native-business-os-architecture-narrative.md \
  tests/promotion/test_three_audience_html.py \
  docs/superpowers/plans/2026-08-13-taas-cream-editorial-redesign.md
git commit -m "feat: redesign TaaS presentation in cream editorial style"
```
