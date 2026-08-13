# web/ frontend map — Import Center, router/nav, scroll & focus behavior, batch-detail API flow

## Key files
- web/package.json — Vite5/React18/TS5.5; scripts: dev=vite, build=vite build, typecheck=tsc --noEmit
- web/src/main.tsx — entry; classic HashRouter wraps <App/>
- web/src/App.tsx — app shell: login gate, topbar, primary nav (.pnav), secondary nav (.snav), <Routes> from MODULE_ROUTES; useLocation at line 32 (no scroll effect)
- web/src/platform/ui_registry.tsx — MODULE_ROUTES/MODULE_REDIRECTS: single route→component registry; /data/import → ImportCenter (lazy), /status → SystemStatus (static)
- web/src/pages/ImportCenter.tsx — Import Center: 4 views (operational/mine/history/quarantine), batch detail card with dry-run/commit buttons (lines 213-222)
- web/src/api.ts — shared API client (fetch /api/v1/*); csrfToken() at :785; NO import endpoints here (labeling/training/etc only)
- web/src/platform/registry.ts — Module Registry projection: fetchModules/fetchIdentity/fetchProduction (drives nav)
- web/src/platform/components.tsx — shared UI: Loading/EmptyState/ErrorState/PageHeader/StatusBadge/DetailDrawer
- web/src/platform/SupervisorWorkspace.tsx — Supervisor side panel (board/chat), UIIntent whitelist execIntent(), only scrollTo in codebase (:179)
- web/src/platform/design/shell.css — shell layout & responsive breakpoints; .main-col has no overflow → window is the scroll container
- web/src/platform/design/tokens.css — design tokens (colors, --topbar-h, --nav-w, --side-w)
- web/vite.config.ts — dev port 5173, proxy /api → 127.0.0.1:8400, vendor chunk splitting
- src/platform/api/import_api.py — backend contract: GET/POST /api/v1/import/batches[/{id}[/dry-run|commit|preview|errors.csv]], view=operational|mine|history|quarantine

## Findings
## Architecture
- **Stack**: Vite 5.4 + React 18.3 + TypeScript 5.5 (strict, noUnusedLocals) + react-router-dom **6.26.2 classic `HashRouter`** (not a data router — no loaders, no `ScrollRestoration` available). Commands: `npm run typecheck` (= `tsc --noEmit`), `npm run build` (= `vite build`), `npm run dev` (port 5173, proxies `/api` → `http://127.0.0.1:8400`).
- **Entry**: `web/src/main.tsx` — `<HashRouter><App/></HashRouter>`.
- **Shell** (`web/src/App.tsx`): login gate via `fetchMe()`; renders topbar, `<nav className="pnav">` primary nav, `<nav className="snav">` secondary nav, `<Routes>`, footer, plus `<SupervisorWorkspace/>`. `location = useLocation()` at **App.tsx:32** — used only for active-module matching; **no effect reacts to location change**.

## Router & navigation
- **Primary nav** (App.tsx:128-144): projected live from backend Module Registry (`fetchModules()` → GET /api/v1/modules, `platform/registry.ts`); filtered (`reference.echo` hidden, `system` admin-only, App.tsx:106-110). `NavLink` to `m.navigation[0]?.route ?? m.primary_route`.
- **Secondary nav** (App.tsx:146-154): `currentModule.navigation` links.
- **Routes**: built from `MODULE_ROUTES` / `MODULE_REDIRECTS` in `platform/ui_registry.tsx` (keys must match backend module_catalog routes). Almost all pages are route-level `lazy()` wrapped in `wide()` = `<div className="page wide"><Suspense fallback="模块加载中…">…`. **Exceptions**: `/home` and `/status` (SystemStatus) are static imports; `/status` is rendered **bare** (no `.page`/`wide` wrapper, ui_registry.tsx:210). Legacy routes redirect (App.tsx:167-192). Two deep-link lazy pages: `/vision/cascade`, `/vision/packaging`.
- **Supervisor / UIIntent**: `platform/SupervisorWorkspace.tsx` — right panel (board/chat tabs); agent chat via `/api/agent/v1/...`; `execIntent()` (lines 26-37) executes a whitelist of structured UIIntents; only `navigate` actually calls react-router `navigate(target)` — this path also triggers route changes without scroll reset.

## Import Center (`web/src/pages/ImportCenter.tsx`, 310 lines, default export, lazy at ui_registry.tsx:76)
- **Four views** = local `useState` tabs, VIEWS const at lines 33-38: `operational`/`mine`/`history`/`quarantine` (labels 运营导入/我的批次/Test Run·历史证据/隔离待处理). Tab buttons lines 258-266 (`role="tablist"`). **Not** URL-driven — switching views does not change the route. `load()` lines 65-74: GET `/api/v1/import/templates` + GET `/api/v1/import/batches?view=<v>` (history adds `include_fixture=1`).
- **Local API helpers** `api()`/`apiPost()` lines 40-54: plain `fetch('/api/v1'+path)`; POST attaches `X-CSRF-Token` via `csrfToken()` imported from `../api` (token set at login in api.ts:797/805). `web/src/api.ts` (1401 lines) contains **no** import endpoints — Import Center is self-contained.
- **Batch detail fetch**: row click `<tr onClick>` lines 278-287 → GET `/api/v1/import/batches/{batch_id}` → `setDetail(d.batch)`. Same detail card is also set after upload (line 95) and after dry-run/commit (line 106).
- **Quarantine detail → dry-run/commit buttons**: the detail card (lines 195-254) renders **unconditionally for any batch status** — the buttons at **lines 213-222** (`dry-run` btn → `act(id,"dry-run")`, `提交` btn → `act(id,"commit")`, POST `/api/v1/import/batches/{id}/dry-run|commit` via `apiPost`, lines 102-110) appear for quarantined batches too; only `disabled={busy}` gates them. This is the UI surface of the quarantine write-escape (backend import_api.py:126-149 is where enforcement must live). Also renders errors table, commit stats, receipts (incl. one-time initial password display, lines 244-253).

## Scroll behavior — the bug (y=2124 → y≈1504)
- **Search results**: `scrollTo|scrollRestoration|scrollTop|scrollIntoView|scroll-behavior` across `web/src` → exactly **ONE hit**: `SupervisorWorkspace.tsx:179` (chat box auto-scroll-to-bottom). **There is no scroll reset on route change anywhere**, no `history.scrollRestoration` config, no `useLocation` scroll effect, no ScrollRestoration component.
- **Scroll container is `window`**: `.abos-app { min-height: 100vh }` (shell.css:4); `.main-col` (shell.css:71) has no `overflow` — main content scrolls the document/body. Only `.pnav` (shell.css:44-48), `.side-panel` (shell.css:183-188), `.drawer` have internal overflow-y.
- **Mechanism**: HashRouter navigation only mutates `location.hash`; the browser neither resets `window.scrollY` nor the app does. On `/data/import` the user scrolls deep (y=2124: templates card + upload card + detail card + batch table). Clicking 系统管理 navigates to `/status`; the new document is shorter / still loading (SystemStatus data arrives async), so the browser **clamps** scrollY to the new max scroll (≈1504) and it stays there instead of returning to top. Lazy routes worsen this: during chunk load the Suspense fallback is a one-line `<p>`, collapsing document height at swap time; when real content mounts the scroll stays clamped.
- **Exact fix spot**: App.tsx already has `useLocation()` (line 32) — add a location-keyed effect calling `window.scrollTo(0, 0)` there (or a ScrollToTop component mounted in App/main). Since window is the scroll container, `window.scrollTo` is correct; no per-container handling needed.

## Accessibility / focus
- **No focus management on route change** anywhere (no `.focus()` calls in src; no aria-live route announcements). `tabIndex` used only in Vision.tsx:92,359 and Workflow.tsx:103. `DetailDrawer` (components.tsx:55-78) handles Esc + `aria-modal` but never moves focus on open/close and doesn't restore it.
- Positives: landmark aria-labels on both navs, `role="tablist"/tab` on view switchers, `:focus-visible` outlines (shell.css:177-180), `prefers-reduced-motion` respected (shell.css:313).
- **Gap**: Import Center batch rows are `<tr onClick>` with no `tabIndex`/`onKeyDown` (ImportCenter.tsx:278-287) — mouse-only.

## Viewports / responsive (shell.css:260-339)
Breakpoints: ≤1280 (side-w 320px), ≤1279 (non-card tables x-scroll), ≤1439 (Supervisor becomes fixed overlay drawer; JS threshold 1440 for dock, SupervisorWorkspace.tsx:98-99), ≤1024 (side-panel → bottom sheet 62vh; nav-w 180px; `table.table` converts to stacked cards via `data-label`), ≤768 (side-panel full-screen; nav-w 132px; status pills hidden). Note ImportCenter's tables use `data-label` attrs specifically for this card conversion.

## Risks
- Scroll-persistence bug confirmed as absence of code: no scroll reset on route change exists anywhere in web/src (only scrollTo is chat autoscroll, SupervisorWorkspace.tsx:179); window is the scroll container (shell.css:4,71), so window.scrollY carries across HashRouter navigations and gets clamped on shorter/slower-loading pages — root cause of y=2124→y≈1504 (Import Center → /status). Fix point: App.tsx:32 useLocation, add scrollTo(0,0) effect.
- Quarantine write-escape UI surface: ImportCenter.tsx:213-222 renders dry-run/commit buttons for every batch regardless of status (no gating on detail.status/view); enforcement currently relies entirely on backend import_api.py:126-149. Related to tasks #2/#4.
- Batch detail row interaction is mouse-only: <tr onClick> at ImportCenter.tsx:278-287 has no tabIndex/onKeyDown — keyboard users cannot open batch details.
- No focus handoff on route change or drawer open/close (DetailDrawer components.tsx:55-78 sets aria-modal but never focuses/restores focus) — a11y gap for keyboard/AT users.
- SupervisorWorkspace.tsx:297-298 reads window.innerWidth during render with no resize listener — dock/drawer breakpoint decisions go stale until next render.
- Import Center view state (operational/mine/history/quarantine) is component-local useState (ImportCenter.tsx:59,264), not URL state — deep-linking/back-button to a specific view is impossible, and the detail selection is lost on remount (lazy route unmount).
- Detail card can surface one-time initial passwords (ImportCenter.tsx:244-253) — frontend displays initial_password_once from receipts; persistence policy is backend's concern (task #3).
- Dead code: ModulePage in App.tsx:24-29 returns null and is kept only with `void ModulePage`.

## Open questions
- Does backend import_api.py dry-run/commit currently 403 for quarantine-status batches (the write-escape question, task #2) — frontend shows the buttons unconditionally, so backend behavior decides severity; needs reading src/platform/import_center.py (service layer) to confirm.
- Desired scroll fix semantics: always scroll-to-top on pathname change, or preserve position only for same-path (e.g., view-switch within Import Center is state-based so unaffected)? Supervisor UIIntent navigate (SupervisorWorkspace.tsx:31-34) goes through the same router navigate, so a central App-level effect covers it.
- Whether /status being rendered without the .page/.wide wrapper (ui_registry.tsx:210) is intentional — it changes padding/max-width vs every other module page and affects measured scroll heights.