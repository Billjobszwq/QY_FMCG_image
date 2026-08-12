# AI Native Business OS Promotion Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a polished, investor-facing Chinese visualization suite that introduces the new AI-native business operating experience, explains the complete architecture in progressive layers, and protects core technical details.

**Architecture:** Build one self-contained interactive HTML visualization with eight vertically arranged, individually understandable diagrams and concise presenter notes. Use semantic HTML and hand-authored responsive SVG/CSS so the diagrams remain legible at presentation and mobile widths; keep all content local and omit implementation-sensitive names, algorithms, routes, thresholds, and infrastructure brands.

**Tech Stack:** HTML fragment, scoped CSS, inline SVG, vanilla JavaScript only for diagram navigation, Codex visualization renderer for validation.

---

## File Structure

- Create: `/Users/zhangweiqi/.codex/visualizations/2026/08/12/019ff54f-37e2-7631-a034-9764f153b65b/ai-native-business-os-architecture.html` — the complete in-conversation visualization, including all eight diagrams, descriptions, navigation, responsive behavior, and accessibility text.
- Create: `docs/promotion/ai-native-business-os-architecture-narrative.md` — durable Chinese presenter narrative, per-diagram explanation, disclosure boundary, and suggested presentation order.
- Modify: `docs/superpowers/plans/2026-08-12-ai-native-business-os-promotion-architecture.md` — check completed tasks while executing.

### Task 1: Freeze Public Vocabulary and Presenter Narrative

**Files:**
- Create: `docs/promotion/ai-native-business-os-architecture-narrative.md`

- [x] **Step 1: Write the eight-section narrative**

Create the document with these exact section titles and intended messages:

```markdown
# AI 原生业务操作系统｜推广架构讲解稿

## 1. 从提出目标，到获得可验证结果
先讲用户体验变化：目标成为入口，系统负责组织工作，人类保留关键决定权。

## 2. AI 原生业务操作系统总体架构
解释多元入口、智能执行内核、业务能力网络、可信业务底座和生态部署边界。

## 3. 智能执行闭环
解释理解、计划、执行、观察、调整、人机协同、交付和评估的完整循环。

## 4. 可组合业务能力网络
解释领域能力如何围绕目标组合，并独立扩展而不形成新的系统孤岛。

## 5. 可信业务底座
解释身份、事实、证据、任务、用量和审计如何让智能执行可控可信。

## 6. 持续进化但始终受控
解释反馈如何经评估、验证、审批和版本升级形成能力进化。

## 7. 行业闭环示例
用发现并改善重点门店执行问题串联规划、外勤、识别、问卷、分析、追踪和核算。

## 8. 新范式带来的体验跃迁
以目标即入口、系统主动组织、跨域组合、人机共同决策和全程可追溯结束叙事。
```

Under every section add exactly three short subsections: `它解决什么`、`它如何工作`、`它带来什么`. Add a final `对外披露边界` section that names both allowed product-level concepts and prohibited implementation details.

- [x] **Step 2: Run vocabulary protection checks**

Run:

```bash
rg -n 'Qwen|YOLO|SAM|DeepSeek|PostgreSQL|Redis|MinIO|Label Studio|FastAPI|React Flow|端口|阈值|提示词|路由策略|数据库表' docs/promotion/ai-native-business-os-architecture-narrative.md
```

Expected: no output.

- [x] **Step 3: Check the narrative for placeholders and diff errors**

Run:

```bash
rg -n 'TBD|TODO|待补|占位' docs/promotion/ai-native-business-os-architecture-narrative.md
git diff --check -- docs/promotion/ai-native-business-os-architecture-narrative.md
```

Expected: no output from either command.

- [x] **Step 4: Commit the narrative**

```bash
git add docs/promotion/ai-native-business-os-architecture-narrative.md
git commit -m "docs: add AI native business OS promotion narrative"
```

### Task 2: Build the New Experience and Overall Architecture Diagrams

**Files:**
- Create: `/Users/zhangweiqi/.codex/visualizations/2026/08/12/019ff54f-37e2-7631-a034-9764f153b65b/ai-native-business-os-architecture.html`

- [x] **Step 1: Create the visualization shell**

