# OSV5 scope registry vs final-report drift (gate check count, registry count, UAT namespace/batch IDs)

## Key files
- src/platform/scope_registry.py — registry single source of truth: SCOPE_REGISTRY dict (126 entries), registry_coverage(), validate_registry(), ARCHIVE_HANDLERS (20), archive_handler_for()
- src/platform/gate_evaluator.py — gate evaluation; checks built dynamically via chk() (append at :295); imports archive_handler_for at :480-483; 6 registry_* checks
- scripts/osv5_gate_evaluate.py — writes .eval/scope_v5/gate.json (GATE_OUT at :22)
- scripts/uatv7_rehearsal.py — 23-check UAT V7 rehearsal; check 15 archives namespace mid-run (:288), writes .eval/scope_v5/uatv7/report.json (:36, :389)
- .eval/scope_v5/gate.json — live machine gate: 52 checks, READY_FOR_REAL_DATA_UAT, source_commit 8e31708d, evaluated_at 2026-08-13T14:14:35+0800
- .eval/scope_v5/uatv7/report.json — live UAT report: namespace uatv7_20260813054236_t8ribm, total=23 failed=0, batches imp-8794cb38594c/imp-13bff4e623a0/imp-6411b356cfbf
- .eval/scope_v5/before/before_audit_v5.json — before-state audit; p0005_parallel_lists.scope_registry=125
- docs/implementation/agentic-business-os-operational-scope-v5/FINAL-REPORT.md — the stale report: §26 (125 tables), §31/:154 (42 checks), §33/:161-162 (kh463m + 首次 23/23 + failed-run admission), §34/:166-168 (old batch IDs), §51/:232 (42 checks)
- docs/implementation/agentic-business-os-operational-scope-v5/EXECUTION-LOG.md — :65 (42 checks, T6 historical), :70-72 (首跑 23/23 + debug-leftover namespace admission)
- docs/implementation/agentic-business-os-operational-scope-v5/READING-LIST.md — :16 claims scope_registry.py has 125 items (stale)
- docs/implementation/agentic-business-os-operational-scope-v5/00-LIVE-AUDIT.md — :48 SCOPE_REGISTRY=125 (before-state, P0-005)
- .platform/platform.sqlite — live DB: uat_test_run_v1 holds all 3 uatv7 runs; import_batch_v1 holds all 6 batch IDs

## Findings
## 1. Registry definition / validation (how it actually works)

**`src/platform/scope_registry.py`** is the machine single source of truth (docstring :1-22):
- `SCOPE_REGISTRY` dict defined at **:52**; entry helper `_e()` at :36-49 (typed declarations: pk/tenant/customer/project/scope_cols/derive/parent/gate/archive_handler).
- **Current count: `len(SCOPE_REGISTRY) == 126`** (verified by direct import). Includes `"sqlite_sequence"` at **:375** (`global_configuration`), which `registry_coverage()` treats as optional (subtract at :630/:634). Real covered tables in live DB = **125**, coverage 100.0%, `validate_registry()` problems = [] (verified live against `.platform/platform.sqlite` read-only).
- `registry_coverage(conn)` at **:626-642** computes missing/unknown/coverage vs `sqlite_master`; fail-closed gate block `BLOCKED_BY_SCOPE_REGISTRY` (docstring :5-6).
- `validate_registry(conn)` at **:728-777**: machine-checks pk (incl. `composite:`/`none`), tenant/customer/project cols, scope cols, parent edges, archive-handler executability, leak_scan-requires-data_scope.
- Executable layer (OSV5 T4, :645-725): `ARCHIVE_HANDLERS` (:685-709, 20 handlers), `archive_handler_for()` (:712-713), `archivable_tables()` (:716), `leak_scan_tables()` (:721). Bidirectional binding enforced at :782-785.
- Gate consumption: `src/platform/gate_evaluator.py:480-483` imports `archive_handler_for`; live gate.json carries 6 registry checks: `scope_registry_full` (coverage=100.0% missing=[]), `registry_schema_valid` (problems=[]), `registry_runtime_scanner_complete`, `registry_archive_handler_complete` (handlers=20 bad=[]), `registry_operational_query_complete`, `registry_parent_edges_valid` — all ok.

## 2. How counts are computed (nothing hardcoded)

