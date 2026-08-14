# Agentic Business OS governance docs — Operational Scope V5 + v1–v4 rounds (data_scope model, import batch lifecycle, quarantine semantics, outstanding issues, doc templates)

## Key files
- docs/implementation/agentic-business-os-operational-scope-v5/00-LIVE-AUDIT.md — V5 independent audit: 12 reproduced issues (OSV5-001..012), baseline, backup hashes
- docs/implementation/agentic-business-os-operational-scope-v5/01-IMPORT-SCOPE-CONTRACT.md — batch=frozen execution context; migration 059; creation rules; archive guard
- docs/implementation/agentic-business-os-operational-scope-v5/02-IMPORT-IAM-AND-PRIVACY.md — endpoint permission matrix, DTO whitelist, preview redaction, new scopes
- docs/implementation/agentic-business-os-operational-scope-v5/03-EXECUTABLE-SCOPE-REGISTRY.md — Registry as executable single source of truth; validator; derived consumers
- docs/implementation/agentic-business-os-operational-scope-v5/04-HISTORICAL-RECONCILIATION.md — bind/quarantine evidence rules for the 20 historical batches
- docs/implementation/agentic-business-os-operational-scope-v5/05-GATE-3.2.md — Gate 3.2.0: 18 new checks, BLOCKED_BY_IMPORT_SCOPE_LINEAGE, negative tests
- docs/implementation/agentic-business-os-operational-scope-v5/DECISIONS.md — DEC-OSV5-001..011 (multi-customer table, quarantine scope, permission matrix, DTO whitelist)
- docs/implementation/agentic-business-os-operational-scope-v5/ISSUES.md — OSV5-001..012 all CLOSED with evidence
- docs/implementation/agentic-business-os-operational-scope-v5/FINAL-REPORT.md — 53-item closure report incl. 17 bind + 3 quarantine result and honesty boundary
- docs/implementation/agentic-business-os-operational-scope-v4/01-ROOT-CAUSE-AND-CONTRACTS.md — V4 root causes (identity lifecycle, BI physical counts, registry classification escape)
- docs/implementation/agentic-business-os-scope-integrity-v3/01-SCOPE-GRAPH-CONTRACT.md — ExecutionContext/effective-scope/fail-closed resolver contract (basis of current model)
- docs/implementation/agentic-business-os-uat-scope-isolation-v2/01-EXECUTION-SCOPE-CONTRACT.md — original data_scope domain and single-source-of-truth decision
- docs/implementation/agentic-business-os-uat-contract-correction-v1/01-ROOT-CAUSE-AND-CONTRACTS.md — RC-1..RC-6 (photo contract, agent usage chain, real parallel branches, rate limit)
- docs/implementation/agentic-business-os-uat-final-consistency-v1/02-EVIDENCE-DRIVEN-GATE.md — evaluate_gate_from_evidence contract; gate.json shape; BLOCKED_BY_* rule
- src/platform/import_center.py — quarantine write-escape (_guard_active:577), users_v1 initial password (~913-921), commit_json persistence (:1208)
- src/platform/gate_evaluator.py — STALE_GATE_EVIDENCE (:20), freshness re-evaluation (:243-286), db_fingerprint binding
- scripts/scope_reconcile_imports_v5.py — historical reconciliation; contains no import_batch_customer_scope_v1 writes (lineage gap)
- .eval/scope_v5/gate.json — current machine gate: READY_FOR_REAL_DATA_UAT, 3.2.0, 52 checks (report says 42), bound to HEAD 8e31708d

## Findings
## Repo state
Project root `<legacy-workspace>`, branch `feat/nextgen-training-cycle-v2`, HEAD `8e31708d` = OSV5 T10 governance-closure commit; tracked tree clean. All V5 issues OSV5-001…012 marked CLOSED; current `.eval/scope_v5/gate.json` = READY_FOR_REAL_DATA_UAT, evaluator 3.2.0, bound to source_commit 8e31708d with db_fingerprint.

