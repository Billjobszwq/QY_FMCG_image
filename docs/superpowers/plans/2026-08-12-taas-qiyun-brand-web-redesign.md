# TaaS QIYUN Brand Web Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Rebrand the existing three-audience standalone presentation around `TaaS｜词元即服务` and `AI 原生业务操作系统`, using the real QIYUN logo and a disciplined token-flow visual language while preserving three complete business loops.

**Architecture:** Keep the single offline HTML and centralized `CONTENT` model. Embed the dark QIYUN logo as a local data URI, add stable brand fields, replace the decorative hero orbit with an input-processing-governance-result-feedback diagram, and update all copy and visual semantics so Chinese explains the product while English remains secondary.

**Tech Stack:** HTML5, CSS Grid, inline SVG, vanilla JavaScript, base64-embedded PNG, pytest static contracts, Playwright visual and interaction validation.

---

## File Structure

- Modify: `docs/promotion/ai-native-business-os-three-audience.html` — branded standalone presentation.
- Modify: `tests/promotion/test_three_audience_html.py` — TaaS naming, brand hierarchy, embedded-logo, token-flow, loop, disclosure, and offline contracts.
- Modify: `docs/promotion/ai-native-business-os-architecture-narrative.md` — TaaS definition and brand usage guidance.
- Modify: `docs/superpowers/plans/2026-08-12-taas-qiyun-brand-web-redesign.md` — execution tracking.

### Task 1: Add Failing TaaS and Brand Contracts

**Files:**
- Modify: `tests/promotion/test_three_audience_html.py`

- [x] **Step 1: Add naming and hierarchy assertions**

Add tests requiring:

```python
assert "TaaS｜词元即服务" in html
assert "AI 原生业务操作系统" in html
assert "Token as a Service" in html
assert "Token as a Severs" not in html
assert html.index("TaaS｜词元即服务") < html.index("Token as a Service")
```

- [x] **Step 2: Add brand-content assertions**

Require one stable `brand` object with `concept`, `positioning`, and `english`, plus the Chinese definition:

```text
词元不再只是智能模型处理内容的计量单位
驱动业务理解、决策、协同与执行的智能生产要素
```

Require all three audience entries to contain `TaaS` and audience-specific token roles.

- [x] **Step 3: Add embedded-logo assertions**

Require an `<img>` with class `qiyun-logo`, a `data:image/png;base64,` source, descriptive alt text, and no absolute source path. Reject the old `.brand-mark` synthetic mark.

- [x] **Step 4: Add token-flow and closed-loop assertions**

Require `token-flow`, `token-pulse`, `human-gate`, `verified-result`, and `feedback-return` semantics. Require all seven shared loop labels: 业务目标、可执行意图、词元驱动理解与决策、组织人员数据与能力、持续执行与人工守门、可验证业务结果、反馈评估与能力进化.

- [x] **Step 5: Run tests and verify RED**

Run:

```bash
pytest -q tests/promotion/test_three_audience_html.py
```

Expected: new TaaS and logo tests fail against the current presentation.

### Task 2: Embed the QIYUN Logo and Establish Brand Tokens

**Files:**
- Modify: `docs/promotion/ai-native-business-os-three-audience.html`

- [x] **Step 1: Encode the approved dark logo**

Read `/Users/zhangweiqi/Documents/QY/相关设计文档/logo-deep2.png`, base64 encode it without line wrapping, and insert it as the `src` of the header `qiyun-logo`. Keep the full original image and aspect ratio; do not crop or recolor it.

- [x] **Step 2: Replace the synthetic brand block**

Remove `.brand-mark` and the manually typed QIYUN wordmark. Render only the embedded logo in the top-left brand area with `alt="QIYUN 公司标识，DECISION DATA DRIVE"`. Size it as a supporting mark rather than a hero element.

- [x] **Step 3: Replace visual tokens with the approved palette**

Define and consistently use:

```css
--qiyun-deep: #060c17;
--token-violet: #7200ff;
--decision-red: #f52b61;
--value-gold: #ffbe18;
--drive-cyan: #08c9be;
--paper-white: #f4f7fc;
```

Use the full multi-color gradient only on `.token-flow` and its active path. Use single semantic colors elsewhere.

- [x] **Step 4: Replace decorative title typography**

Remove calligraphic and serif title fallbacks. Use `PingFang SC`, `Microsoft YaHei`, and system sans-serif for Chinese; use `Avenir Next`, `Helvetica Neue`, and system sans-serif for English and numerals. Keep Chinese titles at weight 600–700.

### Task 3: Rebuild the Hero and Shared Closed Loop

**Files:**
- Modify: `docs/promotion/ai-native-business-os-three-audience.html`

- [x] **Step 1: Add stable brand content**

Add to `CONTENT`:

```javascript
brand: {
  concept: 'TaaS｜词元即服务',
  positioning: 'AI 原生业务操作系统',
  english: 'Token as a Service'
}
```

Render these above audience-specific hero copy. Chinese concept and positioning must have stronger size and contrast than the English line.

- [x] **Step 2: Replace the orbit with a meaningful token-flow diagram**

Render an accessible SVG with these stages and explicit connectors:

```text
业务目标 → 词元流 → 智能理解与决策 → 能力组织 → 可验证结果
                           ↓ 人工守门
结果反馈 ───────────────────┘ 回到下一轮目标
```

