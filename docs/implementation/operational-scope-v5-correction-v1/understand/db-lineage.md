# platform.sqlite READ-ONLY forensics: import_batch_v1 / import_batch_customer_scope_v1 lineage, 3 quarantine batches, 17 unbound history batches, reconciliation audit, customer-binding verdicts

## Key files
- .platform/platform.sqlite — live DB; import_batch_v1 (29 rows), import_batch_customer_scope_v1 (12 rows), md_customer_v1 (46 rows), uat_test_run_v1 (33 rows), scope_backfill_audit_v1 (83 rows, de-facto reconciliation log), iam_audit_event_v1 (437 rows incl. 26 import.committed)
- .platform/logs/app.log — uvicorn access log; contains both POST /commit calls for imp-bf333d101db6 (lines 7001 & 18504) and 405 probes on /adjudicate|/resolve|/bind|/delete|/archive (lines 18450-18454)
- .platform/backups/ — point-in-time DB snapshots (platform_pre_scope_v3/v4/v5) useful as before-state baselines for any backfill write

## Findings
## 1. Schemas (verbatim CREATE TABLE)

```sql
CREATE TABLE import_batch_v1 (
    batch_id TEXT PRIMARY KEY, template_id TEXT NOT NULL,
    filename TEXT NOT NULL DEFAULT '', file_format TEXT NOT NULL DEFAULT 'csv',
    file_hash TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'uploaded',
    actor TEXT NOT NULL DEFAULT '', row_count INTEGER NOT NULL DEFAULT 0,
    mapping_json TEXT NOT NULL DEFAULT '{}', dry_run_json TEXT NOT NULL DEFAULT '{}',
    error_report_json TEXT NOT NULL DEFAULT '[]', commit_json TEXT NOT NULL DEFAULT '{}',
    idempotency_key TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    data_scope TEXT NOT NULL DEFAULT 'operational', test_run_id TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT 'current', archived_at TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'import_center', correlation_id TEXT NOT NULL DEFAULT '');

CREATE TABLE import_batch_customer_scope_v1 (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id TEXT NOT NULL, customer_id TEXT NOT NULL,
  project_id TEXT NOT NULL DEFAULT '', scope_source TEXT NOT NULL DEFAULT 'row',
  authorization_decision TEXT NOT NULL DEFAULT 'granted', created_at TEXT NOT NULL);
```
No FK, no UNIQUE(batch_id, customer_id) on the scope table. `scope_attribution_ledger_v1` covers only usage_event_v2/evidence_bundle_v1 — import batches are out of its scope.

## 2. All 29 batches (batch_id | template | data_scope | status | test_run_id | created_at)

| batch | template | scope | status | test_run_id | created_at |
|---|---|---|---|---|---|
| imp-8e4f53455eaa | customers_v1 | **quarantine** | validation_failed | (empty) | 2026-08-11T20:11:11.286Z |
| imp-9a8028ec9733 | customers_v1 | **quarantine** | committed | (empty) | 2026-08-11T20:11:11.288Z |
| imp-786ac958c7f4 | customers_v1 | uat_fixture | validation_failed | uat_fixture_v3 | 2026-08-12T04:34:29.202Z |
| imp-5ade043c9c60 | customers_v1 | uat_fixture | committed | uat_fixture_v3 | 2026-08-12T04:34:29.204Z |
| imp-d6ad84358c46 | projects_v1 | uat_fixture | committed | uat_fixture_v3 | 2026-08-12T04:34:29.207Z |
| imp-7accb955db6a | stores_addresses_v1 | uat_fixture | committed | uat_fixture_v3 | 2026-08-12T04:34:29.211Z |
| imp-5c139e5e983b | customers_v1 | uat_fixture | validation_failed | uat_fixture_v3 | 2026-08-12T04:37:06.130Z |
| imp-cfbc25ce2b88 | customers_v1 | uat_fixture | committed | uat_fixture_v3 | 2026-08-12T04:37:06.132Z |
| imp-7379230b6fea | projects_v1 | uat_fixture | committed | uat_fixture_v3 | 2026-08-12T04:37:06.135Z |
| imp-0a04c818ce4e | stores_addresses_v1 | uat_fixture | committed | uat_fixture_v3 | 2026-08-12T04:37:06.138Z |
| imp-bf333d101db6 | stores_addresses_v1 | **quarantine** | committed | (empty) | 2026-08-12T07:13:06.035Z |
| imp-e7633ed6bbf1 | stores_addresses_v1 | uat_fixture | committed | uatv2_20260812151543_ph5m62 | 2026-08-12T07:15:43.881Z |
| imp-ed8520470638 | stores_addresses_v1 | uat_fixture | committed | uatv2_20260812151746_40kr1t | 2026-08-12T07:17:46.675Z |
| imp-d53e7062b75c | stores_addresses_v1 | uat_fixture | committed | uatv2_20260812152256_gee9uq | 2026-08-12T07:22:56.938Z |
| imp-ea3bfdf1fbce | stores_addresses_v1 | uat_fixture | committed | uatv2_20260812153016_6uvg8f | 2026-08-12T07:30:16.919Z |
| imp-645d0d0a91b3 | stores_addresses_v1 | uat_fixture | committed | uatv2_20260812153326_7s3rdo | 2026-08-12T07:33:26.614Z |
| imp-f8e3004a7555 | stores_addresses_v1 | uat_fixture | committed | uatv2_20260812170359_5vqash | 2026-08-12T09:03:59.959Z |
| imp-80e73fe0b2af | stores_addresses_v1 | uat_fixture | committed | uatv3_20260812183322_58910h | 2026-08-12T10:33:22.416Z |
| imp-f6c70b10e087 | stores_addresses_v1 | uat_fixture | committed | uatv3_20260812184256_68e64r | 2026-08-12T10:42:56.470Z |
| imp-dbff8a9fd90d | stores_addresses_v1 | uat_fixture | committed | uatv3_20260812184651_kob8rt | 2026-08-12T10:46:52.015Z |
| imp-718cbe298769 / imp-c5078de1780e / imp-789be3fb33e7 | cust/prj/stores | uat_fixture | committed(2)/validation_failed(1) | uatv7_20260813053847_jiv6d6 | 2026-08-13T05:38:47Z |
| imp-2b0fa9391e30 / imp-abd5c30ec408 / imp-3ba7292382da | cust/prj/stores | uat_fixture | committed | uatv7_20260813053942_kh463m | 2026-08-13T05:39:42Z |
| imp-8794cb38594c / imp-13bff4e623a0 / imp-6411b356cfbf | cust/prj/stores | uat_fixture | committed | uatv7_20260813054236_t8ribm | 2026-08-13T05:42:36Z |

