# Import Center pipeline (src/platform/import_center.py + api/import_api.py): full map of upload/dry-run/commit, data_scope enforcement, importer registry, payload storage, audit/evidence, quarantine handling — and the confirmed service-layer gap that lets data_scope=quarantine batches execute dry-run/commit writes

## Key files
- src/platform/import_center.py — Import Center domain service: templates registry, upload/dry_run/commit, _guard_active, authorize_batch, payload persistence (the vulnerable layer)
- src/platform/api/import_api.py — FastAPI routes for upload/list/detail/preview/dry-run/commit/errors.csv; no scope check at route level
- src/platform/scope.py — DATA_SCOPES incl. 'quarantine', ScopeResolver/ScopePolicy, ExecutionContext, scoped-create helpers
- src/platform/scope_registry.py — registry entries for import_batch_v1, archive handlers (_archive_import_batch)
- src/platform/data/store.py — import_batch_v1 schema + migrations (data_scope/visibility columns), emit_event (EventEnvelope+outbox), insert_evidence_bundle
- scripts/scope_reconcile_imports_v5.py — the script that created the 3 quarantine batches (sets data_scope='quarantine' but leaves visibility='current')
- src/platform/api/app.py — ImportCenter wiring (lines 143-155)
- src/platform/iam.py — IAMService.audit/authorize/visible_customers used by authorize_batch
- src/platform/field_ops.py — add_address/add_employee: no scope parameters (commit write sinks)
- web/src/pages/ImportCenter.tsx — UI: dry-run/commit buttons rendered regardless of data_scope
- tests/platform/test_osv5_import_scope.py — OSV5 red tests; covers quarantine creation (r03) and archive re-commit refusal (r21) but NOT quarantine re-commit refusal
- src/platform/gate_evaluator.py — import lineage gate checks (~449-475); treats quarantine as legal scope value, no operation blocking

## Findings
## 1. Architecture overview

Single shared Import Center for all modules. Stack:

- **API layer**: `src/platform/api/import_api.py` — FastAPI router built by `create_import_router(center, auth)`; wired in `src/platform/api/app.py:143-155` (`ImportCenter` instantiated with `bundle.store, iam, master (MasterDataService), survey, field_ops, finance`).
- **Domain service**: `src/platform/import_center.py` — class `ImportCenter` (line 319). State machine: `uploaded → parsed → mapped → validated → dry_run_passed → awaiting_approval → committed → reconciled` (+ failures), `STATUSES` at line 313.
- **Scope system**: `src/platform/scope.py` (`DATA_SCOPES = ("operational", "uat_fixture", "demo_fixture", "system", "archived", "quarantine")` line 23; `ScopeResolver`, `ScopePolicy`, `ExecutionContext`), `src/platform/scope_registry.py` (registry entries + archive handlers).
- **Persistence**: `src/platform/data/store.py` — table `import_batch_v1` (schema `_M042`, line ~1826), scope columns added in migrations at lines 2221-2222 (`data_scope`, `test_run_id`) and 2228+ (`visibility`, `archived_at`, `source`, `correlation_id`, `import_batch_customer_scope_v1`).
- **Frontend**: `web/src/pages/ImportCenter.tsx` (four views: operational/mine/history/quarantine, line 33-38).

## 2. API routes (api/import_api.py)

| Route | Handler | Lines |
|---|---|---|
| GET `/api/v1/import/templates` | `templates` | 39-43 |
| GET `/api/v1/import/templates/{tid}/download` | `download` | 45-58 |
| POST `/api/v1/import/upload` | `upload` (multipart, 20MB limit, rate-limit `import.upload`) | 60-82 |
| GET `/api/v1/import/batches` (`view=operational|mine|history|quarantine`, `include_fixture`) | `batches` | 84-96 |
| GET `/api/v1/import/batches/{id}` | `batch` (detail DTO) | 98-108 |
| GET `/api/v1/import/batches/{id}/preview` | `preview` (creator/platform/`data.import.audit` only) | 110-124 |
| POST `/api/v1/import/batches/{id}/dry-run` | `dry_run` | **126-135** |
| POST `/api/v1/import/batches/{id}/commit` | `commit` (rate-limit `import.commit`) | **137-148** |
| GET `/api/v1/import/batches/{id}/errors.csv` | `errors_csv` | 150-169 |

dry-run/commit handlers just call `center.dry_run(...)`/`center.commit(...)` with actor/role; **they perform no data_scope check themselves** — all guard responsibility is delegated to the service.

