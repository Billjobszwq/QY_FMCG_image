# AI Native Business OS Three-Audience HTML Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one polished, offline-capable HTML presentation that switches among investor, ecosystem-partner, and prospective-customer narratives while preserving a complete target-to-feedback business loop in every version.

**Architecture:** Create a single standalone document with all editable copy centralized in a `CONTENT` object and a small renderer that builds the hero, six chapters, diagrams, navigation, and presentation controls. Use semantic HTML, scoped CSS, inline SVG, and vanilla JavaScript; no external resources or implementation-sensitive content.

**Tech Stack:** HTML5, CSS Grid, inline SVG, vanilla JavaScript, Playwright for responsive and interaction validation.

---

## File Structure

- Create: `docs/promotion/ai-native-business-os-three-audience.html` — final standalone presentation and editable source.
- Create: `tests/promotion/test_three_audience_html.py` — static contract tests for content shape, disclosure boundary, closed-loop vocabulary, accessibility, and offline constraints.
- Modify: `docs/promotion/ai-native-business-os-architecture-narrative.md` — add a short usage note linking the new HTML and explaining where copy is edited.
- Modify: `docs/superpowers/plans/2026-08-12-ai-native-business-os-three-audience-html.md` — mark completed execution steps.

### Task 1: Define Static Contracts Before Building

**Files:**
- Create: `tests/promotion/test_three_audience_html.py`

- [ ] **Step 1: Write failing structural tests**

Create tests that load `docs/promotion/ai-native-business-os-three-audience.html` and assert:

```python
assert "const CONTENT" in html
assert all(key in html for key in ("investor", "partner", "customer"))
assert html.count("data-audience=") >= 3
assert "role=\"tablist\"" in html
assert "aria-live=\"polite\"" in html
assert "prefers-reduced-motion" in html
```

Add one test that requires each audience block to contain its declared loop vocabulary:

```python
required = {
    "investor": ["市场需求", "反馈资产", "能力升级", "更多客户与场景"],
    "partner": ["客户目标", "联合执行", "价值确认", "更多合作机会"],
    "customer": ["业务问题", "智能执行", "可验证结果", "下一轮目标"],
}
```