Visibility: 3 quarantine batches are `visibility=current` + archived_at set; the 26 others are `visibility=history` + archived. All correlation_id/idempotency_key empty.

## 3. The 3 quarantine batches (all archived_at = 2026-08-13T05:28:36Z by `osv5_reconcile`)

**imp-8e4f53455eaa** (customers_v1, validation_failed): filename uat.csv, actor bill, row_count 2. mapping rows: [uat-cust-a, "UAT客户A", …], [uat-cust-b, "", …]. error_report: row 3 必填字段缺失 name. commit_json = `{}` (never committed). No objects created by this batch.

**imp-9a8028ec9733** (customers_v1, committed): uat_fixed.csv, same 2 rows with name fixed. commit_json keys: `stats{inserted:2,skipped:0,failed:0}`, `receipts:[]`. DID create md_customer_v1 rows uat-cust-a/uat-cust-b (created_at 20:11:11.290591/.290733, interleaved with batch updated_at .290892; iam audit import.committed at .291041).

**imp-bf333d101db6** (stores_addresses_v1, committed): uat2_addr.csv, 1 row → customer `uatv2_20260812151305_l16gw2_cust`, store "UAT2 门店/预演二路 2 号". commit_json keys: `stats{inserted,skipped,failed}`, `receipts:[]`. Current commit_json = `{inserted:0, skipped:1, failed:0, receipts:[]}` — OVERWRITTEN by replay.