## 3. Importer registry — ALL 14 template ids

`TEMPLATES` dict, `import_center.py:95-310`: `customers_v1`, `projects_v1`, `skus_v1`, `stores_addresses_v1`, `employees_v1`, `users_v1`, `roles_permissions_v1`, `memberships_v1`, `survey_definition_v1`, `survey_questions_v1`, `survey_logic_v1`, `route_constraints_v1`, `usage_rate_cards_v1`, `knowledge_documents_v1`.

- Capability matrix `TEMPLATE_SCOPE` (lines 34-49): master.manage / iam.manage / survey.manage / finance.manage.
- Customer column map `TEMPLATE_CUSTOMER_COL` (lines 52-63).
- Row classification (`_classify`, 646-745) by natural key → insert/skip/conflict against live tables.
- Row writers (`_commit_row`, 847-980): delegate to `self.master.create_customer/create_project/create_sku/add_alias`, `self.field_ops.add_address/add_employee`, `self.iam.create_principal/create_custom_role/grant`, `self.survey.create_draft/update_draft`, `self.finance.new_rate_card_version`, or direct SQL for route constraints/knowledge docs/rate cards. Batch aggregation flush in `_flush_survey_rows` (982-1048).

## 4. Where data_scope is read and enforced

- **upload()** `import_center.py:456-502`: `data_scope = "operational"` default (line 469); if `test_run_id` given → `ScopeResolver.assert_test_run_current` fail-closed (scope.py:155-172) then `data_scope = "uat_fixture"` (470-473). Saved via `_save_batch` (1169-1197).
- **list_batches()** (1086-1141): default view = effective operational only; `view=quarantine` requires platform actor or `data.import.audit` (1094-1104); `view=history` similarly gated.
- **_guard_active()** (577-583) — the ONLY write-path scope guard:
```python
def _guard_active(self, b: dict) -> None:
    """OSV5：已归档批次不得再次 dry-run/commit（409）。"""
    if b.get("visibility") == "history" or \
            b.get("data_scope") in ("archived",):
        raise ImportError_(...)
```
- **commit scope inheritance** (797-799 + `_inherit_batch_scope` 819-845): only fires when `b.data_scope == "uat_fixture" and b.test_run_id`.
- Gate checks in `gate_evaluator.py:449-475` treat `quarantine` as a legal scope value but only count lineage leaks; they do not block batch operations.
- Registry entry `scope_registry.py:395-404` documents "history/quarantine 需授权" for *listing* only; archive handler `_archive_import_batch` (~line 663) sets `visibility='history'` only for test-run archival.

## 5. CRITICAL — the quarantine write-escape (vulnerable path)

**There is NO data_scope guard at the service layer for dry-run/commit. `quarantine` passes everything.** Exact chain:

1. `POST /batches/{id}/dry-run` → `import_api.py:126-135` → `ImportCenter.dry_run` (`import_center.py:546-575`):
   - `_must(batch_id)` (546) — plain lookup, no scope filter.
   - `self._guard_active(b)` (549) — only blocks `visibility=='history'` or `data_scope=='archived'`. Quarantine batches have `visibility='current'` (the reconcile script never sets visibility, see §8) and `data_scope='quarantine'` ≠ `'archived'` → **passes**.
   - `authorize_batch(actor, session_role, b, write=True)` (551) — passes for the batch creator (line 421-422 `if actor == batch.get("actor"): return`) and for admin/owner/platform_admin (`_platform_actor`, 385-389). The three quarantine batches have **zero rows in `import_batch_customer_scope_v1`** (created before OSV5), so the customer-set path is empty; non-creators need `data.import.audit`, platform roles pass unconditionally.
   - Then rows are re-validated/classified and `_update_batch` writes `status='dry_run_passed'` + `dry_run_json` (570-574) — mutating a quarantined batch.

2. `POST /batches/{id}/commit` → `import_api.py:137-148` → `ImportCenter.commit` (`import_center.py:749-817`):
   - Same `_guard_active` + `authorize_batch` (752-753).
   - Status gate (754): `if b["status"] not in ("dry_run_passed", "committed")` — **accepts `committed`**, so already-committed quarantine batches can be re-committed with no re-dry-run.
   - `_commit_row` (778 → 847-980) calls domain services with **no scope context**: `master.create_customer(...)` is invoked without `test_run_id`, `field_ops.add_address(customer_id=..., raw=..., actor=...)` has no scope parameter at all (field_ops.py:222-234). Rows land in `md_customer_v1`/`geo_address_v1`/`iam_principal_v1` etc. with schema-default `data_scope='operational'`.
   - `_inherit_batch_scope` (797-799) is skipped because `data_scope != 'uat_fixture'` — written objects are never re-tagged. Result: **quarantine batch content is written into the operational surface**.

