# Parallel workflow engine (UATCC T3) — state machine, timeout race in TestParallelEngine.test_branch_timeout, finalize semantics, restart recovery

## Key files
- src/platform/workflow.py — the entire parallel engine: _exec_parallel (991-1235), _worker (1097-1117), _branch_row (921-937), finalize_run CAS (677-778), recover_interrupted_parallels (1237-1281), inline branch wait/heartbeat (1490-1509)
- tests/platform/test_uatcc_parallel_engine.py — TestParallelEngine: test_branch_timeout (126-142), walltime (84-96), restart recovery (144-182)
- src/platform/data/store.py — workflow_branch_v1 DDL (2000-2012), RUN_TRANSITIONS (3840-3851), set_business_run_status SELECT-then-UPDATE (3897-3937), thread-local autocommit connections (2337-2362)
- src/platform/api/app.py — _timer_poller daemon thread (268-283): startup-only recover_interrupted_parallels + 10s resume_due_timers loop

## Findings
## 1. State machine as implemented

**Run level** (`business_run_v1`): `queued → running → {waiting_timer | waiting_human | paused} → running → terminal`. Allowed transitions enumerated in `RUN_TRANSITIONS` (src/platform/data/store.py:3840-3851); terminal set is `TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")` (src/platform/workflow.py:661). Terminal states are written ONLY via the CAS in `finalize_run` (workflow.py:704-708) from the workflow path — no call site writes a terminal status through `set_business_run_status` (verified by grep). `failed → running` is allowed (retry), `succeeded/cancelled` are sinks.

**Branch level** (`workflow_branch_v1`, DDL at store.py:2000-2012 — plain TEXT status column, no CHECK constraint): `pending` (inserted at `_exec_parallel` workflow.py:1036-1045 and 1056-1065) → `running` (`_branch_row` at worker start, workflow.py:1099) → terminal `{completed | failed | timeout | cancelled}`. Nothing enforces terminality at branch level — every branch terminal write is a re-writable unconditional UPDATE.

## 2. How run finalize sets branch terminal states

`finalize_run` (workflow.py:677-778):
1. CAS run status: `UPDATE business_run_v1 SET status=?, ... WHERE run_id=? AND status NOT IN ('succeeded','failed','cancelled')` (workflow.py:704-708); rowcount==0 → no-op return False (first finalizer wins; terminals never overwrite each other).
2. Converges side state: main work item (662-663 mapping succeeded→done/failed→blocked/cancelled→cancelled), approval sub-todos (720-725), pending timers → cancelled (727-730), then **unfinished branches → cancelled** (workflow.py:731-736):
```sql
UPDATE workflow_branch_v1 SET status='cancelled', ended_at=?,
 error=CASE WHEN error='' THEN 'run 终态收敛' ELSE error END
 WHERE run_id=? AND status IN ('pending','running')
```
This sweep IS guarded — it cannot overwrite an already-written `timeout`/`failed`/`completed`. Node executions are likewise swept (741-748). Note: the docstring claims "同一事务内收敛" but the store connection is `autocommit=True` (store.py:2348) with no explicit BEGIN, so each statement self-commits — the convergence is NOT atomic; a crash mid-finalize leaves partial convergence.

## 3. The races (quoted with file:line)

**Race A — unconditional branch UPDATE (the test flake root cause).** `_branch_row` (workflow.py:921-937) has no status guard:
```python
self.store._conn.execute(
    f"UPDATE workflow_branch_v1 SET {', '.join(sets)}"
    " WHERE branch_id=?", (*vals, branch_id))   # workflow.py:934-936
```
Any writer can overwrite any terminal branch state, last-writer-wins.

**Race B — scheduler timeout sweep vs worker.** In `_exec_parallel` (workflow.py:1135-1149):
```python
done_set, pending = wait(pending, timeout=timeout or None,
                         return_when=FIRST_COMPLETED)   # 1136-1138
if not done_set:
    for f in pending:                                     # 1141
        b = futs[f]
        self._branch_row(b["branch_id"], "timeout",
                         error="branch_timeout")          # 1143-1144
```
`pending` is the set of not-yet-done futures observed at `wait()` return; between that observation and the UPDATE (and afterwards), a worker can complete and write `completed` via Race A, which the timeout sweep then overwrites — or the worker overwrites `timeout` later. SELECT(pending-set)-then-UPDATE with no re-check.