**Replay evidence for imp-bf333d101db6 (quarantine write-escape, confirms task #2):**
1. iam_audit_event_v1 has TWO `import.committed` events for `import:imp-bf333d101db6`: original 2026-08-12T07:13:06.037738Z (inserted:1) and replay **2026-08-13T08:07:41.416485Z** (inserted:0, skipped:1) — 2h39m AFTER it was quarantined/archived (05:28:36Z).
2. import_batch_v1.updated_at = 2026-08-13T08:07:41.416302Z (matches replay event; created_at is 08-12) and commit_json rewritten from the original inserted:1 to skipped:1.
3. .platform/logs/app.log: `POST /api/v1/import/batches/imp-bf333d101db6/commit` appears twice (lines 7001, 18504); the second is preceded by `GET /batches?view=quarantine` and `GET /batches/imp-bf333d101db6`, and followed-by/preceded-by OPTIONS probes to `/adjudicate`, `/resolve`, `/bind`, `/delete`, `/archive` → all **405 Method Not Allowed** (lines 18450-18454) — the adjudication endpoints don't exist yet (task #4).
4. Object-level effect was idempotent (geo_address_v1 addr-8002b0f0474f created 08-12T07:13:06.037; no second row), but the commit path executed against a quarantined+archived batch and mutated DB state.
5. event_envelope_v1/blackboard/agent/job tables contain NO batch references and no envelopes after 2026-08-12T19:30Z — the import API emits no envelopes, so actor attribution is only `bill` from iam audit.

## 4. The 17 history batches lacking scope rows — facts per batch

8× uat_fixture_v3 (incl. 2 validation_failed: imp-786ac958c7f4, imp-5c139e5e983b — both reference nonexistent `uat_fixture_v3_cust2` in mapping), 6× uatv2 stores, 3× uatv3 stores. Facts for EACH (all verified by joins, registry_hit=1, cust_hit=1):
- **batch.test_run_id is set** (uat_fixture_v3 / uatv2_* / uatv3_*) — direct structured linkage.
- **uat_test_run_v1 registry row exists** for that namespace (status archived; customer_ids_json lists the *_cust customer; uat_fixture_v3 entry created by si2_backfill, uatv2/v3 by si2_backfill too).
- **md_customer_v1** row exists with matching test_run_id (uat_fixture_v3_cust; uatv2_*_cust; uatv3_*_cust).
- **Object tables**: md_project_v1 rows (projects_v1 batches → uat_fixture_v3_prj under uat_fixture_v3_cust; customer_id at column index 1 per column_map) and geo_address_v1 store rows under each *_cust with matching test_run_id.
- **iam_audit_event_v1**: `import.committed` event with resource=`import:<batch_id>` for every committed batch (stats inserted:1; the 04:37:06 trio shows skipped:1 = duplicate re-import).
- **scope_backfill_audit_v1 rows 66-83** (actor `osv5_reconcile`, 2026-08-13T05:28:36Z): rule "mapping/commit 客户 ↔ 唯一 Test Run 客户集", assigned_scope=uat_fixture, assigned_test_run_id = exactly the batch's test_run_id for all 17. NOTE: these decisions were never materialized into import_batch_customer_scope_v1 (still 0 rows) and the audit detail_json does NOT include the batch_id (only batch_customers/candidates/rules), so rows map to batches only by creation order.

import_batch_customer_scope_v1 contains only 12 rows, all for the 9 uatv7 batches (scope_source='row', authorization_decision='granted') — the only batches created after the scope-writing code path existed.

## 5. Customers (md_customer_v1, 46 rows) — NO operational-scope customer exists; all are data_scope='uat_fixture'

- demo-cust-a / demo-cust-b (演示客户A/B, is_test_fixture=1, admin; test_run_id = own customer_id; registered+archived test runs created by si2_backfill)
- uat-cust-a / uat-cust-b (UAT客户A/B, **is_test_fixture=0**, created_by bill via imp-9a8028ec9733; test_run_id backfilled to own ID by si2 rule r22 but NO registry row)
- uat_fixture_v3_cust (is_test_fixture=0, test_run_id uat_fixture_v3)
- uatv2_20260812151235_k7kvqp_cust, uatv2_..._l16gw2_cust (orphans: objects exist, no import batch, no registry row; SKU backfilled under synthetic `legacy_uat_v2v3_backfill`)
- 6× uatv2 *_cust (+4 *_cust2 added later outside imports), 3× uatv3 *_cust, 5× uatv4, 6× uatv5, 2× uatv6, 6× uatv7 — all test_run_id = their namespace.

## 6. Reconciliation audit tables

No table name matches `%reconcil%`. The de-facto reconciliation log is **scope_backfill_audit_v1** (83 rows): si2_backfill (ids 1-22, structural/名称线索 backfills incl. r22 "fixture 客户按 ID 推导 namespace"), si3-backfill (ids 23-63, r1-r23 rules with ids_hash + commit_ref evidence), and **osv5_reconcile (ids 64-83)** — the import-batch reconciliation pass: 3× "quarantine: 候选 Test Run 数=0" + 17× "mapping/commit 客户 ↔ 唯一 Test Run 客户集". scope_attribution_ledger_v1 (232 rows) only attributes usage_event_v2/evidence_bundle_v1. audit_event (55 rows) has no import references.

## 7. Verdict — deterministic binding vs 未绑定/待裁决

**DETERMINISTICALLY BINDABLE (17)** — batch.test_run_id → existing uat_test_run_v1 row → single customer; corroborated by md_customer_v1.test_run_id, object tables, iam import.committed, and osv5_reconcile audit. No name guessing required:
- 8× uat_fixture_v3 batches → customer `uat_fixture_v3_cust`
- imp-e7633ed6bbf1 → uatv2_20260812151543_ph5m62_cust; imp-ed8520470638 → uatv2_20260812151746_40kr1t_cust; imp-d53e7062b75c → uatv2_20260812152256_gee9uq_cust; imp-ea3bfdf1fbce → uatv2_20260812153016_6uvg8f_cust; imp-645d0d0a91b3 → uatv2_20260812153326_7s3rdo_cust; imp-f8e3004a7555 → uatv2_20260812170359_5vqash_cust
- imp-80e73fe0b2af → uatv3_20260812183322_58910h_cust; imp-f6c70b10e087 → uatv3_20260812184256_68e64r_cust; imp-dbff8a9fd90d → uatv3_20260812184651_kob8rt_cust

**MUST REMAIN 未绑定/待裁决 (3 quarantine)** — all have candidate Test Run count = 0 in the registry:
- imp-8e4f53455eaa: never committed, no objects, no registry namespace for uat-cust-a/b → 待裁决.
- imp-9a8028ec9733: customer-level facts ARE deterministic (it created uat-cust-a/uat-cust-b; timestamps interleave), but there is no registered test run for them (their md_customer test_run_id is a synthetic self-reference) → customer binding possible, namespace binding 待裁决.
- imp-bf333d101db6: customer uatv2_..._l16gw2_cust + project + geo_address + SKU facts exist (SKU was si3-backfilled into synthetic `legacy_uat_v2v3_backfill`), but uat_test_run_v1 has no l16gw2 row → 待裁决; additionally requires human adjudication BEFORE any binding because of the post-quarantine replay write-escape.

## Risks
- QUARANTINE WRITE-ESCAPE (confirmed live): imp-bf333d101db6 was re-committed at 2026-08-13T08:07:41Z while data_scope='quarantine' and archived — evidence: second iam_audit_event_v1 import.committed (stats 0/1/0), import_batch_v1.updated_at 08:07:41.416302Z, commit_json overwritten from inserted:1 to skipped:1, two POST /commit lines in .platform/logs/app.log. Backs task #2.
- ADJUDICATION ENDPOINTS MISSING: OPTIONS probes to /adjudicate, /resolve, /bind, /delete, /archive on the quarantine batch all returned 405 (.platform/logs/app.log lines 18450-18454) — quarantine has no exit path; backs task #4.
- RECONCILE DECISIONS NOT MATERIALIZED: osv5_reconcile assigned scope+test_run for 17 batches in scope_backfill_audit_v1 (ids 66-83) at 05:28:36Z but import_batch_customer_scope_v1 still holds 0 rows for them (only 12 uatv7 rows exist) — the exact gap task #5 must backfill.
- RECONCILE AUDIT LACKS batch_id: scope_backfill_audit_v1 ids 64-83 detail_json carries only batch_customers/candidates/rules; binding audit rows to specific batches relies on creation order (matched_count=1 each). Any backfill should record batch_id explicitly.
- import_batch_customer_scope_v1 has no UNIQUE(batch_id,customer_id) and no FK — duplicate/orphan scope rows are possible; backfill should upsert defensively.
- STATE-MACHINE AMBIGUITY: quarantine is expressed only by data_scope='quarantine' while status stays 'committed'/'validation_failed' and visibility='current'; no distinct quarantine status or adjudication state exists.
- CLASSIFICATION INCONSISTENCY: uat-cust-a/uat-cust-b and all uatv7_* customers have is_test_fixture=0 yet data_scope='uat_fixture'; md_customer_v1 contains ZERO operational-scope customers.
- ORPHAN NAMESPACES: uatv2_20260812151235_k7kvqp and uatv2_20260812151305_l16gw2 have customer/project/sku/geo objects but no import batch and no uat_test_run_v1 entry; only partially covered by the synthetic legacy_uat_v2v3_backfill namespace (customer_ids_json='[]').

## Open questions
- For imp-bf333d101db6: bind to synthetic legacy_uat_v2v3_backfill (where si3-backfill already parked the l16gw2 SKU), register a real uatv2_..._l16gw2 test-run entry via adjudication, or keep 未绑定? Needs owner decision.
- For imp-9a8028ec9733: register namespaces for uat-cust-a/uat-cust-b the way si2 did for demo-cust-a/b (test runs with customer's own ID), or treat as legacy unregistered?
- What actor/flow triggered the 08:07:41Z replay of the quarantined batch (browser QA vs automated test)? app.log lacks timestamps and the import path emits no event envelopes, so attribution stops at actor_id='bill'.
- Should the 2 validation_failed uat_fixture_v3 batches (imp-786ac958c7f4, imp-5c139e5e983b) receive scope rows referencing only the existing customer uat_fixture_v3_cust, given their mapping's second customer uat_fixture_v3_cust2 was never created?
- Should reconciliation audit (scope_backfill_audit_v1 ids 64-83) be re-run/patched to embed batch_id before the backfill writes scope rows, to keep the audit chain verifiable?