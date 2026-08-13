# IAM + users_v1 import: initial_password_once data flow and leak surfaces

## Key files
- src/platform/import_center.py — Import Center core: templates (users_v1 L180-193), commit/receipts (L749-817, L912-921), batch_dto (L1058-1074), commit_json write/read (L1147-1218)
- src/platform/iam.py — IAMService: create_principal + hash-only storage (L148-187), SCOPES/roles incl. iam.manage (L47-89), authorize/visible_customers (L296-336), audit (L436-450)
- src/platform/auth.py — hash_password/verify_password PBKDF2 (L43-56), AuthService login/session (L123-205), require_principal (L208-223)
- src/platform/api/import_api.py — HTTP endpoints: GET batch detail (L98-108), batch lists (L84-96), preview (L110-124), errors.csv (L150-169), commit (L137-148)
- src/platform/data/store.py — import_batch_v1 schema with commit_json column (L1826-1842, 2221-2231)
- src/platform/gate_evaluator.py — gate check import_batch_raw_payload_redacted, structural-only (L509-516)
- src/platform/scope_registry.py — registry entry for import_batch_v1 (L395-404) and archive handler that preserves commit_json (L663-667)
- web/src/pages/ImportCenter.tsx — frontend renders initial_password_once with false '仅显示一次' claim (L244-249)
- tests/platform/test_abos_v3_import_center.py — current expectation: receipt in commit response, usable for login (L152-160)

## Findings
## Data flow: initial_password_once → commit_json → GET responses

### 1. Generation (import_center.py)
`_commit_row` for users_v1 (src/platform/import_center.py:912-921):
- L913-914: `import secrets; temp_pw = "Init-" + secrets.token_hex(4)` (only 32 bits of entropy)
- L915-918: `self.iam.create_principal(kind=..., username=..., display_name=..., password=temp_pw, created_by=actor)`
- L919 comment claims: "一次性初始口令只在回执中返回（不写明文入库/日志）" — FALSE, see step 2
- L920-921: returns receipt `{"username": rec["username"], "initial_password_once": temp_pw}`

### 2. Persistence into commit_json (import_center.py)
`commit()` (L749-817):
- L763: `receipts: list[dict] = []`; L778-781: every `_commit_row` return appended
- L796: `commit_result = {"stats": stats, "receipts": receipts[:50]}` ← plaintext passwords included (note [:50] truncation)
- L800-801: `self._update_batch(batch_id, status=status, errors=errors, commit=commit_result)`
- `_update_batch` (L1199-1218): L1215 `json.dumps(commit ...)` written to `commit_json` column at L1208
- Schema: src/platform/data/store.py:1838 `commit_json TEXT NOT NULL DEFAULT '{}'` (migration _M042, L1826); rows added later: data_scope/test_run_id/visibility/archived_at/source/correlation_id (store.py:2221-2231)
- Read back: `_must()` L1157 `d["commit"] = json.loads(d["commit_json"])`

### 3. Batch detail DTO (GET responses)
`batch_dto` (import_center.py:1058-1074):
- L1059-1060 docstring: "绝不返回 mapping_json/dry_run_json/error_report_json/commit_json 等原始 payload（指令 P0-004）"
- L1052-1056: `_DTO_KEYS` whitelist excludes the raw JSON *columns*
- **BUT L1071-1073: `d["commit"] = {"stats": c.get("stats"), "receipts": c.get("receipts")}` — receipts pass through verbatim, re-exposing every initial_password_once on every read forever**

### 4. API surfaces (src/platform/api/import_api.py)
- POST /api/v1/import/batches/{id}/commit (L137-148) → batch_dto — intended one-time receipt delivery
- GET /api/v1/import/batches/{batch_id} (L98-108) → L102-108 `center.get_batch` + `authorize_batch` + `batch_dto` → receipts re-served indefinitely
- GET /api/v1/import/batches?view=operational|mine|history|quarantine (L84-96) → `list_batches` (import_center.py:1086-1141) returns `batch_dto` for ALL four views: default operational (L1126-1141), mine (L1118-1124), **history (L1105-1117)**, **quarantine (L1094-1104)**
- GET /batches/{id}/errors.csv (L150-169): dumps `b["errors"]`; error strings are `str(e)[:300]` from commit failures (import_center.py:785) — IAMError messages ("username 已存在: X") don't contain the password, so no current leak, but unfiltered error text is a latent channel
- GET /batches/{id}/preview (L110-124) → `preview_rows` (import_center.py:1076-1084): raw uploaded rows; users_v1 files contain no password column (password is generated at commit), so no leak — `"redacted": True` (L1081) is a bare flag, no field masking exists

### 5. IAM / password hashing (src/platform/iam.py, src/platform/auth.py)
- `IAMService.create_principal` (iam.py:148-187): L156-157 requires password for kind=user; L167 `pw_hash = hash_password(password) if password else ""`; only `password_hash` stored in `iam_principal_v1` (L170-177); audit `iam.principal.created` detail (L183-186) contains only kind/data_scope/test_run_id — **no password in audit**
- Hashing (auth.py:43-47): `hash_password` = PBKDF2-HMAC-SHA256, 60,000 iters (`_PBKDF2_ITERS` L34), random 16-byte salt, `salt$dk` hex; `verify_password` (L50-56) via `hmac.compare_digest`. Login path: `verify_login` (iam.py:215-236), fallback from AuthService.login (auth.py:150-189)
- Permissions: `SCOPES` bundle incl. `iam.manage` (iam.py:47-57); `TEMPLATE_SCOPE["users_v1"]="iam.manage"` (import_center.py:42); authorize_template (import_center.py:391-401); platform actors (admin session role / owner / platform_admin roles) bypass at L385-389; `authorize_batch` (L417-444): batch creator always allowed (L421) — creator can re-GET receipts forever
- Audit append-only: iam.py:436-444 (`iam_audit_event_v1`); commit audit at import_center.py:810-814 logs only `{"template", "stats"}` — **no receipts, no leak**; events: no event_envelope emission from import_center (verified by grep)