**Race C — true SELECT-then-UPDATE at run level.** `set_business_run_status` (store.py:3897-3937): SELECTs current status (store.py:3905-3907), validates against `RUN_TRANSITIONS` (3911), then UPDATE with only `WHERE run_id=?` (store.py:3933-3935) — no `AND status=cur` condition. Two concurrent writers (e.g. `pause_run`/timer-fire/`waiting_timer` transitions vs `cancel_run`'s finalize) can both pass validation and both write; last writer lands the run in a state the matrix forbids. `finalize_run`'s CAS (workflow.py:704-708) is the only guarded run-status write.

## 4. Timeout detection: scheduler-side only

Timeouts are detected ONLY by the main/scheduler thread via `concurrent.futures.wait(..., timeout=branch_timeout_seconds, return_when=FIRST_COMPLETED)` (workflow.py:1136-1138); empty `done_set` ⇒ remaining branches marked `timeout` (1139-1149). Workers have NO deadline awareness: the in-branch inline wait (workflow.py:1490-1509) sleeps its full `seconds` with a 0.05-0.5 s heartbeat loop that only checks run-cancel (`_ensure_run_active`, workflow.py:669-675). On timeout the pool is abandoned with `ex.shutdown(wait=False, cancel_futures=True)` (workflow.py:1173-1174) — already-running branch threads keep running and can still write branch rows afterwards. Semantics drift: the timeout restarts fresh on each `wait()` iteration, so it is an "idle-since-last-completion" timeout, not an absolute per-branch deadline from branch start.

## 5. 'cancelled' vs 'timeout' priority

None is declared; behavior is asymmetric last-writer-wins:
- `finalize_run`'s sweep (workflow.py:735-736) is guarded by `status IN ('pending','running')` → a branch already marked `timeout` SURVIVES run finalization.
- All `_branch_row` writers (timeout, cancelled, completed, failed) are unconditional → a later timeout write can overwrite `cancelled`, and a later worker write can overwrite `timeout`.
- Join accounting treats `timeout` as failure (`failed = ... status in ("failed","timeout")`, workflow.py:1181-1182) while `cancelled` is neutral — cancelled only occurs after any/quorum is already met (1162-1172), on run-cancel (1109-1112), or via finalize sweep. So under `mode=all` any timeout fails the run (len(ok)<need → WorkflowError, workflow.py:1183-1194).

## 6. test_branch_timeout timing assumptions → flake mechanism

Test (tests/platform/test_uatcc_parallel_engine.py:126-142): two 3 s `wait` branches, `branch_timeout_seconds=1`, `mode=all`; asserts run `failed`, wall < 3, and `"timeout" in statuses` queried right after `start_run` returns.

Timeline: t≈1 s scheduler marks both branches `timeout`, raises WorkflowError → `_fail_node` → `finalize_run("failed")` (branch sweep skips them — already terminal). Test then SELECTs statuses. But the two worker threads are still inside the 3 s sleep: their heartbeat (`_ensure_run_active` every ≤0.5 s, workflow.py:1497) raises `WorkflowCancelled` ≤0.5 s AFTER the run becomes terminal, and `_worker`'s except handler (workflow.py:1109-1112) writes `cancelled` over `timeout` via the unguarded `_branch_row`. If they instead reach the sleep deadline (t≈3 s) they write `completed` (workflow.py:1106-1107). The test passes only if its SELECT lands in the window between the timeout write and the first post-finalize heartbeat — normally microseconds vs ~500 ms, but under full-suite load (GIL contention, pytest-xdist workers, WAL busy retries on the per-thread connections, `finalize_run`'s long non-atomic tail incl. `rebuild_work_projection`, thread starvation delaying the main thread's SELECT) the main thread can stall past the heartbeat and see `{'cancelled'}` (or `{'completed'}` at t>3 s) → assertion `"timeout" in statuses` fails. Secondary assumption: `wall < 3` is measured around the WHOLE `_publish_run` (draft+lint+simulate+approve+publish+start_run), leaving only ~2 s of headroom for the publish pipeline under load; `test_walltime_two_branches` (wall < 3.5 for 2×2 s branches, line 92) has the same shape with 1.5 s headroom and false-flags "serial" under contention even when genuinely parallel.

## 7. Restart-recovery behavior

`recover_interrupted_parallels()` (workflow.py:1237-1281), invoked once at API startup by the `_timer_poller` daemon thread (src/platform/api/app.py:268-283) — NOT on the 10 s poll loop, which only runs `resume_due_timers`:
- SELECTs run_ids having branch rows in `('pending','running')` (GROUP BY run_id), keeps only runs with status=='running'.
- Rebuilds ctx via `_restore_ctx` (replays trigger inputs + transform `_vars` from node-execution checkpoints, workflow.py:1685-1718) and re-enters `_exec_parallel(..., resume_rows=brows)`.
- Resume semantics: branches with durable status `completed` are skipped and their results restored from rows (workflow.py:1086-1095); EVERY other branch (pending/running — and failed/timeout/cancelled if such rows exist in the run) is re-executed from its entry node. At-least-once, branch-granularity; no idempotency keys on branch-internal command side effects.
- After join, continues join successors via `_run_nodes`. Per-run failures are swallowed silently (`except Exception: continue`, workflow.py:1279-1280) — a persistently failing recovery leaves the run stuck `running` forever with no dead-letter and no retry (startup-only invocation).
- No claim/lock on the SELECT: two concurrent recoverers (multi-process, or startup + manual call) would both pick the same rows and execute branches twice.

## 8. Every terminal-state transition site (exhaustive)

Branch (`workflow_branch_v1`) — all via `_branch_row` (workflow.py:921-937) except #8:
1. workflow.py:1106-1107 — worker success → `completed`
2. workflow.py:1111-1112 — worker `WorkflowCancelled` → `cancelled`
3. workflow.py:1115-1116 — worker exception → `failed`
4. workflow.py:1123-1124 — simulate fast-path → `completed`
5. workflow.py:1143-1144 — scheduler timeout sweep → `timeout`
6. workflow.py:1155-1156 — scheduler `f.result()` raise → `failed`
7. workflow.py:1167-1168 — any/quorum met, remainder → `cancelled`
8. workflow.py:731-736 — `finalize_run` raw SQL sweep → `cancelled` (guarded `pending/running`)
(in-memory only: results dict entries at 1145-1147, 1169-1170)

Run (`business_run_v1`) terminal writes:
9. workflow.py:704-708 — `finalize_run` CAS, callers: `_run_nodes` success 1396-1399, `_fail_node` 1439-1441, `cancel_run` 655-657, `approve_run` rejection 610-612
10. store.py:3933-3935 — `set_business_run_status` unguarded UPDATE (can carry terminal statuses; no workflow.py call site does today, but the path is open and non-CAS)

## Risks
- Unguarded branch terminal writes (workflow.py:934-936): _branch_row UPDATE has no 'AND status IN (...)' guard, so completed/cancelled/failed can overwrite 'timeout' and vice versa — direct cause of test_branch_timeout flake and of misleading durable states in production
- Abandoned worker threads remain live after shutdown(wait=False) (workflow.py:1173-1174) and keep writing branch rows + committing on their own connections for up to the full wait duration; results are discarded but durable state is not fenced
- finalize_run claims same-transaction convergence but store connections are autocommit=True (store.py:2348) with no explicit BEGIN — crash mid-finalize yields partially converged work items/timers/branches/node rows
- set_business_run_status (store.py:3905-3935) is a TOCTOU SELECT-then-UPDATE with unconditioned UPDATE; concurrent pause/cancel/timer-fire can land illegal run transitions (finalize_run's CAS is the only guarded writer)
- recover_interrupted_parallels has no claim/lock (double-recovery → duplicate branch execution), silently swallows per-run failures (workflow.py:1279-1280), and runs only at API startup — a run whose recovery keeps failing is stuck 'running' forever with branches left pending/running
- Recovery re-runs ALL non-completed branches including previously failed/timed-out ones (workflow.py:1086-1087, todo excludes only 'completed'), and re-execution duplicates side effects of command/model nodes inside branches (at-least-once with no idempotency keys)
- test_walltime_two_branches measures the publish pipeline inside its wall budget (tests/platform/test_uatcc_parallel_engine.py:88-92), so non-engine overhead can produce false 'serial execution' failures under load

## Open questions
- Desired semantics for branch_timeout_seconds: absolute deadline per branch vs current idle-since-last-completion (per wait() call) timeout — affects whether wait-loop timeout should be computed against each branch's started_at
- Intended durable end-state of a timed-out branch whose worker later observes run-terminal (currently flips to 'cancelled') or finishes (flips to 'completed') — i.e., should 'timeout' be sticky
- Whether recover_interrupted_parallels should also run on the 10s poll (currently startup-only) and whether failed recoveries should dead-letter instead of silent continue