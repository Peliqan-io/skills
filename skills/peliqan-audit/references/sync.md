# Audit: sync workers

Checks a **live** sync worker that nobody has reported as broken yet. The worker
is a single data-app built by the `peliqan-sync` skill: one file per system
pair, all syncs driven from `process_all()`, on a shared framework (link table +
bookmarks + hash idempotency + error containment).

The yardstick is the framework contract. Before scoring anything, read
`../../peliqan-sync/references/framework-contract.md` (implemented by
`../../peliqan-sync/assets/worker_template.py`), the "Keep the scaffold lean"
section of `../../peliqan-sync/references/worker-build.md`, the "Sync rules" of
`../../peliqan-sync/references/sync-build.md`, and
`../../peliqan-sync/references/systems/<system>.md` for both systems of the
pair.

Two audits, pick by the question:

| | **A. Contract check** (Steps 1–5) | **B. Reconciliation** (part B) |
|---|---|---|
| Question | Is this worker built and configured per the contract, and healthy? | Does the target still match the source for what the syncs own? |
| Where it runs | Here: offline on the script + read-only MCP calls | Inside the worker (`audit_all`, contract §12) |
| Output | A scorecard in the chat | Rows in `audit_{PAIR}`, read back here |

"Audit the worker / is it ready / review the setup" → A. "Are records missing /
find the drift / which orders never arrived" → B. Both together for a go-live.

Audit vs. support: support starts from a symptom ("orders don't arrive") and
finds its cause. Audit starts from nothing and looks for the problems that have
not surfaced yet. If the audit turns up an active incident, say so and hand it
to `peliqan-support`.

## Ground rules

- **Read-only.** List, read and query only. Never `run_data_app`,
  `update_data_app`, `set_bookmark`, `replay_source`, a delete reconciliation,
  or any write to the source or target. A run is a write. The one exception is
  part B: with the user's go-ahead, set the audit request in the worker's state;
  the worker then writes its findings to its own `audit_{PAIR}` table.
- **Local offline checks are fine.** Saving the worker's script locally and
  running `py_compile` and `../../peliqan-sync/scripts/test_bookmarks.py` on it
  touches nothing in the account.
- **Evidence for every score.** Each pass/warn/fail cites a code line, a log
  line or a row count. No evidence → `n/a` with what would decide it.
- **A skip is not a finding.** `no change in hash -> skip` is the idempotence
  proof working.
- **Lean is not a finding.** A sync-empty scaffold shipping the unused helper
  API is the contract. Missing custom-fields code with an empty
  `CUSTOM_FIELDS` is correct.

## Step 1 — Inventory

`list_data_apps` (filter names on `sync|worker`), then `get_data_app` for each
worker in scope. Save `raw_script` locally. Record per worker: `PAIR`,
`FRAMEWORK_VERSION`, `WORKER_VERSION` + the changelog block, the
`SYNC_REGISTRY` entries in order, and `SYNCS_ENABLED`, `TEST_LIMIT`,
`MAX_ATTEMPTS`. A pre-v5 worker may also have `MULTI_STORE`; if it is `True`,
check that every `find_*` and `insert_link_row` passes `store_id`/`company_id`
(**fail** if not: duplicates).

## Step 2 — Code against the contract