### 6. users_v1 template definition
- TEMPLATES["users_v1"] import_center.py:180-193: columns username (required), display_name, kind (user/service_account), status (active/disabled); L191-192 note promises the one-time password is "不入库明文" — violated by receipt persistence
- users_v1 has no customer column (TEMPLATE_CUSTOMER_COL L60 → None) → global template; non-platform viewers need `data.import.audit` for the batch (authorize_batch L441-444)
- fixture scope inheritance: users_v1 → iam_principal_v1 by username (import_center.py:70, _inherit_batch_scope L819-845)

### 7. Existing "redaction" logic (all insufficient for secrets)
- `_DTO_KEYS` whitelist (import_center.py:1052-1056) — blocks raw column names only
- Gate check `import_batch_raw_payload_redacted` (gate_evaluator.py:509-516): only asserts `_DTO_KEYS ∩ {mapping_json, dry_run_json, error_report_json, commit_json} == ∅` — structural, never inspects receipts content; passes green while passwords leak
- preview_rows `redacted: True` flag (import_center.py:1081) — cosmetic
- `leak_scan` in scope_registry/scope.py (scope.py:542 `_SCOPED_TABLES = _leak_scan_tables()`) = fixture scope leakage scanning, NOT secret scanning
- Archive handler `_archive_import_batch` (scope_registry.py:663-667) only flips data_scope/visibility — commit_json (with passwords) survives archival and keeps being served via history/quarantine views

### 8. Consumers of the receipt
- Frontend web/src/pages/ImportCenter.tsx:29 (DTO type), L244-249 renders `r.initial_password_once` in a `<code>` tag with text "仅显示一次，请尽快修改" — the "shown once" claim is false since every subsequent GET re-serves it
- Test tests/platform/test_abos_v3_import_center.py:152-154: reads `b["commit"]["receipts"][0]["initial_password_once"]` from the commit POST response and uses it to log in (L157-160)

### Complete leak-surface list for initial_password_once
1. **commit_json at rest** — import_batch_v1.commit_json (SQLite), survives archival
2. POST /commit response (intended, one-time)
3. **GET /api/v1/import/batches/{id}** — batch_dto receipts re-exposure (import_api.py:108)
4. **GET /api/v1/import/batches view=operational & view=mine** — list of DTOs w/ receipts
5. **GET /api/v1/import/batches view=history** — archived batches still return passwords to platform/authorized actors
6. **GET /api/v1/import/batches view=quarantine** — passwords served to auditors/platform admins
7. Frontend ImportCenter detail panel re-renders from any of the above
NOT leaking (verified): iam_audit_event_v1 (both import.committed and iam.principal.created details), event_envelope_v1 (no emission), errors.csv (error text doesn't contain passwords today), preview rows (password not in source file), iam_principal_v1 (hash only).

## Risks
- P0 leak: initial_password_once is persisted in import_batch_v1.commit_json (import_center.py:796 → 800-801 → _update_batch L1208/1215) despite the in-code comment at L919 claiming it is never written to DB
- P0 leak: batch_dto passes receipts through verbatim (import_center.py:1071-1073), so GET /api/v1/import/batches/{id} (import_api.py:108) and ALL list views — operational, mine, history, quarantine (import_center.py:1094-1141) — re-serve plaintext passwords indefinitely to anyone with batch visibility (creator always allowed per authorize_batch L421)
- Weak entropy: temp_pw = 'Init-' + secrets.token_hex(4) = 32 bits (import_center.py:914), and it remains valid until the user changes it — a leaked persisted password is directly login-usable (verified by test test_abos_v3_import_center.py:157-160)
- Gate blind spot: import_batch_raw_payload_redacted (gate_evaluator.py:509-516) only checks DTO key names, not receipts content — passes green while leaking; any fix must extend this check or add a content-level secret scan of receipts
- Archival does not redact: _archive_import_batch (scope_registry.py:663-667) keeps commit_json; history/quarantine views continue serving old passwords
- Functional gap: receipts[:50] truncation (import_center.py:796) means users in rows >50 of a single batch are created with a password nobody ever receives
- Frontend contract mismatch: ImportCenter.tsx L244-249 displays '仅显示一次' while every GET re-returns the password — after a zero-persistence fix the UI must not expect receipts on detail re-reads
- Latent channel: errors.csv and DTO errors pass raw exception text (import_center.py:785 str(e)[:300]); safe today because IAMError messages omit secrets, but no allowlist/masking exists

## Open questions
- Desired P0-2 semantics: should the receipt be returned ONLY in the POST /commit response and never persisted (e.g., hold receipts in memory for that one response), or persisted encrypted/with a short TTL?
- Should receipts beyond 50 rows (receipts[:50] truncation) also be addressed — currently those users get created with an unrecoverable password
- Do existing DB backups/snapshots of the project's SQLite store need rotation guidance once persistence is removed?
- Are there other deployed DB copies (CI fixtures, demo data) containing commit_json with passwords that need cleanup migration?