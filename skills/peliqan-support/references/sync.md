# Support: sync workers

Troubleshoots a **live** Peliqan sync worker. The worker itself is a single
data-app built by the `peliqan-sync` skill: one file per system pair, all syncs
driven from `process_all()`, on a shared framework (link table + bookmarks +
hash idempotency + error containment). Every diagnosis here is against that
framework's contract — read `../../peliqan-sync/references/framework-contract.md`
before concluding anything about bookmarks, link rows or statuses, and the
pair's `../../peliqan-sync/references/systems/<system>.md` before blaming a source or target
system's behaviour.

## Ground rules

- **Diagnose read-only first.** Listing apps, reading code, reading run logs and
  querying the link/run tables are always fine. Rewinding a bookmark, replaying
  rows, reconciling deletes, editing the worker or redeploying it are **not** —
  each needs the developer's explicit go-ahead, because each one moves customer
  data in a live account.
- **Never touch customer records directly.** Fixes go through the worker
  (replay, rewind, code change, redeploy), never through hand-written writes
  into the source or target system, and never through raw DML against the link
  table.
- **Evidence before theory.** Every root cause must be backed by a specific log
  line, a row count, or a line of the worker's code. If the evidence isn't
  there, say the diagnosis is unconfirmed and name what would confirm it.
- **A skip is not a bug.** `no change in hash -> skip` is the framework's
  idempotence proof working as designed. Never report it as a failure.
- **Don't hand-patch the framework.** If the worker's `FRAMEWORK_VERSION`
  predates the contract, the fix is an in-place framework upgrade via
  `peliqan-sync` (contract §11), not a local edit to one helper.

## Step 1 — Find the worker and read its constants

`list_data_apps`, then `get_data_app` on the one in question (ask which if the
name is ambiguous; a pair name like `shopify_odoo` is usually in it). From the
top of the file, record:

- `FRAMEWORK_VERSION` — decides which known bugs apply (see Step 4).
- `PAIR`, `LINK_SCHEMA`, `LINK_TABLE`, `RUNS_TABLE` — the state tables to query.
  Legacy hand-built workers use `link_tables.link_table` / `sync_runs`.
- `SYNCS_ENABLED` — **check this first.** A sync switched off here is the single
  most common false alarm; the run caption also lists which syncs are OFF.
- `TEST_LIMIT`, `MAX_ATTEMPTS`: a non-zero `TEST_LIMIT` left in place caps
  every run and looks exactly like "the sync stopped halfway".
- The registration tuples in `process_all` — which syncs exist, in what order,
  and which have a parent dependency.

Use `get_data_app_context` and `get_data_app_state` when the run depends on
connection or state values that aren't in the file.

## Step 2 — Read the last runs

`get_data_app_runs` for the recent history, then `get_data_app_run_logs` on the
last good run and the first bad one. In the run summary, read:

- Per-sync **status, duration, processed / errors / skipped**.
- The **Bookmarks** block: `before -> after` or `unchanged`. This is the highest
  signal line in the whole log — `unchanged` means either "nothing new upstream"
  or "frozen", and nothing else distinguishes those two.
- The caption listing disabled syncs.
- Whether `ensure_schema` raised (if it did, no syncs ran at all).

Compare the first bad run against the last good one rather than reading the bad
run alone — what changed between them is usually the answer.

## Step 3 — Query the worker's own state tables

Through the warehouse (`get_table_data`, or a query table):

- `v_run_summary_{PAIR}` — run history at a glance.
- `v_dead_letter_{PAIR}` — poison rows that stopped retrying at `MAX_ATTEMPTS`.
- Status counts per sync: rows in `{LINK_SCHEMA}.{LINK_TABLE}` grouped by
  `sync_name`, `status`, latest `timestamp`, plus a sample of `error_detail`.
  Statuses are `ok`, `source_error`, `target_error`, `dead`.
- For a "record didn't arrive" report: the link rows for that specific id
  (`shopify_id` / `odoo_id` as named for this pair) in `sync_name` order —
  effective link is the latest `ok` per (sync_name, id). Whether the id has no
  row at all, an error row, or an `ok` row the target then lost, are three
  different bugs.

