# LLM-Image (QY FMCG / Agentic Business OS) — full project map: docs, services, abos CLI, tests, migrations, implementation rounds, bundle protocol, gates

## Key files
- docs/CODEX-PROJECT-HANDBOOK.md — Codex continuity handbook: progress snapshots, authority hierarchy, gates, methodology lessons (latest truth about rounds)
- docs/handbook.md — system state snapshot: cascade recognition architecture, service/port table, immutable bundle protocol, data protocols (dated 2026-08-04, partly stale)
- docs/architecture.md — ADR-01..08 (VLM-as-teacher/YOLO-as-student, human gate, native-first, retrieval-recall-only, append-only, SQLite-first, cascade)
- docs/structure.md — three-stage data flow, legacy src/ map, runtime data dirs, 8-table warehouse schema, red lines
- docs/README.md — documentation map + current/historical implementation entry points
- bin/abos — local stack controller (status/start/stop/restart/doctor) for the 4-service topology
- pyproject.toml — deps (numpy/pillow/requests + optional training/platform/vlm-train/dev), pytest hermetic config (not host_mps)
- conftest.py — sys.path insert + autouse _hermetic_auth_env fixture popping PLATFORM_ADMIN_* env vars
- src/platform/data/store.py — PlatformStore: 59 in-code migrations (_M001.._M059), schema_migrations sha256 tamper check, apply_migrations()
- src/platform/scope_registry.py — full-table scope registry (123 tables) driving scanner/archiver/filter/Gate derivation
- src/platform/gate_evaluator.py — machine gate evaluator (osv5_gate_evaluate.py produces gate.json)
- src/models/bundle.py — immutable model bundle governance CLI (create/publish/rollback/verify/list/current)
- src/recognize/service.py — cascade recognition service on :8091, loads from CURRENT.json with per-file hash verify
- src/composition/serve.py — unified platform app (ABOS web + /api/v1) on :8400
- src/platform/api/ — FastAPI-style API modules (app.py, iam_api, import_api, control_plane_api, agent_runtime_api, ...)
- src/platform/auth.py — platform auth (reads PLATFORM_ADMIN_CREDENTIALS etc.)
- .models/bundles/CURRENT.json — atomic production bundle pointer (currently prod_v4_best_r1, previous prod_20260805_v5_r1)
- .eval/scope_v5/gate.json — current machine gate: READY_FOR_REAL_DATA_UAT, 52/52 checks, bound to HEAD 8e31708d + DB fingerprint
- docs/implementation/agentic-business-os-operational-scope-v5/STATUS.md — status of the last closed round (all T0-T10 DONE)
- docs/implementation/operational-scope-v5-correction-v1/BEFORE-STATE.md — before-state of the CURRENT open round (only file in that dir so far)

## Findings
## 1. Repo identity and current state
- Root: `/Users/zhangweiqi/Documents/QY/项目/LLM-Image`; branch `feat/nextgen-training-cycle-v2`; HEAD `8e31708d` (= osv5 T10 governance-closure commit). Started as a shelf-SKU recognition system; now an **Agentic Business OS (ABOS)**: one Foundation + Graph+Loop kernel + pluggable Domain Packs (recognition is the first Domain Pack, not the center).
- Python: `/Users/zhangweiqi/miniconda3/bin/python` (3.13.2). Apple M3 Max (16 CPU / 40 GPU / 128GB), MPS-verified. Local-first; Docker optional only.
- **No AGENTS.md exists** anywhere within maxdepth 3 (find returned nothing).

## 2. Service topology (from `bin/abos` + handbook.md)
Four services managed by `bin/abos` (PIDs in `.platform/run/`, logs in `.platform/logs/`):

| Service | Port | Command | Health probe |
|---|---|---|---|
| recognize (cascade recognition API) | 8091 | `python -m src.recognize.service --port 8091` | any HTTP != 000 on `/` |
| training monitor | 8092 | `python -m src.training.monitor --port 8092` | any HTTP != 000 on `/` |
| Label Studio | 8300 | `bash scripts/start_label_studio.sh` | `/health` == 200 |
| app (unified ABOS platform: Web + /api/v1) | 8400 | `python -m src.composition.serve --port 8400` | `/api/v1/health` == 200 |

