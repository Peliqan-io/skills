---
name: peliqan-support
description: "Triages anything broken in a Peliqan account — a sync worker that stopped or duplicates, a failed pipeline run, a data app that crashed, an API endpoint returning errors, a table that went stale or empty, a dashboard that errors or whose numbers drifted from Power BI, connections that stopped or load wrong data (one, or a health check of all of them across the account and its sub-accounts) — and comes back with an evidence-backed root cause plus a concrete fix. Reads runs, logs, lineage and the sync framework's state tables through the Peliqan MCP. Use whenever someone reports a breakage or asks why something failed: 'the sync is broken', 'orders stopped arriving in the ERP', 'stuck bookmark', 'dead letter rows', 'records are syncing twice', 'the pipeline failed last night', 'why is this table empty', 'the data app is erroring', 'nothing has updated since Tuesday', 'the data is stale', 'the dashboard numbers don't match Power BI', 'the gold table is stale', 'the dashboard is erroring', 'are all our connections running', 'the balances in our app are wrong', '/peliqan-support' — including when they only paste an error or a run log. Read-only by default; any rewind, replay, rerun or redeploy needs explicit go-ahead. For building or changing something, use the build skill (peliqan-sync for syncs, peliqan-dashboard for dashboards)."
---

# Peliqan Support

Takes a reported breakage in a Peliqan account, finds out what actually
happened, and writes it up so the fix is obvious. Works for every kind of
object in the account. Domain-specific diagnosis lives in `references/`:

| Failing object | Read |
|---|---|
| A sync worker (a data app for a system pair, syncs driven from `process_all`) | `references/sync.md` |
| A dashboard or one of its medallion layers (Bronze/Silver/Gold/`dm_*`) | `references/dashboard.md` |
| Connections and the data they load, or a health check of all of them (the account or its sub-accounts) | `references/connections.md` |
| Anything else (pipelines, other data apps, API endpoints, tables) | The steps below |

Paths inside a reference file are relative to that file.

## Ground rules

- **Diagnose read-only.** Listing, reading logs and querying tables are always
  fine. Anything that creates, updates, runs, deletes or deploys (`create_*`,
  `update_*`, `delete_*`, `run_data_app`, `publish_data_app`, a bookmark rewind,
  a replay, DML) needs the user's explicit go-ahead first, because each one
  moves data in a live account.
- **Never write into a source or target system** to paper over a gap.
- **Evidence over narrative.** Every root cause is backed by a log line, a row
  count or a line of code. No evidence → say the diagnosis is unconfirmed and
  name what would settle it.
- **A skip is not a failure.** `no change in hash -> skip` in a sync log, or a
  pipeline that legitimately found no new rows, is the system working.
- **One incident, one report.** Other things noticed on the way go in a
  separate follow-ups list.
- If the Peliqan MCP isn't connected, say so and stop. A pasted log is a fine
  starting point, but label conclusions as provisional until the account can
  be checked.

## Step 1 — Pin the symptom

Turn the report into something checkable: which account or sub-account, which
object (connection, pipeline, data app, query table, API endpoint), which time
window. If the report is vague, find the concrete failure in the logs yourself
before asking questions. Ask only when the account or object is genuinely
ambiguous. Orient with `list_sub_accounts`, `list_connections`,
`list_data_apps`, `list_api_endpoints`, `list_databases` / `list_schemas` /
`list_tables`.

If the object is a sync worker, continue in `references/sync.md`; if it is a
dashboard or a medallion layer, in `references/dashboard.md`. Use the steps below only for the account-level
context around it: is the upstream connection healthy, did the source system change, when did it last work.

If the report is about connections or the data they load (nothing updates, a
balance is wrong, records are missing) and names no single object, or the
user asks for help without a specific breakage, offer two ways: **one
incident** (continue here) or **a connection health check** of the account
or its sub-accounts (`references/connections.md`, from Step 1). The same check
is what `peliqan-connection-health` runs.

## Step 2 — Read the evidence

Newest failure first, always compared against the last successful run:

- **Pipelines:** `get_connection_pipeline_runs`, then `get_pipeline_run_logs`.
- **Data apps:** `get_data_app_runs`, `get_data_app_run_logs`, `get_data_app`,
  `get_data_app_context`, `get_data_app_state`.
- **API endpoints:** `get_api_endpoint_logs`.
- **Tables:** `get_table`, `get_table_runs`, `get_table_lineage`,
  `get_table_data`. Lineage tells "this table is broken" apart from "its
  upstream is broken", which is what most stale-data reports turn on.

## Step 3 — Land on a cause

One root cause, backed by evidence. Distinguish clearly between:

- broken in Peliqan (pipeline, data app, query, endpoint);
- broken in the source or target system (credentials, API change, permissions);
- a legitimately empty result;
- a configuration value someone changed.

## Step 4 — Report

In this order:

- **Impact** — what's affected and since when, in business terms.
- **Evidence** — the runs, logs, counts and code lines actually looked at.
- **Root cause** — one sentence, or the labelled leading theory.
- **Fix** — the concrete change, the exact calls or code edit it needs, and
  its blast radius. Apply it only after a yes. Code changes to a sync worker go
  through `peliqan-sync`.
- **Prevention** — only if there is something real that would have caught
  this earlier.
- **Follow-ups** — other things noticed on the way.

For an incident worth keeping, offer to attach the write-up to the account with
`create_project_note`.