Use a violet-red-gold-cyan gradient only for the token-flow line. Use a gold diamond for human approval, a cyan governance rail, and a violet double-border result.

- [x] **Step 3: Replace the shared loop labels**

Use exactly:

```javascript
['业务目标','可执行意图','词元驱动理解与决策','组织人员、数据与能力','持续执行与人工守门','可验证业务结果','反馈、评估与能力进化']
```

Preserve each audience's shorter loop as a secondary audience lens, not as the core architecture loop.

- [x] **Step 4: Make the feedback path visually closed**

The return line must visibly start at the result/feedback end and terminate with an arrow at 业务目标. At mobile widths, render the same loop as a vertical CSS track with a return label rather than shrinking the desktop SVG.

### Task 4: Rewrite the Three Audience Narratives Around TaaS

**Files:**
- Modify: `docs/promotion/ai-native-business-os-three-audience.html`

- [x] **Step 1: Rewrite the investor version**

Explain TaaS once in the hero or first chapter, then move through intelligent production factors, business execution, platform architecture, feedback assets, layered value, and category expansion. Keep the investor loop logically equivalent to demand → target → run → result → feedback → upgrade → more markets.

- [x] **Step 2: Rewrite the partner version**

Explain how tokens carry goals, context, and collaboration intent to organize platform and partner capabilities. Preserve capability ownership, trusted boundaries, joint delivery, contribution visibility, and reusable solution evolution.

- [x] **Step 3: Rewrite the customer version**

Lead with experience and results. Explain token technology only in plain Chinese: it helps the system understand the target and context, form a plan, and coordinate work. Preserve human approval, evidence, results, and next-round improvement.

- [x] **Step 4: Check Chinese-first balance**

Ensure no English paragraph carries a requirement or product explanation absent from Chinese. Limit English to brand expansion, short eyebrows, and the original logo slogan.

### Task 5: Upgrade All Diagram Families to the Brand System

**Files:**
- Modify: `docs/promotion/ai-native-business-os-three-audience.html`

- [x] **Step 1: Update paradigm and friction diagrams**

Add explicit input, token role, governance, result, and feedback annotations. Replace generic colored boxes with aligned cut-corner nodes and connectors using the approved semantic colors.

- [x] **Step 2: Update architecture and execution diagrams**

Show `TaaS 智能执行层` in the architecture without exposing implementation. In execution, place tokens between executable intent and capability organization; keep the human gate gold and governance rail cyan.

- [x] **Step 3: Update flywheel and value diagrams**

Make entry, delivery, feedback, validation, upgrade, and next opportunity explicit. Connect the value ladder back to capability evolution so the diagram is not an open-ended stack.

- [x] **Step 4: Apply one-time restrained motion**

Animate one token pulse along the hero flow and one return-path draw on entry. Do not loop indefinitely. Disable both when reduced motion is requested.

### Task 6: Verify Brand, Responsiveness, Logic, and Offline Delivery

**Files:**
- Modify: `docs/promotion/ai-native-business-os-three-audience.html`
- Modify: `docs/promotion/ai-native-business-os-architecture-narrative.md`
- Modify: `docs/superpowers/plans/2026-08-12-taas-qiyun-brand-web-redesign.md`

- [x] **Step 1: Reach GREEN on static contracts**

Run:

```bash
pytest -q tests/promotion/test_three_audience_html.py
```

Expected: all tests pass.

- [x] **Step 2: Verify embedded asset and offline behavior**

Confirm the logo source begins with `data:image/png;base64,`, the standalone HTML contains no network URLs or absolute logo paths, and opening the copied HTML from `/tmp` still displays the logo and all diagrams.

- [x] **Step 3: Run Playwright checks**

At 1440×1000, 1024×900, 768×900, and 390×844, assert no horizontal overflow; the logo has non-zero natural dimensions; TaaS concept is visible; three audience tabs and six chapters render; all audience switches, browsing/presentation modes, and previous/next controls work.

- [x] **Step 4: Inspect screenshots**

Review hero, shared loop, all six diagram families, and presentation mode on desktop and mobile. Reject logo distortion or square-edge mismatch, English-dominant hierarchy, rainbow overuse, clipped labels, crossing connectors, floating nodes, open feedback paths, and fixed-width mobile diagrams.

- [x] **Step 5: Update usage documentation**

Add the official TaaS definition, brand hierarchy, logo usage, and `CONTENT.brand` editing guidance to `docs/promotion/ai-native-business-os-architecture-narrative.md`.

- [x] **Step 6: Run final verification**

Run:

```bash
pytest -q tests/promotion/test_three_audience_html.py
git diff --check -- docs/promotion/ai-native-business-os-three-audience.html docs/promotion/ai-native-business-os-architecture-narrative.md tests/promotion/test_three_audience_html.py docs/superpowers/plans/2026-08-12-taas-qiyun-brand-web-redesign.md
```

Expected: tests pass and diff check returns no output.

- [x] **Step 7: Commit the branded presentation**

```bash
git add docs/promotion/ai-native-business-os-three-audience.html docs/promotion/ai-native-business-os-architecture-narrative.md tests/promotion/test_three_audience_html.py docs/superpowers/plans/2026-08-12-taas-qiyun-brand-web-redesign.md
git commit -m "feat: brand TaaS presentation with QIYUN identity"
```