The table is append-only, so history is intact — use `attempt` and `timestamp`
to see whether a failure is new, retrying, or long dead.

## Step 4 — Match symptom to cause

| Symptom | Likely cause | Confirm with | Fix |
|---|---|---|---|
| Sync produced nothing, no errors | Disabled in `SYNCS_ENABLED`, or `TEST_LIMIT` still set | Run caption, constants | Flip the flag / clear the limit |
| Bookmark `unchanged`, source clearly has newer records | Orphan-freeze: a parent dependency never linked, so the child can't advance | Parent sync's link rows for that record — missing or error | Fix/replay the parent sync first, then the child |
| Records permanently missing after a run that was truncated (crash, page cap, `TEST_LIMIT`) | Pre-v4 strict `>` bookmark filter dropping the equal-second tail (live incident 2026-07-15) | `FRAMEWORK_VERSION` < 4 | Upgrade the framework block to v4 (`>=` drain rule) via `peliqan-sync`, then rewind the bookmark to just before the truncated run |
| Same records failing every run, `attempt` climbing, then `dead` | Real functional rejection by the target (validation, permissions, missing related record) | `error_detail` on the latest rows; the target's `references/systems/<system>.md` failure modes | Fix the mapping or the target-side prerequisite, then `replay_source` |
| Target returned 200 but nothing was written | Functional error hidden in a successful response (GraphQL `userErrors`, Odoo fault in a 200) | Whether the record function checks `graphql_user_errors` / `is_ok` | Add the check per contract step 5, redeploy, replay |
| Sync reported FAILED with `source_error: ... ACCESS_DENIED` or an Odoo fault name (`builtins.ValueError`, `AccessError`) | The source refused the read: missing permission (Shopify Protected Customer Data, API scopes), or a module/field that doesn't exist on the target instance | The error text in the run log; the failure modes in the system's `references/systems/<system>.md` | Fix the access or the field. The bookmark did not move, so the sync catches up on its own once fixed |
| A pre-v5 worker reads "0 records" while the source clearly has changes | `is_ok` without the `detail.error` / `detail.errors` check, so a failed read looked empty | `FRAMEWORK_VERSION` < 5; run a read by hand to see the error | Upgrade the framework block to v5 via `peliqan-sync` |
| Sync FAILED with `hit max_pages` | More changed records since the bookmark than the drain's page cap | The count in the message | Raise `max_pages` for that drain, or narrow it with `extra_filter`, via `peliqan-sync` |
| Everything reported as skipped | Hash-skip on unchanged records — healthy | `no change in hash -> skip` lines | Nothing; report as working |
| "Worker aborted unexpectedly" / `ValueError` on unpack | Run-summary tuple arity differing on the disabled-sync branch | The `SYNCS_ENABLED` branch in `process_all` | Make every run-summary tuple the same arity |
| Writes fail with the table missing, or `dbconn.insert/fetch` can't see it | Raw DDL without catalog registration — `ensure_schema` must DDL → `refresh_schema` → fetch-probe | Whether `ensure_schema` raised in the log | Restore contract-compliant `ensure_schema` |
| Duplicates in the target | A link lookup missing from the record function; a second app (often a sandbox copy) writing with the same `PAIR`; a link row lost after a successful write; or, on a pre-v5 multi-store worker, `store_id` / `company_id` not passed | Multiple `ok` rows for one source id with different target ids; `list_data_apps` for another app with the same `PAIR`; "Could not write link row" warnings in the log | Fix the cause (own `PAIR` per sandbox, restore the lookup or the link-insert retry), then reconcile the duplicates with the developer |
| Run suddenly slow, hundreds of queries for few writes | `prefetch_links` not called per page, or a pre-v5 framework without the link cache | Duration in the run summary vs processed count | Call `prefetch_links` per page for the sync and its parents (contract §3) |
| A child sync treats records as orphans although the parent sync linked them in the same run | `insert_link_row` not writing `ok` rows through to the link cache (a hand-edited framework) | The registration order and `insert_link_row` against the template | Restore the template's `insert_link_row` (correctness, not speed) |
| A warehouse-sourced sync: run green, bookmark `unchanged`, but the source system has newer records | The pipeline feeding the table stopped or lags; the drain reads nothing new | The `max(ts_field)` freshness line in the run log; `get_connection_pipeline_runs` for that pipeline | Fix the pipeline; the sync catches up on its own (no rewind needed) |
| A warehouse-sourced sync silently misses some records that are in the table now | Pipeline lag: the record landed after the bookmark had passed its timestamp, and the overlap is shorter than one pipeline interval (or missing) | The sync's `bookmark_with_overlap(..., seconds=)` vs the pipeline schedule; the record's timestamp vs the bookmark history | Set the overlap to at least one interval (or bookmark on the table's load timestamp) via `peliqan-sync`, then rewind to before the oldest missed record |
| Sync FAILED with `source_error: dwh_drain(...)` | The pipeline table was renamed, moved or isn't registered | The table name in the sync vs `list_tables` | Point the sync at the right table via `peliqan-sync` |

If the symptom isn't in this table, work it from the contract's 6-step
per-record path: which of validate → lookup → build → send → handle response →
append link row did the record last reach? The link row's `status` and `action`
answer that directly.

**Coming from an audit.** Findings in `v_audit_latest_{PAIR}` (from the
`peliqan-audit` reconciliation) arrive here as work: `missing` with a backlog
row → fix the cause, then replay; `missing` with no link row → a bookmark rewind
to before the record; `drift` and `orphan` → the developer decides first (who is
right; which delete semantics), then the fix goes through `peliqan-sync`.

## Step 5 — Propose the fix, then wait

Report before acting (see Step 7 for shape). For anything that changes state,
state plainly what it will do and get a yes:

- **Replay** — `replay_source(sync_name, process_one, statuses=, include_dead=,
  limit=)` re-drives error/dead rows from the stored source JSON. Preferred
  first remedy: it's bounded and idempotent. Only after the underlying cause is
  fixed, otherwise it just re-fails and burns attempts toward `dead`.
- **Bookmark rewind** — `set_bookmark` to just before the suspect window.
  Re-reads are absorbed by hash-skip, so a modest rewind is cheap; say which
  timestamp and why.
- **Delete reconciliation** — only when the developer asks for orphan cleanup
  and the worker has a delete handler (contract §10), never as part of a
  routine repair.
- **Code change + redeploy** — edit through `peliqan-sync` so the output stays
  one runnable single-file data-app, run
  `python ../../peliqan-sync/scripts/test_bookmarks.py <worker.py>` before deploying, then
  `update_data_app`, `run_data_app`, and re-read the logs to confirm the fix
  landed. Bump nothing else in the same deploy — one change per run makes the
  next log readable.

## Step 6 — Confirm the fix

After a sanctioned change, re-run and check three things: the bookmark moved
(`before -> after`), error/dead counts for that sync stopped growing, and the
specific record that triggered the report now has an `ok` link row and exists in
the target. A green run with an unchanged bookmark is not a confirmed fix.

## Step 7 — Report

- **Symptom** — what was reported, and the window it covers.
- **Evidence** — the log lines, row counts and code lines actually looked at.
- **Root cause** — one sentence, or an honest "unconfirmed, here's the leading
  theory and what would settle it".
- **Fix** — applied (with the confirmation from Step 6) or proposed (with the
  exact calls it needs and their blast radius).
- **Follow-ups** — anything noticed on the way that isn't this incident: an
  outdated `FRAMEWORK_VERSION`, a sync still disabled, a missing
  `references/systems/<system>.md` checklist row, a `TEST_LIMIT` left in place.

For an incident worth recording, use `create_project_note` to keep the write-up
with the account.

## Notes

- A system with no `references/systems/<system>.md` file yet means its timestamp
  format, comparator behaviour, id shapes and failure modes are unverified —
  treat any diagnosis touching them as unconfirmed and raise the checklist as a
  build-time question for `peliqan-sync` rather than guessing.
- If the Peliqan MCP isn't connected, say so and stop: this skill diagnoses from
  the worker's real code, runs and tables, and guessing from a pasted symptom
  alone produces confident wrong answers. Reading a pasted log is fine as a
  starting point — just label the conclusions as provisional until the account
  can be checked.