| # | Check | Pass when | Severity if not |
|---|---|---|---|
| C1 | Framework version | `FRAMEWORK_VERSION` equals the template's (`"6"`) | **fail** below 4 (strict `>` loses records), else warn. A `"5"` is one of two lines (contract v6 note): say which |
| C2 | Incremental filters | Self-written filters use `>=`; connector `list(bookmark=)` gets `bookmark_with_overlap` | **fail** |
| C3 | Bookmark advance | `advance_bookmark` only over the contiguous processed prefix; orphan-freeze on a parent dependency | **fail** |
| C4 | Schema bootstrap | `ensure_schema` does DDL → `pq.refresh_schema` → fetch-probe → raises; `process_all` runs no syncs on failure; link table never created with `dbconn.write()` | **fail** |
| C5 | Hash coverage | `stable_hash` over exactly the fields this sync owns; no `str(a)+str(b)` | warn (missed updates or needless rewrites) |
| C6 | 6-step record path | Each `process_<record>` validates, looks up, hash-skips, checks `is_ok` (and `graphql_user_errors` for GraphQL), and appends a link row on success **and** failure | **fail** for a missing response check or link row |
| C7 | Error containment | Per-record try/except in the loop that records a row and continues | **fail** |
| C8 | Link-insert retry | The 3× retry plus error-row fallback around the link-row insert | **fail** (silent duplicates) |
| C9 | Link id guard | Monotonic `_next_link_id`, not bare `time.time_ns()` | **fail** |
| C10 | Registry order | Parents before children; Shopify→Odoo before Odoo→Shopify | **fail** if a child can run before its parent |
| C11 | Link cache | `prefetch_links` per page with write-through in `insert_link_row` | warn (slow) / **fail** if a child reads a stale cache |
| C12 | Loud source reads | `is_ok` rejects `detail.error` and `detail.errors`; every drain raises on a response that is not ok, and no page cap returns a partial, unsorted set | **fail** (a broken read looks like "0 records" with a green run, or the bookmark skips unread records) |
| C13 | Run summary | Every run-summary tuple has the same arity, including the disabled-sync branch | **fail** (crashed a live run) |
| C14 | Bookmark test | `python ../../peliqan-sync/scripts/test_bookmarks.py <worker.py>` passes; the four pure helpers are present | **fail** |
| C15 | Compiles | `py_compile` clean | **fail** |
| C16 | Traceability | `WORKER_VERSION` and a dated changelog at the top | warn |
| C17 | Warehouse-sourced syncs | A sync that reads a pipeline table uses `dwh_drain` with `bookmark_with_overlap(..., seconds=<at least one pipeline interval>)`, or bookmarks on the table's own load timestamp; its header comment records table, `ts_field`, interval and overlap | **fail** without the overlap (pipeline lag loses records silently) |
| C18 | Targets | Every sync writes to the other system, not to a warehouse table, unless the changelog or header records that the dev asked for it (contract §7a) | warn |

## Step 3 — Configuration

| # | Check | Pass when | Severity if not |
|---|---|---|---|
| K1 | Test limit | `TEST_LIMIT` is `None`/`0` on a worker meant to be live | warn (caps every run, looks like a stalled sync) |
| K2 | Disabled syncs | Every sync off in `SYNCS_ENABLED` is off on purpose (ask) | warn |
| K3 | Connections | The connection names in the script exist (`list_connections`) | **fail** |
| K4 | System references | Both systems have a `references/systems/<system>.md` with every checklist row answered | warn; unanswered rows are open questions |
| K5 | Sandbox isolation | A sandbox copy has its own `PAIR`, so it has its own link table and bookmarks | **fail** if it shares the production `PAIR` |

## Step 4 — Runtime health

From `get_data_app_runs`, `get_data_app_run_logs` on the last runs, and the
worker's own tables (`get_table_data` or a query table):

| # | Check | Pass when | Severity if not |
|---|---|---|---|
| R1 | Recent runs | Runs on the expected cadence, no aborted runs | **fail** on aborts |
| R2 | Bookmarks | Each sync's bookmark moves when its source has newer records | **fail** if frozen while newer source records exist |
| R3 | Errors | Error rows per sync are not growing run over run | warn; **fail** when growing |
| R4 | Dead letters | `v_dead_letter_{PAIR}` empty, or every row known and explained | warn |
| R5 | Duplicates | No source id with several `ok` link rows pointing at different target ids | **fail** |
| R6 | Duration | Run duration in line with records processed | warn |
| R7 | Source freshness | For a warehouse-sourced sync: the `max(ts_field)` freshness line in the run log is recent, and the pipeline feeding it runs green (`get_connection_pipeline_runs`) | **fail** when the pipeline stopped: the sync reads nothing new while looking healthy |