3. **UI is equally unguarded**: `web/src/pages/ImportCenter.tsx:213-218` renders the dry-run/提交 buttons for whatever batch is in the detail panel regardless of `data_scope`; `act()` (102-110) POSTs unconditionally. Quarantine is only restricted at *listing* (view=quarantine is admin/auditor-visible). So the control is listing-visibility only — neither UI nor service blocks the write operations.

**Empirical proof this path was exercised** (read-only queries on `.platform/platform.sqlite`):
- `imp-bf333d101db6` (stores_addresses_v1, quarantine) has `archived_at=2026-08-13T05:28:36` (quarantine time) but `updated_at=2026-08-13T08:07:41`, status `committed`, `dry_run_json={"plan":{"insert":1,...},"rows":1}`, `commit_json={"stats":{"inserted":0,"skipped":1,...}}`.
- A second evidence bundle `evid-dca91a51476a` (`source_uri=import_batch:imp-bf333d101db6`) was created at 2026-08-13T08:07:41, and `iam_audit_event_v1` audit_id 437 records `bill / import.committed / import:imp-bf333d101db6` at 08:07:41 — ~2.7h **after** quarantine. The row skipped only because the address already existed (idempotency), not because of any scope guard.

## 6. Batch id generation

`_new_id(prefix)` `import_center.py:78-79`: `f"{prefix}-" + uuid.uuid4().hex[:12]`. Batch ids: `_new_id("imp")` at `upload()` line 464 → `imp-` + 12 hex chars (matches all observed ids, e.g. `imp-bf333d101db6`). Evidence ids use `_new_id("evid")` (line 806).

## 7. How commit_json/dry_run_json are stored

- `import_batch_v1` columns: `mapping_json`, `dry_run_json`, `error_report_json`, `commit_json` (store.py:1826-1843).
- Write on upload: `_save_batch` (import_center.py:1169-1197) — rows are persisted inside `mapping_json.rows` at upload ("批次文件内容在上传时随 mapping_json 保存", `_reread` 1160-1165), so dry-run/commit never need the original file.
- Update: `_update_batch` (1199-1218) rewrites all four JSON blobs + status + updated_at.
- Read: `_must` (1147-1158) parses them back into `mapping/dry_run/errors/commit` dict keys.
- API responses go through `batch_dto` (1058-1074) which whitelists keys and never leaks raw payloads (test r15, test_osv5_import_scope.py:358-370).

## 8. How the three quarantine batches were created

They were ordinary uploads by actor `bill` *before* OSV5 scope tables existed (2026-08-11T20:11 UTC: `uat.csv` → imp-8e4f53455eaa customers_v1 validation_failed, `uat_fixed.csv` → imp-9a8028ec9733 customers_v1 committed; 2026-08-12T07:13 UTC: `uat2_addr.csv` → imp-bf333d101db6 stores_addresses_v1 committed). They contained UAT fixture content but carried no `test_run_id`, so they counted as operational.

On 2026-08-13T05:28:36, `scripts/scope_reconcile_imports_v5.py --apply` (OSV5 historical reconciliation, actor `osv5_reconcile`) quarantined them: `plan_reconciliation` (lines 102-142) found 0 candidate Test Runs for their customers (`uat-cust-a/uat-cust-b`, `uatv2_20260812151305_l16gw2_cust`), decision `quarantine`; `apply_reconciliation` (145-181) executes:
```python
conn.execute(
    "UPDATE import_batch_v1 SET data_scope='quarantine',"
    " archived_at=? WHERE batch_id=? AND COALESCE("
    "data_scope,'operational')='operational",
    (_now(), d["batch_id"]))
```
(lines 165-169) — sets `data_scope='quarantine'` + `archived_at` but **does not set `visibility='history'`**, which is precisely why `_guard_active` doesn't catch them. Decisions recorded in `scope_backfill_audit_v1` (3 quarantine rows at 05:28:36). Repro test: `tests/platform/test_osv5_import_scope.py::test_r03_unassignable_batch_quarantined` (155-178). No test anywhere asserts quarantine batches refuse dry-run/commit — the gap is untested.