Auxiliary/legacy: 8301 YOLO ML backend (`src.ls_ml_backend.yolo_backend`, LS auto-prelabel), 8304 orchestrator (`src.ls_platform.orchestrator`), 8090 zero-dep review server (legacy labeling), 8455 (historical). `omlx-server` runs locally for all embed/VLM/OCR (gemma-4 VLM / Qwen3 embeddings / PaddleOCR-VL / DeepSeek-OCR). At the current round's BEFORE-STATE all four services were UP, production=`prod_v4_best_r1`, no training processes, watchdog not running.

## 3. `bin/abos` CLI (ABOS T11)
Bash stack controller, commands `status | start | stop | restart | doctor`. Principles baked in: idempotent (skip already-up services), only manages PIDs it recorded + precise command-line matches (never broad kill), never starts training (but warns if it detects `train_detector|train_classifier|train_segmenter|run_qwen3vl_lora|ultralytics`), honest health (waits up to 15/15/30/90s per service and reports failure instead of lying). Details:
- `status`: probes all four, reports managed PIDs, prints production bundle id from `.models/bundles/CURRENT.json`, training-process check, monitor watchdog state.
- `start`: starts recognize → monitor → label_studio → app via nohup, then `wait_ok` per service.
- `stop`: stops the monitor watchdog **first** (else monitor gets resurrected), then app → label_studio → monitor → recognize; 10s SIGTERM grace then SIGKILL.
- `doctor`: SQLite `PRAGMA integrity_check` on `.platform/platform.sqlite`; CURRENT.json existence; `web/dist` built; DEEPSEEK_API_KEY configured (else "Agent will honestly degrade to rule answers"); port occupancy via lsof; training-process detection.

## 4. Test conventions
- **Hermetic default suite**: `pyproject.toml` sets `addopts = "-m 'not host_mps'"`; markers: `host_mps` ("真实宿主 MPS/Apple 探针测试, 非 hermetic, 需普通 Terminal") and `slow`. Host tests run separately: `pytest -m host_mps`. Handbook rule: Codex/sandbox processes may not see MPS/sysctl, so tests must distinguish hermetic mock vs host G0; real startup accepts only host probes.
- **`conftest.py`**: inserts repo root into `sys.path` (import `src.*` without install) + autouse fixture `_hermetic_auth_env` that pops `PLATFORM_ADMIN_CREDENTIALS`, `PLATFORM_ADMIN_PASSWORD`, `PLATFORM_USERS` from the environment because `src/common/config.py` loads `.env` (with production credentials) at import; tests must monkeypatch their own auth env.
- Baseline command: `XONSH_HISTORY_BACKEND=dummy PYTHONDONTWRITEBYTECODE=1 <python> -m pytest -p no:cacheprovider -q`.
- Test tree: `tests/{unit, contract, platform, promotion}`. Latest baselines: osv5 hermetic **1479 passed**, host MPS **6 passed** (si3: 1425, si4: 1447).

## 5. Migration system
- **Platform DB**: `.platform/platform.sqlite` is the local single source of truth (107+ tables). Migrations are NOT in `migrations/platform/` — they live **in code** in `src/platform/data/store.py` as an append-only ordered list of 59 entries `("0NN_name", _M0NN)`, latest = `059_import_scope_lineage_v1`.
- `PlatformStore.apply_migrations()` records `(name, sha256, applied_at)` in `schema_migrations`; **tamper check**: if a recorded sha256 differs from current migration content → refuses to start ("migration 已被篡改"). New migrations must be appended only.
- Legacy `migrations/`: `sqlite/001_schema.sql` (old warehouse `.warehouse/db.sqlite`, 8 tables, append-only triggers on annotation/auto_label/review_event) and `postgres/{000_init.sql,001_schema.sql}` (isomorphic schema for future PG switch; ADR-06).
- Pre-round DB backups are mandatory (e.g. `.platform/backups/platform_pre_v3_*.sqlite`, `platform_pre_scope_v5_20260813T124408`).

## 6. How docs/implementation rounds are organized
Each round is a directory under `docs/implementation/<round-slug>/` containing: `README.md`, `AGENT-EXECUTION-PROMPT.md` (self-contained continuous-execution task book), `STATUS.md` (**the single Gate authority for the round**), `ISSUES.md` / `LIST.md`, `EXECUTION-LOG.md`, `FINAL-REPORT.md`, `DECISIONS.md`, `READING-LIST.md`, `BEFORE-STATE.md`, plus numbered design docs (e.g. `00-LIVE-AUDIT.md` … `07-BROWSER-ACCEPTANCE.md`). Rounds execute as tasks T0..Tn gated by G0..G8, red-test-first (failing tests reproduce issues before fixes), with machine gate evidence under `.eval/<round>/`.