Create an HTML fragment rooted at `#abos-architecture`. Add scoped CSS with `light-dark()` surfaces, a deep-indigo intelligent-execution color, teal trusted-foundation color, and warm-gold human-decision color. Include a concise header, an eight-item progress navigator using native buttons, and eight semantic `<section>` elements. The navigator must set `aria-current="true"` on the selected section and call `scrollIntoView({behavior:'smooth', block:'start'})`.

- [x] **Step 2: Add diagram 1 — new experience overview**

Draw a left-to-right SVG sequence:

```text
业务目标 → 理解与计划 → 组织人和能力 → 持续推进 → 可验证结果
                                  ↕
                              人类关键决策
```

Use the headline `从提出目标，到获得可验证结果` and the supporting line `目标成为入口，系统承担组织、推进与反馈。` Do not mention competing product categories in this diagram.

- [x] **Step 3: Add diagram 2 — overall architecture**

Draw a four-level responsive architecture:

```text
多元业务入口
      ↓
智能执行与持续进化内核
      ↓
可组合业务能力网络
      ↓
可信业务底座
```

Place `生态连接` and `灵活部署` as side rails rather than core layers. Show the eight public domain capabilities: 智能识别、外勤与位置、调研与问卷、分析与经营、客户与主数据、流程与协作、财务与结算、行业能力扩展.

- [x] **Step 4: Validate structure and forbidden vocabulary**

Run:

```bash
rg -n '<section|aria-current|scrollIntoView|从提出目标|智能执行与持续进化内核|可信业务底座' /Users/zhangweiqi/.codex/visualizations/2026/08/12/019ff54f-37e2-7631-a034-9764f153b65b/ai-native-business-os-architecture.html
rg -n 'Qwen|YOLO|SAM|DeepSeek|PostgreSQL|Redis|MinIO|Label Studio|FastAPI|React Flow|localhost|/api/|阈值|提示词|路由策略' /Users/zhangweiqi/.codex/visualizations/2026/08/12/019ff54f-37e2-7631-a034-9764f153b65b/ai-native-business-os-architecture.html
```

Expected: the first command finds the required structure; the second command returns no output.

### Task 3: Add the Four Architecture Detail Diagrams

**Files:**
- Modify: `/Users/zhangweiqi/.codex/visualizations/2026/08/12/019ff54f-37e2-7631-a034-9764f153b65b/ai-native-business-os-architecture.html`

- [x] **Step 1: Add diagram 3 — intelligent execution loop**

Use an eight-stage circular SVG flow: 理解目标、形成计划、组织能力、执行任务、观察结果、判断调整、人机协同、交付评估. Put `权限 · 预算 · 证据 · 审批` in the center. Add the presenter line `能行动，也知道何时停下并请求人类决定。`

- [x] **Step 2: Add diagram 4 — composable capability network**

Put `智能执行内核` at the center and the eight public domain capabilities around it. Add three visible outcomes: `一个目标跨域完成`、`新能力快速接入`、`能力独立升级组合`.

- [x] **Step 3: Add diagram 5 — trusted business foundation**

Build a supporting-platform diagram with six blocks: 身份与边界、业务事实、证据链、任务与事件、用量与价值、安全与审计. Above it place three supported properties: 可控、可追溯、可恢复.

- [x] **Step 4: Add diagram 6 — controlled evolution**

Draw two connected loops: `业务运行闭环` and `能力升级闭环`. The only connection from feedback to active capability must pass through `评估 → 验证 → 人工批准 → 新版本`. Add `不直接改写业务事实` as a boundary annotation.

- [x] **Step 5: Run detail-diagram content checks**

Run:

```bash
for term in '理解目标' '形成计划' '人机协同' '一个目标跨域完成' '身份与边界' '用量与价值' '人工批准' '不直接改写业务事实'; do rg -q "$term" /Users/zhangweiqi/.codex/visualizations/2026/08/12/019ff54f-37e2-7631-a034-9764f153b65b/ai-native-business-os-architecture.html || exit 1; done
```

Expected: exit code 0.

### Task 4: Add the Proof Story and Experience Leap Diagrams

**Files:**
- Modify: `/Users/zhangweiqi/.codex/visualizations/2026/08/12/019ff54f-37e2-7631-a034-9764f153b65b/ai-native-business-os-architecture.html`