## 9. EventEnvelope / audit / evidence emission

- `store.emit_event` (data/store.py:3998-4030) writes `event_envelope_v1` + `outbox_v1` in one transaction (Transactional Outbox); table at line 1204 with no-delete/no-update triggers (1276-1284). **ImportCenter never calls emit_event** — imports produce no EventEnvelope at all.
- Instead, `commit()` (import_center.py:803-816) emits: `store.insert_evidence_bundle(kind="import_batch", source_uri=f"import_batch:{batch_id}", input_hash=b.file_hash, config_version=template_id)` + `iam.audit(actor, "import.committed", f"import:{batch_id}", {...})` (writes `iam_audit_event_v1`, iam.py:436-445). Both are wrapped in `try: ... except Exception: pass` — audit/evidence failures are silently swallowed.
- `insert_evidence_bundle` (store.py:4090) is called without `data_scope`/`test_run_id` → evidence rows default to `data_scope='operational'` even for fixture/quarantine batches.

## 10. Related scope infrastructure (for context)

- `scope.py`: `ScopeResolver.resolve` (176-235), `assert_test_run_current` (155-172), `create_scoped_customer` (341-378, atomic same-transaction scope), `bind_fixture_scope` (321-338), `ScopedQuery.operational_leakage` (471-526).
- `scope_registry.py`: `import_batch_v1` entry 395-404; `import_batch_customer_scope_v1` audit-only child 405-410; `_archive_import_batch` ~663-668; `ARCHIVE_HANDLERS` ~685-709.
- `scripts/scope_audit_v5.py:74-76` counts quarantine batches; `scripts/osv5_browser_evidence.py:207,261` renders the quarantine view for evidence.

## Risks
- P0 quarantine write-escape: ImportCenter.dry_run (import_center.py:546-575) and commit (749-817) have no data_scope guard — _guard_active (577-583) only blocks visibility=='history' or data_scope=='archived', so quarantine batches (visibility='current') pass and commit writes into operational tables via _commit_row (847-980). Proven in prod DB: imp-bf333d101db6 committed at 08:07:41, ~2.7h after quarantine (audit_id 437, evid-dca91a51476a).
- Re-commit of already-committed batches is permitted by design (status gate accepts 'committed', import_center.py:754) — combined with the missing scope guard this is the exact exploit vector used on the quarantined stores_addresses_v1 batch.
- scripts/scope_reconcile_imports_v5.py:165-169 quarantines with archived_at but not visibility='history', inconsistent with the bind branch (sets visibility='history', line 158-162) and with _archive_import_batch; this asymmetry is what lets quarantined batches stay 'active' per _guard_active.
- Audit/evidence emission in commit() is wrapped in try/except: pass (import_center.py:803-816) — a failure to record evidence or audit is silently swallowed, violating the stated contract '原文件 hash、actor、结果与错误报告进 Evidence + 审计'.
- insert_evidence_bundle called without data_scope/test_run_id (import_center.py:804-809) → evidence for fixture/quarantine commits is stored as data_scope='operational'.
- ImportCenter emits no EventEnvelope at all (store.emit_event unused) while the platform convention (control_plane.py, agents/runtime.py) is EventEnvelope + Outbox; import commits are invisible to event-sourced projections.
- The three quarantine batches have no import_batch_customer_scope_v1 rows (pre-OSV5 uploads), so authorize_batch falls to the 'global batch' path — creator (bill) and platform roles pass; customer-level fail-closed doesn't apply to them.
- No regression test covers 'quarantine batch refuses dry-run/commit' (tests/platform/test_osv5_import_scope.py only tests archive refusal r21 and quarantine creation r03) — the fix needs a new red test.
- UI (web/src/pages/ImportCenter.tsx:213-218) shows enabled dry-run/提交 buttons for any batch incl. quarantine view — even the presentation layer offers no guard.

## Open questions
- Who/what executed the 08:07:41 dry-run+commit against imp-bf333d101db6 (actor=bill) — manual repro or an automated UAT script (scripts/osv5_browser_evidence.py touches the quarantine view)? The audit trail doesn't distinguish.
- Intended quarantine lifecycle: should quarantine batches be permanently frozen (guard), or routed into a human adjudication state machine (task #4 suggests the latter) — determines whether the fix rejects with 409 or redirects to a release/re-bind flow.
- Should commit also emit a real EventEnvelope (store.emit_event) instead of only evidence+iam.audit, per control-plane conventions used elsewhere (control_plane.py)?