Round chronology (18 dirs): graph-loop-training-control-v1 → nextgen-four-model-training-loop-v2 → project-logic-chain-v3 → sku-long-tail-agent-foundation-v1 → candidate-evidence-convergence-and-microgold-v1 → micro-gold-v2-leakage-rebuild → platform-v2 → agentic-business-os-workbench-v1 → agentic-business-os-domain-packs-v2 → agentic-business-os-operational-workbench-v3 → agentic-business-os-scope-integrity-v3 → agentic-business-os-operational-scope-v4 → agentic-business-os-operational-scope-v5 → uat-scope-isolation-v2 / uat-contract-correction-v1 / uat-final-consistency-v1 → **operational-scope-v5-correction-v1 (CURRENT, only BEFORE-STATE.md exists)**.

Authority hierarchy (CODEX handbook §2.3): architecture conflicts L0 spec → Stage program → current Stage plan → Domain Pack spec; running-fact conflicts: real-time commands/current code/artifacts > latest experiment reports > latest gate > handbook > historical reports. Docs marked as snapshots must be re-verified, never trusted blindly.

## 7. Production bundle protocol (handbook.md §3, RA-006)
- A **bundle** = detector + classifier + registry + thresholds + MANIFEST (sha256 per file); files read-only. CLI: `python -m src.models.bundle {create|publish|rollback|verify|list|current}`.
- `.models/bundles/CURRENT.json` is an atomic pointer (tmp + `os.replace`) with a `previous` field keeping the rollback chain; archived bundles in `.models/archive/` are also publishable.
- Recognition service startup does `resolve_weights(verify=True)`: per-file hash verification before load; failure raises BundleError → **fail-closed refuse service**, never silent fallback to default paths; `_validate_class_alignment` (classifier classes ⊆ registry ∪ {__unknown__}); detector class count vs registry mismatch also fail-closed.
- **Current**: `CURRENT.json` = `prod_v4_best_r1`, previous `prod_20260805_v5_r1`, `switched_by=bill`, reason "回滚验证通过，最终切换为默认 standard" (user-authorized switch in workbench-v3 round after shadow compare + rollback verification; detector = sku_v4 best.pt sha256 `84bf9936…`; classifier/registry/thresholds identical SHA to the v5 bundle = zero-variable change; `CURRENT.previous.json` backup in place). History: `prod_20260804_v4_r2` → `prod_20260805_v5_r1` (sku_v5 detector) → `prod_v4_best_r1`. Experimental profiles (exp_classifier_only / exp_v4_detector_smoke / exp_m3_grouped_classifier) are honestly disabled with blockers. No further bundle switches authorized this round; no long training authorized; no merge/push/deploy.

## 8. Gate / READY_FOR_REAL_DATA_UAT
- Gate history is a series of **falsified READYs**: domain-packs-v2's `READY_FOR_USER_ACCEPTANCE` was revoked after real user experience; SI2 and SI3 `READY_FOR_REAL_DATA_UAT`s were disproven by independent audits (leaked media/work/recognition/BI/Usage rows, IAM 85 active test accounts, BI physical row counts, 20 historical import batches polluting the operational plane).
- Three permanent lessons recorded: (1) isolation must use **effective scope** (own column ⊕ parent chain ⊕ attribution), not column-only COALESCE; (2) scanners must fail-fast (except/continue that swallows errors is a defect); (3) static gate.json needs **freshness binding** — Gate must be bound to HEAD + DB fingerprint (scope-graph aggregate / event watermark / projection hash / key-table counts) and re-evaluated live (`/api/v1/control/gate`); stale → `STALE_GATE_EVIDENCE`.
- **Current machine gate** `.eval/scope_v5/gate.json`: `"gate": "READY_FOR_REAL_DATA_UAT"`, **52 checks, 52 ok, reasons=[]**, source_commit == HEAD `8e31708d`, code-tree hash, migration hash, tracked-worktree-clean, fixture leakage zero, db_fingerprint (scope_graph `e284c223…`, event_watermark 731, outbox_pending 0, projection_hash…). Evaluator version 3.2.0; 12 negative tests all blocked correctly.
- Honest boundary (repeated in every STATUS): the machine gate can only emit READY_FOR_REAL_DATA_UAT or specific BLOCKED_*; **real-data UAT and human acceptance are performed by the user — until then nobody may write ACCEPTED/COMPLETE/PRODUCTION_READY**.