- [x] **Step 1: Add diagram 7 — industry closed-loop example**

Create an eight-stage journey: 经营目标、任务规划、现场执行、智能识别、调研核验、异常分析、持续追踪、结果与核算. Mark task approval, exception review, and result publication as warm-gold human checkpoints. Show four outputs: 问题清单、执行证据、改进进度、经营洞察与可核对成本.

- [x] **Step 2: Add diagram 8 — experience leap**

Use a two-state transformation without making the old state the headline. The muted state contains 找入口、搬数据、催流程、难追溯、定制孤岛. The dominant state contains 目标即入口、系统主动组织、跨域能力组合、人机共同决策、全程有证据、持续进化. Title it `从使用软件，走向运营一套会工作的系统`.

- [x] **Step 3: Add concise presenter notes**

For every one of the eight sections, add a three-line note with the labels `解决`、`机制`、`价值`. Each note must fit within 90 Chinese characters per line and must not repeat the full diagram labels.

- [x] **Step 4: Add accessible text alternatives**

Every SVG must have `role="img"`, a unique `aria-labelledby`, and matching `<title>` plus `<desc>`. Every navigation control must be a native `<button type="button">`.

### Task 5: Render, Inspect, and Harden the Final Visualization

**Files:**
- Modify: `/Users/zhangweiqi/.codex/visualizations/2026/08/12/019ff54f-37e2-7631-a034-9764f153b65b/ai-native-business-os-architecture.html`
- Modify: `docs/superpowers/plans/2026-08-12-ai-native-business-os-promotion-architecture.md`

- [x] **Step 1: Validate HTML fragment rules**

Run:

```bash
rg -n '<!doctype|<html|<head|<body|fetch\(|XMLHttpRequest|WebSocket|document\.currentScript|\\n|\\"' /Users/zhangweiqi/.codex/visualizations/2026/08/12/019ff54f-37e2-7631-a034-9764f153b65b/ai-native-business-os-architecture.html
```

Expected: no output.

- [x] **Step 2: Render a standalone inspection copy**

Run:

```bash
python3 /Users/zhangweiqi/.codex/plugins/cache/openai-bundled/visualize/1.0.20/skills/visualize/scripts/render.py /Users/zhangweiqi/.codex/visualizations/2026/08/12/019ff54f-37e2-7631-a034-9764f153b65b/ai-native-business-os-architecture.html /tmp/ai-native-business-os-architecture-preview.html
```

Expected: the renderer reports a successfully written standalone HTML file.

- [x] **Step 3: Inspect at desktop and mobile widths**

Open the rendered copy at 736px and 360px. Verify: no clipped Chinese labels, no horizontal scrolling, arrows point in the intended direction, all eight diagrams are visible, navigator buttons work, selected navigation state updates, and notes remain readable. Fix any violation in the source fragment and repeat the render.

- [x] **Step 4: Re-run disclosure and completeness checks**

Run:

```bash
for term in '从提出目标，到获得可验证结果' 'AI 原生业务操作系统总体架构' '智能执行闭环' '可组合业务能力网络' '可信业务底座' '持续进化但始终受控' '行业闭环示例' '从使用软件，走向运营一套会工作的系统'; do rg -q "$term" /Users/zhangweiqi/.codex/visualizations/2026/08/12/019ff54f-37e2-7631-a034-9764f153b65b/ai-native-business-os-architecture.html || exit 1; done
rg -n 'Qwen|YOLO|SAM|DeepSeek|PostgreSQL|Redis|MinIO|Label Studio|FastAPI|React Flow|localhost|/api/|阈值|提示词|路由策略|数据库表' /Users/zhangweiqi/.codex/visualizations/2026/08/12/019ff54f-37e2-7631-a034-9764f153b65b/ai-native-business-os-architecture.html docs/promotion/ai-native-business-os-architecture-narrative.md
```

Expected: the loop exits 0 and the final `rg` returns no output.

- [x] **Step 5: Mark the plan complete and commit durable documentation**

Check every completed checkbox in this plan, then run:

```bash
git add docs/promotion/ai-native-business-os-architecture-narrative.md docs/superpowers/plans/2026-08-12-ai-native-business-os-promotion-architecture.md
git commit -m "docs: complete AI native business OS architecture package"
```