- **Gate check count**: `evaluate_gate()` builds `checks` dynamically; every `chk(...)` call (append at `gate_evaluator.py:295`) adds one; many are conditional on evidence availability. At T6 (commit `72cbd39e`, evidence incomplete, gate=BLOCKED_BY_P0) the run produced **42** checks. The final regeneration at T10 (same evaluator code — `git log 72cbd39e..HEAD -- gate_evaluator.py` is empty) produced **52** checks because all evidence (browser, uatv7, tree/migration hashes) was present. `scripts/osv5_gate_evaluate.py` writes `.eval/scope_v5/gate.json` (:22).
- **Registry count**: purely `len(SCOPE_REGISTRY)` / `registry_coverage()` against live schema. Growth during the round: before-state `before_audit_v5.json → p0005_parallel_lists.scope_registry = 125`; commit `72cbd39e` message records "registered import_batch_customer_scope_v1" → **126**.

## 3. Live truth (verified today)

- `.eval/scope_v5/gate.json`: `gate=READY_FOR_REAL_DATA_UAT`, **checks=52**, `source_commit=8e31708d`, `evaluated_at=2026-08-13T14:14:35+0800`.
- `.eval/scope_v5/uatv7/report.json`: `namespace=uatv7_20260813054236_t8ribm`, `generated_at=2026-08-13T05:42:48Z`, `total=23 failed=0`, `ids`: test_run=uatv7_20260813054236_t8ribm, import_batch_customer=**imp-8794cb38594c**, import_batch_project=**imp-13bff4e623a0**, import_batch_address=**imp-6411b356cfbf**.
- Live DB `uat_test_run_v1` holds **three** uatv7 runs: `uatv7_20260813053847_jiv6d6` (created 05:38:47, archived 05:39:33), `uatv7_20260813053942_kh463m` (created 05:39:42.806, archived 05:39:42.893), `uatv7_20260813054236_t8ribm` (created 05:42:36). All six batch IDs exist in `import_batch_v1` (all uat_fixture/visibility=history).

## 4. The stale report: `docs/implementation/agentic-business-os-operational-scope-v5/FINAL-REPORT.md`

- **:154 (§31)** — "总检查数 42。" (drift: live gate.json = 52)
- **:232 (§51 "最终机器 Gate")** — "`.eval/scope_v5/gate.json`（scripts/osv5_gate_evaluate.py 在收尾 HEAD 上生成；42 检查；机器评估，非手写）" — the file it points to actually contains **52** checks; the text was never updated after the T10 regeneration.
- **:132 (§26)** — "125 表类型化声明" describes the AFTER-state; actual `len(SCOPE_REGISTRY)` is now **126**.
- **:161-162 (§33)** — cites namespace `uatv7_20260813053942_kh463m（首次 23/23；报告 .eval/scope_v5/uatv7/report.json…）` — but the report.json on disk is the **t8ribm** run; `kh463m` appears nowhere in that file or any other artifact (repo-wide grep finds it only in FINAL-REPORT.md itself).
- **:166-168 (§34)** — cites `imp-2b0fa9391e30 / imp-abd5c30ec408 / imp-3ba7292382da` (the kh463m-run batches); live report.json ids are `imp-8794cb38594c / imp-13bff4e623a0 / imp-6411b356cfbf`.

Secondary stale mentions:
- `READING-LIST.md:16` — "src/platform/scope_registry.py | READ | 125 项" (stale: 126).
- `00-LIVE-AUDIT.md:48` — "SCOPE_REGISTRY=125 项" (before-state, P0-005; accurate as history).
- `EXECUTION-LOG.md:65` — "osv5_gate_evaluate.py：42 检查" (T6 log entry; acceptable as history, but is the origin of the number the FINAL-REPORT propagated as final).
- No document anywhere states **52** — there is no human-readable projection of the final gate state.

## 5. "首次 23/23" claim vs contradictory failed-run evidence

Claim locations: `FINAL-REPORT.md:161`（"首次 23/23"）, commit `f75ef79d` message ("UAT V7 first-run 23/23"), `EXECUTION-LOG.md:70`（"uatv7_rehearsal.py：首跑 23/23"）.