## 1. data_scope model (operational / uat_fixture / quarantine)
- V2 (uat-scope-isolation-v2, `01-EXECUTION-SCOPE-CONTRACT.md`): introduced `ExecutionScopeV1` in `src/platform/scope.py` as single source of truth; domain `operational | uat_fixture | demo_fixture | system | archived`; server-side ScopeResolver only (client may not self-assert operational); resolution order explicit Test Run → parent Run → parent WorkItem → `md_customer_v1` → default operational; runtime `LIKE 'uat%'` name matching banned.
- V3 (scope-integrity-v3, `01-SCOPE-GRAPH-CONTRACT.md`): `ExecutionContext` replaces ExecutionScopeV1 (alias kept). Fail-closed resolver: `test_run_id` must exist in `uat_test_run_v1` with status='current' + matching actor/customer set, else ScopeViolation. Effective scope = row's own columns ⊕ parent-chain derivation; operational surfaces show only effective=operational; fixture history only in Test & Evidence Center. Same-transaction scope writes; no INSERT OR REPLACE of namespaces; Usage/Evidence append-only, corrections via `scope_attribution_ledger_v1`.
- V4: migration 057 (IAM provenance), 058 (BI metric/dashboard + import_batch_v1 gained data_scope/test_run_id); BI on `bi_effective_counts` effective basis.
- V5: DEC-OSV5-002 adds **`quarantine`** to DATA_SCOPES — fail-closed destination for undeterminable batches; must not count as operational in API/BI/Gate; visible only to admin/auditor in quarantine view. Live import-batch values: operational, uat_fixture, quarantine; archiving handled via lifecycle columns (`visibility='history'` + `archived_at`), not a scope value.

## 2. Import batch lifecycle contract (V5 `01-IMPORT-SCOPE-CONTRACT.md` + `02-IMPORT-IAM-AND-PRIVACY.md`)
Batch = frozen execution context. Migration 059: import_batch_v1 + `visibility` (default 'current'), `archived_at`, `source` ('import_center'), `correlation_id` (data_scope/test_run_id pre-existing); new table `import_batch_customer_scope_v1` (batch_id, customer_id, project_id nullable, scope_source, authorization_decision, created_at; UNIQUE(batch_id, customer_id, COALESCE project '')). DEC-OSV5-001: no single customer_id column — multi-customer via association table.
Creation rules: operational ⇒ test_run_id empty + template permission matrix + per-row customer auth, whole-batch fail-closed 403 with nothing persisted (DEC-OSV5-004). UAT ⇒ explicit test_run_id; `ScopeResolver.assert_test_run_current` fail-closed (archived/missing → 409); data_scope=uat_fixture same transaction; "operational now, patch later" forbidden. Global templates: users/roles/memberships→iam.manage, rate card→finance.manage, knowledge base→master.manage, surveys→survey.manage; missing customer_id may not bypass auth. Committed objects inherit batch scope same txn. Archived batches 409 on re-dry-run/commit; replay idempotent.
IAM: all Import endpoints through IAMService.authorize + visible_customers; list default = effective operational ∩ caller customer scope; views `view=mine|history|quarantine`; `include_fixture=1` platform_admin/owner/auditor only. Detail = DTO whitelist (batch_id/template_id/filename/actor/status/row_count/data_scope/test_run_id/customer_scopes/created_at/updated_at/dry_run_summary/error_count/commit_summary) — no raw payloads. Raw rows only via /preview (creator or data.import.audit, redacted, ≤50). New scopes finance.manage + data.import.audit; new role auditor. read_only → 403 everywhere on Import (DEC-OSV5-011).