Add a disclosure test rejecting internal model, infrastructure, endpoint, prompt, threshold, and database terminology listed in the approved design.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
pytest -q tests/promotion/test_three_audience_html.py
```

Expected: FAIL because `docs/promotion/ai-native-business-os-three-audience.html` does not exist.

### Task 2: Build the Standalone Shell and Editable Content Model

**Files:**
- Create: `docs/promotion/ai-native-business-os-three-audience.html`

- [ ] **Step 1: Create the valid standalone document**

Add `<!doctype html>`, Chinese language metadata, responsive viewport, descriptive title, inline styles, one application root, and inline script. Do not load fonts, scripts, images, analytics, or stylesheets from the network.

- [ ] **Step 2: Define the complete `CONTENT` object**

Define `investor`, `partner`, and `customer`. Each entry must contain:

```javascript
{
  label: '',
  shortLabel: '',
  hero: { eyebrow: '', title: '', lead: '', closing: '' },
  loop: ['', '', '', '', '', '', ''],
  sections: [
    { eyebrow: '', title: '', thesis: '', diagram: '', values: ['', '', ''], transition: '' }
  ],
  cta: { title: '', body: '', action: '' }
}
```

Provide exactly six sections per audience. Use the approved narrative order and ensure each `transition` introduces the next chapter.

- [ ] **Step 3: Add edit guidance inside the source**

Immediately above `CONTENT`, add a clear Chinese comment explaining that ordinary copy changes should be made only inside `CONTENT`; document the stable fields and advise keeping `loop` at seven stages.

- [ ] **Step 4: Implement deterministic rendering**

Implement `renderAudience(key)`, `renderSection(section, index)`, `renderDiagram(type, audience, index)`, `setChapter(index)`, and `setMode(mode)`. Validate the selected audience key and section index before rendering. Default to `investor`, browsing mode, chapter zero.

### Task 3: Build the Formal Visual System and Diagrams

**Files:**
- Modify: `docs/promotion/ai-native-business-os-three-audience.html`

- [ ] **Step 1: Implement the presentation token system**

Use a deep-ocean canvas, restrained coordinate grid, electric-blue execution, teal governance, amber human decisions, violet results/evolution, and neutral external context. Define consistent spacing, twelve-column desktop layout, line weights, arrow markers, cut-corner nodes, diamond approval nodes, double-border result nodes, and continuous foundation bands.

- [ ] **Step 2: Implement the signature closed-loop rail**

Render all seven stages with directional connectors and a visible return path from feedback to the next goal. Use SVG marker arrows; keep labels outside paths; add an accessible `<title>` and `<desc>`. Change stage labels with the selected audience while preserving geometry.

- [ ] **Step 3: Implement six diagram families**

Implement these `diagram` types:

```text
paradigm     — before/after operating dimension
friction     — fragmented actors converging on one target
architecture — four formal layers plus side boundaries
execution    — target-to-result rail with human gates and governance guardrails
flywheel     — closed feedback flywheel with explicit entry, result, validation, and return
value        — result/value stack and next-step expansion
```

Every diagram must expose the same architecture truth but derive emphasis and labels from the current audience.

- [ ] **Step 4: Make layout responsive**

At widths below 820px, convert multi-column diagrams into vertical tracks. At widths below 520px, stack controls and value statements, simplify connector turns, and preserve at least 14px body text. Do not use horizontal scrolling or scaled-down fixed-width canvases.

### Task 4: Add Audience Switching and Presentation Controls

**Files:**
- Modify: `docs/promotion/ai-native-business-os-three-audience.html`

- [ ] **Step 1: Implement accessible audience tabs**

Use three native buttons with `role="tab"`, `aria-selected`, and `aria-controls`. Support click, Enter/Space, and left/right arrow navigation. Switching audience resets to chapter zero and updates all hero, loop, chapter, diagram, values, transition, and CTA content.

- [ ] **Step 2: Implement chapter navigation**

Build six chapter buttons from current content. In browsing mode they scroll to the matching section; in presentation mode they replace the visible chapter. Keep `aria-current="step"` synchronized.

- [ ] **Step 3: Implement browsing and presentation modes**

Add a mode switch and Previous/Next controls. Presentation mode shows one chapter at a time; browsing mode shows all six. Disable Previous at chapter zero and Next at chapter five. Preserve the active audience across mode changes.

- [ ] **Step 4: Respect motion and keyboard use**

Use one short section transition and one loop-path drawing transition. Disable both under `prefers-reduced-motion: reduce`. Maintain visible focus indicators and native tab order.

### Task 5: Verify Logic, Visual Quality, and Editability

**Files:**
- Modify: `docs/promotion/ai-native-business-os-three-audience.html`
- Modify: `docs/promotion/ai-native-business-os-architecture-narrative.md`

- [ ] **Step 1: Run static tests and reach GREEN**

Run:

```bash
pytest -q tests/promotion/test_three_audience_html.py
```

Expected: all tests pass.

- [ ] **Step 2: Run browser checks at four widths**

Use Playwright to open the local file at 1440×1000, 1024×900, 768×900, and 390×844. For each width assert:

```javascript
document.documentElement.scrollWidth === document.documentElement.clientWidth
document.querySelectorAll('[data-rendered-section]').length === 6
document.querySelectorAll('[role="tab"]').length === 3
```

Switch through all audiences, confirm the active label and CTA change, switch presentation mode, traverse all six chapters, and capture screenshots for visual inspection.

- [ ] **Step 3: Inspect screenshots and correct geometry**

Check node alignment, arrow direction, return paths, label clipping, text contrast, chapter rhythm, and mobile stacking. Reject any diagram with floating nodes, unexplained lines, connector crossings through labels, uneven baseline alignment, or an open feedback loop.

- [ ] **Step 4: Verify offline and disclosure constraints**

Run:

```bash
rg -n 'https?://|fetch\(|XMLHttpRequest|WebSocket' docs/promotion/ai-native-business-os-three-audience.html
rg -n 'Qwen|YOLO|SAM|DeepSeek|PostgreSQL|Redis|MinIO|Label Studio|FastAPI|React Flow|localhost|/api/|阈值|提示词|路由策略|数据库表' docs/promotion/ai-native-business-os-three-audience.html
```

Expected: no output.

- [ ] **Step 5: Document usage**

Add a `三受众 HTML 使用说明` section to `docs/promotion/ai-native-business-os-architecture-narrative.md` with the relative file link, browser-opening instruction, audience-switch behavior, and exact guidance to edit only the `CONTENT` object for copy changes.

- [ ] **Step 6: Run project-level verification**

Run:

```bash
pytest -q tests/promotion/test_three_audience_html.py
git diff --check -- docs/promotion/ai-native-business-os-three-audience.html docs/promotion/ai-native-business-os-architecture-narrative.md tests/promotion/test_three_audience_html.py docs/superpowers/plans/2026-08-12-ai-native-business-os-three-audience-html.md
```

Expected: tests pass and diff check produces no output.

- [ ] **Step 7: Commit the finished package**

```bash
git add docs/promotion/ai-native-business-os-three-audience.html docs/promotion/ai-native-business-os-architecture-narrative.md tests/promotion/test_three_audience_html.py docs/superpowers/plans/2026-08-12-ai-native-business-os-three-audience-html.md
git commit -m "feat: add three-audience AI business OS presentation"
```