Contradictions:
1. **Self-contradiction in the same section**: `FINAL-REPORT.md:162` continues "…首次失败运行与遗留 namespace 已归档" — explicitly admits a *first failed run* existed, two lines after claiming "首次 23/23".
2. `EXECUTION-LOG.md:71-72` admits "首次运行前的一次脚本调试遗留 namespace 已归档（诚实登记）".
3. **DB evidence**: `uat_test_run_v1` contains `uatv7_20260813053847_jiv6d6` created 05:38:47 (55 s before kh463m), ran ~46 s, then archived — a real earlier attempt. So kh463m was at best the **second** uatv7 run, and t8ribm (the run whose report.json survives) the **third**. "首次" is factually wrong.
4. **Unverifiable kh463m success**: kh463m's row was archived 87 ms after creation and no report artifact for kh463m exists anywhere (the file FINAL-REPORT cites as its evidence belongs to t8ribm). The "kh463m = 首次 23/23" claim has no surviving machine evidence; the only surviving 23/23 report is t8ribm's.

## 6. Drift summary table

| Item | Report claim (FINAL-REPORT.md) | Live truth | Verdict |
|---|---|---|---|
| Gate checks | 42 (:154, :232) | 52 (.eval/scope_v5/gate.json) | stale |
| Registry size | 125 (:132; READING-LIST:16) | 126 entries / 125 tables | stale |
| UAT namespace | kh463m (:161) | t8ribm (report.json) | stale + wrong-file evidence |
| Batch IDs | imp-2b0f…/imp-abd5…/imp-3ba7… (:166-168) | imp-8794…/imp-13bf…/imp-6411… (report.json ids) | stale |
| "首次 23/23" | :161 + commit f75ef79d | ≥2 earlier runs in DB (jiv6d6 ran 46s; kh463m archived +87ms); :162 admits failed run | contradicted |

## Risks
- FINAL-REPORT.md:232 (§51 '最终机器 Gate') asserts gate.json was generated '在收尾 HEAD 上' with '42 检查', but the file on disk has 52 checks — the report misdescribes its own cited machine evidence, violating the round's T10 lessons 'single-source gate version' and 'structured-evidence reconciliation' (commit 8e31708d).
- FINAL-REPORT.md:161-168 cites namespace uatv7_20260813053942_kh463m and batch IDs imp-2b0fa9391e30/imp-abd5c30ec408/imp-3ba7292382da while pointing at .eval/scope_v5/uatv7/report.json, which contains a different namespace (uatv7_20260813054236_t8ribm) and different batch IDs (imp-8794cb38594c/imp-13bff4e623a0/imp-6411b356cfbf). Any auditor reconciling report → evidence file will hit dead IDs; kh463m appears nowhere else in the repo (grep across *.json/*.md/*.py finds it only at FINAL-REPORT.md:161).
- FINAL-REPORT.md:161 claims '首次 23/23' while FINAL-REPORT.md:162 admits '首次失败运行与遗留 namespace 已归档' and EXECUTION-LOG.md:71-72 admits a pre-run debug-leftover namespace; live DB (uat_test_run_v1) proves an earlier run uatv7_20260813053847_jiv6d6 (created 05:38:47, archived 05:39:33). 'First-run success' is false; kh463m was run #2 and its claimed 23/23 has no surviving report artifact (its row was archived 87 ms after creation).
- FINAL-REPORT.md:132 ('125 表类型化声明') and READING-LIST.md:16 ('125 项') are stale: len(SCOPE_REGISTRY)=126 (verified by import; +1 during the round — commit 72cbd39e registered import_batch_customer_scope_v1; before_audit_v5.json p0005_parallel_lists.scope_registry=125).
- No document reflects the final 52-check gate (repo-wide grep for '52' + 检查/check in the v5 docs returns nothing), so the human-readable layer has no correct projection of the final machine gate — the exact 'parallel list' failure mode OSV5-005 was supposed to abolish reappears at the report layer.
- 00-LIVE-AUDIT.md:48 'SCOPE_REGISTRY=125 项' is historically accurate (before-state) but sits in a file named LIVE-AUDIT with no as-of marker, inviting reuse as current truth.

## Open questions
- Did kh463m actually complete 23/23, or was it aborted (archived +87 ms after creation)? No report artifact survives; only FINAL-REPORT's prose claims it.
- Was the T10 gate.json regeneration (evaluated_at 2026-08-13T14:14:35+0800) intentionally post-FINAL-REPORT-text, i.e. did the author know §31/§51's '42' was stale when committing 8e31708d?
- Should 00-LIVE-AUDIT.md:48 and READING-LIST.md:16 be annotated as before-state snapshots rather than corrected (they describe the audit moment), versus FINAL-REPORT §26/§31/§51 which describe the final state and must be fixed?
- Which entry made the registry 126 — sqlite_sequence was presumably pre-existing; confirm import_batch_customer_scope_v1 (per commit 72cbd39e message) is the round's addition before correcting the '125' claims.