Useful queries on `{LINK_SCHEMA}.{LINK_TABLE}`: counts grouped by `sync_name`,
`status`; the latest `timestamp` per sync; and, for R5, `ok` rows grouped by
`sync_name` + source id having more than one distinct target id.

## Step 5 — Report

Start with a one-line verdict: **ready**, **ready with warnings**, or **not
ready**. Any **fail** means not ready.

Then a scorecard, one row per check:

| # | Check | Result | Evidence |
|---|---|---|---|
| C2 | Incremental filters | fail | `L212: updated_at > '{bookmark}'` in `fetch_changed_orders` |

Then the findings, most severe first. For each: what is wrong, what it can cost
(lost records, duplicates, a crashed run, a slow run), and the fix, routed to
the right skill:

- code or framework changes → `peliqan-sync` (framework upgrade per contract §11
  for C1);
- an active incident (R2, R3, R5 failing) → `peliqan-support`.

Close with the open questions (unanswered system checklist rows, syncs whose
off-switch nobody could explain). Never apply a fix from this skill.

## Part B — Reconciliation audit (in the worker)

Needs framework v6 (or the claude.ai v5 line); the worker does the reading, so
the source and target are compared with the sync's own mapping.

**What every worker already does.** With nothing extra registered,
`audit_all()` records the **backlog** per sync: ids whose latest link row is
`source_error`, `target_error` or `dead`. For many accounts that is the whole
audit they need; say so before proposing code.

**Per-sync checks** need an `audit_<sync>()` in the worker, registered as
`"audit": audit_<sync>` (built through `peliqan-sync`, example in
`../../peliqan-sync/assets/sync_examples/dwh_and_audit.py`):

- **missing:** source ids with no `ok` link row. One SQL when the source is a
  pipeline table; for an API source, drain ids and timestamps only and take the
  set difference. Scope it like the sync (a sync that only pushes active
  products must not report drafts as missing).
- **drift:** for the newest `AUDIT_LIMIT` `ok` links, run the sync's own
  `fieldmapping_*` on the current source record and compare the owned fields
  with the current target record. Reads only; bounded, because it costs one
  target read per record.
- **orphan:** `ok` links whose source record is gone. Only meaningful when the
  source channel shows deletes (a pipeline table that keeps deleted rows can't).

An audit fn never calls `insert_link_row`, `set_bookmark` or a write to either
system, and every loop is bounded by `AUDIT_LIMIT`.

**Trigger** (ask first; it changes the worker's state):
`update_data_app_state` with `{"audit": {"requested": true}}`, optionally
`"syncs": [...]`. The audit runs at the end of the worker's **next scheduled
run**. Don't `run_data_app` to speed it up unless the user explicitly asks: that
also runs every sync. A standing audit is `AUDIT_EVERY_N_RUNS` in the worker
(e.g. 24 on an hourly worker = daily), set through `peliqan-sync`.

**Read** `v_audit_latest_{PAIR}` (one `run_at` = one audit) and the run log's
Audit block. Report findings per sync and check, then hand them over:

| Finding | Goes to | Usually |
|---|---|---|
| `missing` with a backlog row | `peliqan-support` | fix the cause, then replay |
| `missing` with no link row at all | `peliqan-support` | bookmark rewind to before the record (for a pipeline source: is the overlap at least one interval?) |
| `drift` | the dev decides who is right | a manual edit in the target, or a partial write; re-push or accept |
| `orphan` | the dev | the delete-semantics decision the sync deferred |

Cost: backlog is free; missing and orphans are one set difference per sync;
drift is the expensive one, so keep `AUDIT_LIMIT` modest and audit a bounded
window, never the whole target every run.

## Notes

- If the Peliqan MCP isn't connected, say so and stop. An audit of a pasted
  script alone can cover Step 2 only, so label it a code review, not an audit.
- An older hand-built worker (`link_tables.link_table` / `sync_runs`) predates
  the contract. Score it the same way; most of Step 2 will fail, and the fix is
  a framework upgrade, not a list of patches.
