---
name: peliqan-sync-audit
description: "Audits a deployed Peliqan sync worker that looks healthy — before go-live, after a change, or as a periodic check — against the sync framework contract, and returns a pass/warn/fail scorecard with evidence and a ranked fix list. Checks framework version, bookmark rules (>= drain), catalog-registered link tables, hash coverage, the 6-step per-record path, data-loss guards, leftover test settings, and runtime health from the run log and link table (error/dead counts, stuck bookmarks, duplicates). Use when someone asks to 'audit the sync', 'review our worker', 'is this sync production-ready', 'validate the Shopify-Odoo worker', 'health check on the syncs', 'can we go live', or '/peliqan-sync-audit'. Read-only: it never deploys, runs, rewinds or replays. For something already broken, use peliqan-sync-support; to apply fixes, peliqan-sync."
---

# Peliqan Sync Audit

Checks a **live** sync worker that nobody has reported as broken yet. The worker
is a single data-app built by the `peliqan-sync` skill: one file per system
pair, all syncs driven from `process_all()`, on a shared framework (link table +
bookmarks + hash idempotency + error containment).

The yardstick is the framework contract. Read
`../peliqan-sync/references/framework-contract.md` and the `SKILL.md` of
`peliqan-sync` (its "Production learnings" and "Keep the scaffold lean"
sections supersede the contract where they differ) before scoring anything,
plus `../peliqan-sync/references/systems/<system>.md` for both systems of the
pair.

Audit vs. support: support starts from a symptom ("orders don't arrive") and
finds its cause. Audit starts from nothing and looks for the problems that have
not surfaced yet. If the audit turns up an active incident, say so and hand it
to `peliqan-sync-support`.

## Ground rules

- **Read-only, no exceptions.** List, read and query only. Never
  `run_data_app`, `update_data_app`, `set_bookmark`, `replay_source`,
  `reconcile_deletes`, or any write to the warehouse, source or target. A run
  is a write.
- **Local offline checks are fine.** Saving the worker's script locally and
  running `py_compile` and `../peliqan-sync/scripts/test_bookmarks.py` on it
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
`MAX_ATTEMPTS`, `MULTI_STORE`.

## Step 2 — Code against the contract

| # | Check | Pass when | Severity if not |
|---|---|---|---|
| C1 | Framework version | `FRAMEWORK_VERSION` equals the template's (`"4"`) | **fail** below 4 (strict `>` loses records), else warn |
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
| C12 | Multi-store scoping | Under `MULTI_STORE = True`, every `find_*` and `insert_link_row` passes `store_id`/`company_id` | **fail** (duplicates) |
| C13 | Run summary | Every run-summary tuple has the same arity, including the disabled-sync branch | **fail** (crashed a live run) |
| C14 | Bookmark test | `python ../peliqan-sync/scripts/test_bookmarks.py <worker.py>` passes; the four pure helpers are present | **fail** |
| C15 | Compiles | `py_compile` clean | **fail** |
| C16 | Traceability | `WORKER_VERSION` and a dated changelog at the top | warn |

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
- an active incident (R2, R3, R5 failing) → `peliqan-sync-support`.

Close with the open questions (unanswered system checklist rows, syncs whose
off-switch nobody could explain). Never apply a fix from this skill.

## Notes

- If the Peliqan MCP isn't connected, say so and stop. An audit of a pasted
  script alone can cover Step 2 only, so label it a code review, not an audit.
- An older hand-built worker (`link_tables.link_table` / `sync_runs`) predates
  the contract. Score it the same way; most of Step 2 will fail, and the fix is
  a framework upgrade, not a list of patches.