## 9. CODEX handbook — latest conclusions and next steps (near-verbatim)
Latest snapshot header (2026-08-12, now partially stale vs HEAD — must re-verify): HEAD `47c01c43`, migration 040, 8091 loading `prod_20260805_v5_r1`, Gate `OPERATIONAL_WORKBENCH_V3_NOT_STARTED`, sole entry `docs/implementation/agentic-business-os-operational-workbench-v3/`. This round authorized only the local `best/sku_v4_best.pt` switch after shadow/regression/rollback; no long training, no remote deploy, no merge/push.

Latest changelog entries (2026-08-13), condensed near-verbatim:
- **Scope Integrity V3 收口**: false-positive Gate downgraded+fixed; Scope Graph V3 / effective scope / attribution ledger / full-table Registry / Gate 3.0 freshness / UAT V5 48 items; hermetic 1425 passed, host MPS 6 passed.
- **Operational Scope V4 收口**: SI3 READY falsified again (IAM 85 active accounts / BI physical counts / frontend default values); IAM identity lifecycle (migration 057); BI/Finance effective basis (migration 058); Registry semantic layer; Gate 3.1 + 22 negatives; UAT V6 57/57; 12-page browser 30/30; hermetic 1447 passed.
- **Operational Scope V5 收口**: V4 READY falsified again (20 historical UAT import batches polluting operational plane / Import API over-reach / fake Registry semantics); batch = frozen execution context (migration 059 + multi-customer scope table); template permission matrix + per-customer whole-batch fail-closed + DTO whitelist; executable Registry (validator + scanner/archiver/filter/TestCenter/Gate all derived, parallel lists abolished); historical 20 reconciled (17 bind / 3 quarantine); Gate 3.2.0 (18 new checks + 12 negatives); UAT V7 real multipart Import Center 23/23; browser object-level 29/29; hermetic 1479 passed, host MPS 6 passed.

V5 nine methodology lessons (verbatim-ish, appended to handbook): (1) 表名进入 Registry ≠ 作用域治理完成 — module is only integrated when create/auth/operational-query/archive/test-center/BI/Gate/browser/evidence all driven by one executable policy; (2) Registry declarations must be machine-validated (pk/columns/parent edge/handler vs schema; fabricated declarations worse than missing); (3) parallel hardcoded lists are leak hotbeds — scanner/archiver/filters/stats/Gate derive from one source; (4) import batch is an execution-context carrier (frozen tenant/scope/test_run/actor/customer links; no multi-customer compression; no bypass via "no customer column"); (5) API responses need DTO whitelist (raw DB rows = payload leak; raw preview needs separate permission + redaction + row cap); (6) historical reconciliation prefers structured evidence; non-uniquely-attributable → quarantine fail-closed, never delete; (7) browser acceptance must be object-level (DOM rows/IDs == API; "page lacks token" is a false negative; same-hash navigation needs forced reload; CDP extraction must not swallow falsy); (8) UAT must traverse the entry it claims (import closure ⇒ real multipart through Import API); (9) Gate version single-defined and referenced across the whole chain (code/gate.json/API/Web/docs/validator/negatives) — doc/code version drift is itself a defect.

**Next step (current open round)**: `docs/implementation/operational-scope-v5-correction-v1/` (only BEFORE-STATE.md exists; baseline captured at HEAD `8e31708d`, all four services UP, gate = READY_FOR_REAL_DATA_UAT 52 checks at that HEAD). The session task list defines the correction backlog: P0-1 quarantine write-escape fix (red→fix→green); P0-2 first-password zero-persistence (`users_v1 initial_password_once`); P0 Gate evidence freshness binding (STALE_GATE_EVIDENCE closed loop); P1 quarantine human-adjudication state machine (API/permission/audit/UI); P1 customer-lineage backfill for 17 historical batches; P1 parallel-workflow timeout race (`TestParallelEngine.test_branch_timeout`); P1 single source of truth for reports (Gate checks/Registry/namespace/batch-ID drift); P2 nav scroll continuity (Import Center → System Admin); then full acceptance + final report + handbook update.

