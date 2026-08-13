# OSV5 Gate 3.2 evidence chain: static gate.json vs live /api/v1/control/gate, hash bindings, self-compare flaw, and artifact regeneration CLIs

## Key files
- scripts/osv5_gate_evaluate.py — full gate regeneration script; contains the self-compare flaw at lines 116-118 (recorded==current tree/migration/HEAD)
- src/platform/gate_evaluator.py — 52-check evidence-driven evaluator; freshness re-eval path at lines 250-288; db_fingerprint at 174-208; STALE priority at 868
- src/platform/api/control_plane_api.py — live GET /api/v1/control/gate (lines 187-220): picks newest .eval/*/gate.json by mtime, re-checks only HEAD + db_fingerprint
- .eval/scope_v5/gate.json — static gate artifact (READY_FOR_REAL_DATA_UAT, 52 checks, source_commit 8e31708d, db_fingerprint, evidence_hashes)
- .eval/scope_v5/uatv7/report.json — UAT V7 report, 23/23 checks, NO commit/tree binding field
- .eval/scope_v5/test_report.json — hand-written pytest summary (1479 passed), no generator script, no HEAD binding
- .eval/scope_v5/browser/browser_evidence.json — CDP browser evidence, 29 pages / 28 screenshots, gate_observed=STALE_GATE_EVIDENCE at capture, no commit binding
- .eval/scope_v5/gate_negative_tests.json — 12 negative tests all blocked, incl. stale_head_binding_detected (only covers explicit x≠y, not the self-compare)
- .eval/scope_v5/before/before_audit_v5.json — pre-fix defect baseline (P0-001..006, P1-004 version drift)
- scripts/uatv7_rehearsal.py — UAT V7 generator against live stack; writes uatv7/report.json
- scripts/osv5_browser_evidence.py — browser evidence generator via CDP Chrome on port 9227
- scripts/osv5_gate_negative.py — hermetic negative-test runner (temp DB + TestClient)
- pyproject.toml — pytest addopts '-m not host_mps' defines the hermetic suite behind test_report.json
- docs/implementation/agentic-business-os-operational-scope-v5/ISSUES.md — issue ledger consumed by no_open_p0_p1 (0 OPEN; all OSV5-001..012 CLOSED)
- docs/implementation/agentic-business-os-operational-scope-v5/EXECUTION-LOG.md — T0-T10 timeline and CLI provenance for each artifact

## Findings
## 1. Live gate vs static gate.json — two different computations

**Static `.eval/scope_v5/gate.json` = FULL evaluation.** Produced by `python3 scripts/osv5_gate_evaluate.py` (runs at 2026-08-13T14:14:35+0800, 20s after HEAD commit):
- Opens the LIVE DB `.platform/platform.sqlite` via `build_production_bundle` (osv5_gate_evaluate.py:100-104).
- Computes `head = git rev-parse HEAD` (osv5_gate_evaluate.py:31-37,105), `tree = _tree_hash()` = sha256[:16] over all files in `src/platform`, `web/src`, `scripts` (path+content, skipping `__pycache__`/dotfiles; osv5_gate_evaluate.py:51-62), `mig = _migration_hash()` = sha256[:16] of `SELECT name FROM schema_migrations ORDER BY id` (osv5_gate_evaluate.py:65-69).
- Calls `evaluate_gate_from_evidence(...)` WITHOUT `recorded_gate_path` → runs the full 52-check battery (gate_evaluator.py:290-857): 4 code-binding checks, ~30 direct-SQL scope-lineage/registry/BI re-computations ("直接重算，不信自报"), UAT report consumption + `scripts/uat_report_validator.validate_report`, terminal-drift scan, agent-failure ledger, `PRAGMA integrity_check`, ISSUES.md open-P0/P1 parse, test_report `failed==0`, browser-evidence semantic checks (files exist, console clean, 4 viewports, 12 required routes, import view separation, per-page assertion==true), live HTTP service probes (8400/8091/8092/8300; osv5_gate_evaluate.py:72-89).
- Appends `db_fingerprint` (gate_evaluator.py:174-208, 890-895) and `evidence_hashes` (file sha256[:16] of each evidence file), writes gate.json.

**Live `GET /api/v1/control/gate` = FRESHNESS RE-EVALUATION ONLY** (control_plane_api.py:187-220 → gate_evaluator.py:250-288):
- Globs `.eval/*/gate.json` and picks the NEWEST BY MTIME across ALL scopes (control_plane_api.py:200-205).
- Re-reads the recorded JSON; recomputes only live HEAD (5-second cache, control_plane_api.py:206-217) and `db_fingerprint(store)`; compares.
- If unchanged, it returns the recorded gate.json **verbatim** plus a `freshness_verified_at` stamp (gate_evaluator.py:286-288). It never re-runs any of the 52 evidence checks, never re-hashes the evidence files, and never checks tree hash / migration hash / worktree cleanliness on the live path.

## 2. What gate.json binds, and via which hashes

From `.eval/scope_v5/gate.json`:
- `source_commit` = `8e31708d584459fb38fedefe21b070bede36db57` (= HEAD, verified today). Check `gate_bound_to_head` evidence: `source_commit=8e31708d… head=8e31708d…`.
- `code_tree_hash` = `d741311d6fbe26b8` (in check `code_tree_hash_match` evidence `recorded=… current=…`) — covers ONLY `src/platform`, `web/src`, `scripts`. Docs, migrations files on disk, `.env`, and frontend build output are NOT hashed (migrations bind via DB `schema_migrations` instead).
- `migration_hash` = `64b718541ca6ee37` (check `migration_hash_match`).
- `db_fingerprint`: `scope_graph=e284c22350308ae8` (data_scope count aggregates over all registry-derived `_SCOPED_TABLES`), `event_watermark=731` (max seq of `event_envelope_v1`), `outbox_pending=0`, `projection_hash=bf175bc0…` (full sha256 from `store.rebuild_work_projection()`), `counts={business_run_v1:205, work_item_v2:244, usage_event_v2:201, recognition_task:51, survey_media_v1:28}`.
- `evidence_hashes` (sha256[:16] of file bytes): `uat_report=a32e0662b8888516` (uatv7/report.json), `issue_ledger=79700bee0254fbab` (docs/implementation/agentic-business-os-operational-scope-v5/ISSUES.md), `test_report=179aa1d81a7fbc3c`, `browser_report=71a01f2ac2b87b91`.
- `evaluator_version=3.2.0` (single-sourced at gate_evaluator.py:23).
- Only the live freshness path actually COMPARES any of these (source_commit + the 5 fingerprint keys). `evidence_hashes`, tree hash and migration hash are recorded but never compared against any prior record by any code path.

## 3. The self-compare flaw — exact location

**scripts/osv5_gate_evaluate.py:105-118**, specifically lines 116-118:
```python
head = _git_head(); tree = _tree_hash(); mig = _migration_hash(store)
...
source_commit=head, current_head=head,
recorded_tree_hash=tree, current_tree_hash=tree,
recorded_migration_hash=mig, current_migration_hash=mig,
```
The "recorded" side is computed from the SAME current tree/HEAD/migrations as the "current" side, so the three binding checks (gate_evaluator.py:305-322: `gate_bound_to_head`, `code_tree_hash_match`, `migration_hash_match`) compare freshly-computed values against themselves and pass **tautologically** at write time. Consequences:
- The recorded tree/migration hashes in gate.json describe the tree at GATE-EVALUATION time, not the tree at which UAT/test/browser evidence was generated.
- None of the evidence files themselves carries a commit/tree binding (uatv7/report.json has no source_commit field; test_report.json has none; browser_evidence.json has none), so the chain `evidence → gate.json → code` is broken at the evidence end: any code change between evidence generation and a gate re-run is invisible.
- The negative test `stale_head_binding_detected` (osv5_gate_negative.py:246-250) only exercises the case where a caller explicitly passes `source_commit="x", current_head="y"` — it proves the live freshness path works, but does not cover the self-compare in the regeneration script.
- In this cycle it happened to be harmless only by ordering discipline: evidence was generated 13:42 (UAT) → ~14:00-14:02 (browser PNG mtimes) → gate 14:14:35, all after the last code-touching commit (c957f063 at 14:03:58 added only the browser script itself; final commit 8e31708d at 14:14:15 touched only docs/, which the tree hash excludes — but which DOES include ISSUES.md, the issue ledger the gate consumes; the gate was regenerated 20 s later, so it consumed the post-commit ledger). Nothing enforces this ordering.

## 4. test_report.json — production and (non-)binding

- Content: `{"suite": "hermetic", "failed": 0, "passed": 1479, "skipped": 1, "deselected": 6, "new_tests": 32, "new_file": "tests/platform/test_osv5_import_scope.py", "baseline": "1447 passed, 1 skipped, 6 deselected", "marker": "not host_mps"}`.
- Produced from the pytest run configured in pyproject.toml:47-48 (`addopts = "-m 'not host_mps'"`), i.e. plain `pytest` for the hermetic 1479, plus `pytest -m host_mps` (6 passed) for host probes.
- **There is NO generator script**: nothing in `scripts/` writes `.eval/scope_v5/test_report.json` (grep confirms only consumers: si2/si3/si4 gate scripts for older scopes). EXECUTION-LOG T9 says it was "入账" (booked in) — it is a hand-written one-line JSON summary.
- It does **NOT bind HEAD**: no commit, no tree hash, no timestamp. The gate only checks `failed == 0` (`tests_all_passed`, gate_evaluator.py:764-780) and records the file's sha256 — so a stale report from any older commit would pass identically.

## 5. Browser evidence binding (or lack thereof)

`scripts/osv5_browser_evidence.py` drives real headless Chrome via CDP (port 9227) against the RUNNING app on 127.0.0.1:8400; per-page it records DOM assertions via `Runtime.evaluate` (row counts of `tr[data-batch-id]` vs API counts, fixture-token scans), screenshot sha256s, console errors; at capture time it also records `gate_observed` and `evaluator_version_observed` from live `/api/v1/control/gate`, and a `browser_test_run` namespace (`osv5br_20260813060026_me4xz`).
- **No source_commit / tree hash is recorded** → browser evidence is not bound to code state. It binds implicitly to the DB state at capture time (the 29/26/3 counts live in `import_batch_v1`, which is scope-covered, so a DB-level change to those rows would flip `db_fingerprint.scope_graph` and make the live gate STALE), but frontend/backend CODE changes after capture do not invalidate it.
- Notably `gate_observed` was `"STALE_GATE_EVIDENCE"` at capture time (browser_evidence.json:461) — the browser run happened before the final gate regen; the `gate_pill_live_value` check asserts the pill matches whatever the live value is, so it passed on STALE.
- The gate's consumption of browser evidence (gate_evaluator.py:782-848) checks file existence, console, viewport set {1440,1280,1024,768}, 12 required routes, import views ⊇ {operational, history}, and per-page `assertion`/object-id equality — but never screenshot content or uniqueness.

## 6. What flips the gate to STALE_GATE_EVIDENCE

**Live freshness path** (gate_evaluator.py:250-288, triggered by `/api/v1/control/gate`; also exercised by negative test 12):
1. `git rev-parse HEAD` != recorded `source_commit` (any new commit);
2. any of the 5 `db_fingerprint` keys differs from recorded: `scope_graph` (any data_scope count change in any scoped table), `event_watermark` (any new event envelope; recorded 731), `outbox_pending` (recorded 0), `projection_hash` (work-projection rebuild), `counts` (the 5 key tables);
3. recorded gate.json has no `db_fingerprint` at all;
4. recorded gate.json missing/unreadable → `BLOCKED_BY_GATE_EVIDENCE` (not STALE).
**Full-evaluation path**: the three binding checks carry `block=STALE` but can only fail if a caller passes mismatched values (the shipped script never does); also `db_fingerprint()` raising flips a READY result to STALE (gate_evaluator.py:890-902). STALE outranks every `BLOCKED_BY_*` in the priority list (gate_evaluator.py:868).
**Does NOT flip it** (gaps): uncommitted tracked-code changes (live path never checks worktree/tree hash), edits to the evidence files after gate generation (hashes are never re-compared), reopening a P0/P1 in ISSUES.md, or a test regression — each requires a manual `python3 scripts/osv5_gate_evaluate.py` re-run to surface.

## 7. Exact CLI invocations to regenerate each artifact

All from repo root `/Users/zhangweiqi/Documents/QY/项目/LLM-Image` (stack first via `bin/abos start` / verify `bin/abos status`, `bin/abos doctor`):

| Artifact | Command | Notes |
|---|---|---|
| before audit | `python3 scripts/scope_audit_v5_before.py` | read-only; needs live app for API probes; overwrites `.eval/scope_v5/before/before_audit_v5.json` |
| UAT V7 report | `python3 scripts/uatv7_rehearsal.py` | needs full stack (:8400/:8091/:8092/:8300) + `.env` `PLATFORM_ADMIN_CREDENTIALS`; check 18 restarts services (`bin/abos` semantics); writes `.eval/scope_v5/uatv7/report.json` |
| browser evidence | `python3 scripts/osv5_browser_evidence.py` | needs app on :8400 + local Google Chrome + `websockets`; spawns own Chrome on debug port 9227; writes `browser_evidence.json` + 28 PNGs; archives its fixture identities at the end |
| negative tests | `python3 scripts/osv5_gate_negative.py` | self-contained (temp DB + TestClient, no live services); exit 0 only if all 12 blocked; writes `.eval/scope_v5/gate_negative_tests.json` |
| hermetic tests | `pytest` (addopts `-m 'not host_mps'`) then `pytest -m host_mps` | results HAND-written into `.eval/scope_v5/test_report.json` (no generator) |
| gate (LAST) | `python3 scripts/osv5_gate_evaluate.py` | needs live DB + all 4 services (services_healthy probe) or it emits BLOCKED_BY_GATE_EVIDENCE; writes `.eval/scope_v5/gate.json` |

Correct order after code changes: commit → `bin/abos restart` → `pytest` → write test_report.json → `uatv7_rehearsal.py` → `osv5_browser_evidence.py` → `osv5_gate_negative.py` → `osv5_gate_evaluate.py` last (so HEAD/db fingerprint are fresh) — but note the self-compare flaw means this ordering is convention, not enforced.

## Risks
- SELF-COMPARE FLAW (P0, task #7): scripts/osv5_gate_evaluate.py:116-118 passes source_commit=head/current_head=head and recorded_tree_hash=tree/current_tree_hash=tree (same for migration) — the three binding checks (gate_evaluator.py:305-322) compare current state against itself and always pass at write time. gate.json's recorded hashes reflect gate-evaluation time, not evidence-generation time; no evidence file (uatv7 report, test_report, browser_evidence) embeds a commit/tree hash, so code drift between evidence generation and gate regeneration is undetectable. Correctness currently relies on the human discipline of running osv5_gate_evaluate.py last.
- LIVE PATH NEVER RE-VERIFIES EVIDENCE FILES: evidence_hashes (uat_report/issue_ledger/test_report/browser_report) in gate.json are recorded but never re-compared anywhere (freshness path copies them through, gate_evaluator.py:282); editing any evidence file after gate generation is invisible until a full manual re-run.
- LIVE GATE IGNORES CODE STATE SHORT OF A COMMIT: the freshness path (gate_evaluator.py:250-288) checks only HEAD string + db_fingerprint; uncommitted tracked changes, worktree dirt, tree hash and migration hash are not re-checked live (tracked_worktree_clean exists only in the full path).
- BROWSER SCREENSHOT EVIDENCE ANOMALY: the four Import Center view screenshots (osv5_import_operational/mine/history/quarantine_1440.png) are BYTE-IDENTICAL on disk (sha256 c01b52d60c2f…, 241865 bytes each) despite asserting different row counts (0/29/26/3). The gate's browser_screenshots_exist check (gate_evaluator.py:795-798) only checks presence, not distinctness — view separation is proven only by Runtime.evaluate DOM numbers, not by pixels. Likely a capture-path bug (screenshot taken before/without the tab switch rendering).
- REPORT/DOC COUNT DRIFT (task #9): EXECUTION-LOG T6 and FINAL-REPORT §51 claim '42 检查', but gate.json actually contains 52 checks; FINAL-REPORT §39 says '1440×17' screenshots vs 28 files listed. Single-source-of-truth violation in the governance docs.
- CROSS-SCOPE GATE HIJACK: live endpoint picks newest .eval/*/gate.json by mtime across all scopes (control_plane_api.py:200-205); regenerating an older scope's gate.json would silently switch the live gate's baseline.
- EVIDENCE NOT IN GIT: .eval/ is gitignored (.gitignore:20), so gate.json/evidence_hashes/source_commit strings cannot be verified from the repository alone — the audit trail lives entirely on the local machine.
- db_fingerprint() has a WRITE SIDE EFFECT (store.rebuild_work_projection() delivers outbox, gate_evaluator.py:178-184 docstring acknowledges this); every live gate poll mutates DB state, which is why outbox_pending must be read after rebuild — a fragility noted in-code but a risk for repeated-poll false-STALE if ordering ever changes.

## Open questions
- Should evidence_hashes be actively re-compared on the live path (detect post-gate tampering/editing of report files)?
- Should the tree hash cover docs/ (ISSUES.md is consumed by the gate but excluded from code_tree_hash; the final commit 8e31708d changed only docs)?
- Is the live endpoint's cross-scope mtime glob (.eval/*/gate.json) intentional, or should it pin scope_v5?
- Should test_report.json be machine-generated with a HEAD binding (the only scope without a writer script)?