## 3. Quarantine semantics as defined
- DEC-OSV5-002/008: undeterminable batches fail-closed to quarantine; stop counting as operational; admin/auditor-only visibility. Evidence priority: mapping_json customers ↔ test_run customer set > commit receipts ↔ test run > time window; filenames/UAT prefixes diagnostic only (red line 4).
- Reconciliation (`04-HISTORICAL-RECONCILIATION.md`, `scripts/scope_reconcile_imports_v5.py`): read-only plan with 5 evidence classes (mapping↔test-run customers, receipts↔test run, imported objects' own scope, created_at↔time window, audit/evidence links); unique → bind (uat_fixture+test_run_id), else quarantine. Apply is idempotent, before/after hashes, per-batch rows in `scope_backfill_audit_v1`, deletes nothing.
- Applied: 20 historical batches → 17 bind (uat_fixture_v3 ×8, uatv2 ×6, uatv3 ×3) + 3 quarantine (imp-8e4f53455eaa / imp-9a8028ec9733 / imp-bf333d101db6 — customers uat-cust-a/b and uatv2…l16gw2 matched no registered Test Run customer set). operational 20→0. Disposition of quarantined batches = manual admin adjudication (keep or delete via approval matrix data.delete) per FINAL-REPORT §52; no state machine exists.

## 4. What V5 claimed to fix (OSV5-001…012, all CLOSED in ISSUES.md)
- 001 (P0): 20 historical UAT batches all operational polluting API/BI/Gate → reconciled, operational=0.
- 002 (P0): creation chain lacked ExecutionContext/test_run_id (upload/_save_batch unscoped; V4's "import closed loop" had no end-to-end evidence) → migration 059 + same-txn uat_fixture; UAT V7 23/23 real multipart.
- 003 (P0): Import API only `require_principal` (read_only could list/detail/dry-run/commit) → template matrix + authorize_batch + per-customer fail-closed.
- 004 (P0): detail returned raw mapping/dry_run/error/commit JSON → DTO whitelist + authorized redacted preview.
- 005 (P0): parallel lists Registry 125 / scanner `_SCOPED_TABLES` 23 / archiver `_SCOPED_DOMAIN_TABLES` 18, import_batch_v1 in neither → all Registry-derived (leak_scan_tables/archivable_tables/ARCHIVE_HANDLERS).
- 006 (P0): fake Registry semantics (35 fake pks / 5 fake customer_cols / 115 phantom tenant_id defaults) → typed declarations (composite:/none/not_applicable) + validate_registry zero errors.
- 007 (P1): Import Center UI showed no filename/scope/test_run → 4 views rebuilt, object-level DOM↔API reconciliation 29/29.
- 008 (P1): archiver/Test Center missed import_batch_v1 → import archive handler + count_tables.
- 009 (P1): Gate data-products reconciled customer only → data_products_all_effective_consistent across 8 products; "effective ≤ physical" weak condition banned.
- 010 (P1): version drift (docs Gate 3.1 vs code/evidence 3.0.0) → EVALUATOR_VERSION="3.2.0" single-sourced + evaluator_version_consistent check.
- 011 (P2): lazy session deletion → purge_expired_sessions (login-triggered, expiry-only, audited, bill identity exempt).
- 012 (P2): scope_audit_v4.py stale claims → annotated + 7-dimension scope_audit_v5.py.
Plus: Gate 3.2 with 18 new checks (import_batch_* ×9, registry_* ×5, data_products_all_effective_consistent, browser_import_current_history_separated, uat_import_lineage_complete, evaluator_version_consistent); new block state BLOCKED_BY_IMPORT_SCOPE_LINEAGE; 12 negative tests all blocked; UAT V7 first-run 23/23 (namespace uatv7_20260813053942_kh463m); hermetic 1479 passed; backup platform_pre_scope_v5_20260813T124408.sqlite two-way integrity ok; no merge/push/deploy/production-switch/training.

## 5. Outstanding issues (V5 claims zero open; code inspection at HEAD + current-round work ledger say otherwise)
- Quarantine write escape (P0): `_guard_active` import_center.py:577-583 blocks only `visibility=='history'` or `data_scope in ("archived",)` — quarantined batches (quarantine/current) pass and can still be dry-run/commit/replayed. Quarantine enforced only in read paths (list view filters import_center.py:1094-1128) and Gate.
- Initial password persistence (P0): import_center.py ~913-921, users_v1 template generates plaintext `temp_pw="Init-"+secrets.token_hex(4)`, returned as `initial_password_once` in commit receipt; iam.py:167 hashes for iam_principal_v1 but plaintext persists in `import_batch_v1.commit_json` (import_center.py:1208), contradicting its own comment "不写明文入库/日志".
- Batch–customer lineage gap (P1): scope_reconcile_imports_v5.py has zero references to import_batch_customer_scope_v1 — the 17 bound historical batches got data_scope/test_run_id but no customer-scope lineage rows; DTO customer_scopes empty for history; only UAT V7 creation-path batches have lineage.
- Gate staleness closure (P0): gate_evaluator.py:20 STALE_GATE_EVIDENCE + freshness re-eval at :243-286 bound to source_commit + db_fingerprint (since Gate 3.0/V3); current-round ledger flags the detection→re-evaluation loop as unclosed.
- Report single-source drift (P1): FINAL-REPORT §31 + EXECUTION-LOG say Gate 3.2 = 42 checks; `.eval/scope_v5/gate.json` actually holds 52.
- Parallel-workflow timeout race (P1): tests/platform/test_uatcc_parallel_engine.py:126 test_branch_timeout (legacy of contract-correction-v1 RC-3 parallel contract).
- P2: page-navigation scroll continuity (Import Center → System Admin); quarantine manual-adjudication state machine (API/perms/audit/UI) missing.

## 6. Doc templates used (consistent across all rounds)
- `00-LIVE-AUDIT.md`: start-of-round independent audit — baseline table (branch/HEAD/services/integrity/row counts), reproduced P0/P1/P2 with structured evidence, backup sha256 + two-way integrity.
- Numbered contracts `01-…`…`07-…`: binding specs written before implementation (root cause+contracts, IAM/privacy, Registry, reconciliation, Gate, UAT protocol, browser acceptance).
- `READING-LIST.md` (V4/V5): mandatory pre-work table `| # | 文档/代码 | 状态 | 关键记录 |`.
- `AGENT-EXECUTION-PROMPT.md`: the non-stop loop (audit → red repro → contracts → small-step impl → negatives → browser → DB reconcile → Gate recompute → regression → docs → final report) + red lines.
- `STATUS.md`: phase ledger T0…T10 + Gate posture + honesty boundary (machine Gate only outputs READY_FOR_REAL_DATA_UAT or BLOCKED_*; no ACCEPTED/COMPLETE/PRODUCTION_READY before user's real-data UAT).
- `ISSUES.md`: `| ID | 级别 | 状态 | 摘要 | 复现证据 | 根因 | 修复 |` (V5 short variant), round-prefixed IDs SI2-/SI3-/SI4-/OSV5-, append-only.
- `DECISIONS.md`: `| ID | 决策 | 理由 |` (DEC-*-NNN).
- `LIST.md`: work-item ledger `| ID | 阶段 | 事项 | 状态 | 证据 |`.
- `EXECUTION-LOG.md`: chronological narrative incl. honest registrations (e.g. V5 T1: 27 failed / 5 honestly-green red tests with per-case reasons).
- `FINAL-REPORT.md`: numbered checklist (V4 47 items / V5 53 items): HEAD/commit chain, backups+hashes, red tests, issue closures, Gate checks/negatives, UAT namespace+IDs, browser role×viewport matrix, hermetic/MPS/tsc/build, integrity, migrations, restart, explicit no-merge/no-deploy/no-production/no-training declarations, open items, user's single next step, absolute evidence paths.
- Recurring red lines: backup + two-way integrity before DB change; never delete history (append-only/versioned, quarantine instead of delete); no reset --hard/add -A/merge/push/deploy/production switch/training; no filename-based runtime scope decisions; red test before fix with round-numbered commits; Gate only via evaluate_gate_from_evidence.

## Cross-round lineage
Gate: 2.1 → 3.0 (V3: evidence-driven + db fingerprint freshness + STALE_GATE_EVIDENCE) → 3.1 (V4: 34 checks, READY bound final HEAD+DB fingerprint) → 3.2.0 (V5). UAT protocols: V2→V3→V4→V5→V6 (V4 round, 57/57, 30 id keys) → V7 (V5 round, real multipart Import API, 6 required import id keys). Migrations: 047 → 051 → 057 → 058 → 059.

## Risks
- Quarantine write escape (P0): src/platform/import_center.py:577-583 `_guard_active` blocks only visibility=='history' or data_scope in ('archived',); the 3 quarantined batches (data_scope='quarantine', visibility='current') pass the guard and can be dry-run/commit/replayed despite DEC-OSV5-002's isolation intent.
- Initial password plaintext persistence (P0): src/platform/import_center.py ~913-921 returns `initial_password_once` in the commit receipt which is persisted into import_batch_v1.commit_json (:1208) — the hash-only storage in iam.py:167 is undermined; contradicts the inline comment claiming zero plaintext persistence.
- Batch–customer lineage gap (P1): scripts/scope_reconcile_imports_v5.py never writes import_batch_customer_scope_v1; the 17 bound historical batches lack customer-scope lineage rows, so batch DTO customer_scopes and any lineage-based authorization/audit are empty for history.
- Gate staleness closure incomplete (P0): STALE_GATE_EVIDENCE machinery exists (gate_evaluator.py:20,243-286) but the detect→re-evaluate loop is flagged unfinished in the current work ledger; gate.json's db_fingerprint goes stale on any live write.
- Report-vs-evidence drift (P1): FINAL-REPORT §31 and EXECUTION-LOG state 42 Gate checks while .eval/scope_v5/gate.json contains 52 — same drift class V5 itself cited against V4 (OSV5-010).
- Parallel-workflow timeout race (P1): tests/platform/test_uatcc_parallel_engine.py:126 test_branch_timeout flagged in current work ledger; branch timeout/cancel semantics date to contract-correction-v1 RC-3.
- V5 ISSUES.md declares all P0/P1/P2 CLOSED and §50 '无' — the governance docs overstate closure relative to code state at HEAD 8e31708d; next round must re-audit rather than trust the V5 report (which is itself the V5 methodology lesson).

## Open questions
- No V6 governance directory exists yet — the current round is still at baseline setup (task ledger #1 in_progress), so the outstanding issues currently live only in the work ledger + code, not in governance docs.
- Is gate.json's 52 checks vs the documented '42' a post-FINAL-REPORT regeneration or a genuine undercount? Needs evaluator source reconciliation.
- Quarantine disposition (keep vs delete via approval matrix data.delete) for the 3 quarantined batches has no defined adjudication path in code; FINAL-REPORT §52 delegates it to humans.
- Whether commit_json containing initial_password_once is reachable via /preview or errors.csv paths for auditor/creator roles (would widen the plaintext-password exposure beyond raw DB access).
- Whether the current-round instructions (not in docs yet) redefine quarantine semantics beyond V5's read-only isolation.