## 10. Legacy vs platform architecture (docs/handbook.md, architecture.md, structure.md)
- Legacy recognition cascade: YOLO detector (frozen sku_v4, mAP50=0.6887) draws boxes → 224x224 crop → ResNet18 classifier (208 classes) → rejection gate (conf≥0.6 AND top1-top2 margin≥0.05 → accepted; else unknown/needs_review). `__unknown__` top1 always needs_review regardless of confidence. Low-confidence → empty sku_id, needs_review=true.
- Legacy three-stage flow (structure.md): KB build (.kb/) + field photos (.field/) → labeling dual-mode (proposals/) → human gate (review_server :8090 / Label Studio) → approved/ → training → recognize :8091. Warehouse `.warehouse/db.sqlite` 8 tables, append-only triggers.
- ADRs: 01 VLM=teacher/YOLO=student; 02 human gate every photo; 03 native-first (Docker optional); 04 retrieval only recalls, verdict = hard-filter + VLM final review (never embedding top1); 05 append-only + read-only originals; 06 SQLite-first, PG-isomorphic; 07 labeling dual mode (seed vs from-scratch); 08 cascade (frozen detector + dynamic classifier, `finetune.py` head-only lr=1e-4).
- Platform layer: `src/platform/` (kernel, api/, agents, iam, scope/scope_registry, gate_evaluator, import_center, workflow, worker, model_runtime, finance, survey, analytics, field_ops, home_center, control_plane, projection, reconciliation, standard_profile, test_data), `src/modules/` (fmcg, reference_echo, training_control, training_gov, nextgen_data, dataset_factory, labeling, system_health), `src/composition/serve.py` (app), `web/` React (pages + platform), built to `web/dist`. Cross-module only via API/Capability/DomainCommand/events/DataProduct/ResourceRef/WorkItemProjection; agents have no arbitrary SQL/shell/FS access.

## Risks
- Doc drift at the top of the chain: CODEX-PROJECT-HANDBOOK.md latest snapshot (2026-08-12) says migration 040 / bundle prod_20260805_v5_r1 / Gate OPERATIONAL_WORKBENCH_V3_NOT_STARTED, but live state at HEAD 8e31708d is migration 059 / prod_v4_best_r1 / READY_FOR_REAL_DATA_UAT — handbook itself warns snapshots must be re-verified; treat it as index only (docs/CODEX-PROJECT-HANDBOOK.md lines 9-27 vs .models/bundles/CURRENT.json and src/platform/data/store.py)
- Root README.md is stale: claims training status NO-GO and points to the 2026-08-05 execution manual as the current entry (README.md lines 5-9); docs/README.md 'current status' sections are from 2026-08-08/09 and name operational-workbench-v3 as the sole entry even though scope v3/v4/v5 + correction rounds have since run (docs/README.md lines 3, 113-156)
- The current READY_FOR_REAL_DATA_UAT gate (.eval/scope_v5/gate.json, 52/52 at HEAD 8e31708d) was produced BEFORE the correction-round findings; the session task list records open P0 defects (quarantine write escape, first-password zero-persistence, gate freshness binding, parallel-workflow timeout race), so the green gate does not reflect known issues — per the project's own rules any new code change makes it STALE_GATE_EVIDENCE and it must be regenerated
- No AGENTS.md exists anywhere in the repo (find maxdepth 3 empty) — agents rely entirely on docs/CODEX-PROJECT-HANDBOOK.md + per-round AGENT-EXECUTION-PROMPT.md for continuity
- Platform migrations exist only in code (src/platform/data/store.py) — the target layout in the handbook (§4.2: migrations/platform/ + migrations/modules/<module_id>/) is not realized; migrations/sqlite and migrations/postgres only hold the legacy warehouse schema
- A stale worktree exists at .claude/worktrees/upbeat-archimedes-158fe1 (branch claude/upbeat-archimedes-158fe1, commit 3f559911) recorded in BEFORE-STATE.md; reading files from it would give wrong project state
- conftest.py warns src/common/config.py injects .env (production credentials PLATFORM_ADMIN_CREDENTIALS) into os.environ at import — any test that forgets the monkeypatch inherits production auth values; the autouse fixture pops them but test authors must still set explicit values

## Open questions
- Where is the authoritative current-round README/task book for operational-scope-v5-correction-v1? The directory only contains BEFORE-STATE.md — the task backlog appears to live in the session task list, not yet in a committed AGENT-EXECUTION-PROMPT.md
- What is the exact behavior of /api/v1/control/gate live re-evaluation when the correction-round code changes land — does it downgrade to BLOCKED_BY_P0 automatically (as osv5_gate_evaluate.py did) or require regeneration of .eval/scope_v5/gate.json?
- Whether docs/README.md and root README.md will be updated as part of correction-v1's final governance closure (task #10 mentions handbook update only)
- Legacy services 8301/8304/8090 current run state is undocumented at HEAD 8e31708d (bin/abos only manages 8091/8092/8300/8400)