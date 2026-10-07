---
name: peliqan-sync
description: "Builds and extends Peliqan Reverse-ETL sync workers between two business systems (verified: Shopify ⇄ Odoo; others through a system checklist), as ONE single-file data app on the Peliqan data warehouse. Use when someone wants to scaffold a worker for a system pair or add one sync (orders, stock, customers, products, fulfilment, refunds) to an existing worker, reading the source from its API or from its Peliqan pipeline table in the warehouse: 'build a sync between our webshop and our ERP', 'add an order sync to Odoo', 'push stock from the ERP to the webshop', 'connect Shopify to Odoo', '/peliqan-sync'. Also used to apply fixes that peliqan-audit or peliqan-support route here, and to upgrade a worker's framework."
---

# Peliqan Sync

Generates the code for Peliqan warehouse-side sync workers, following the
pattern of the live Shopify⇄Odoo worker. One worker per system pair runs every
sync between those two systems through `process_all()`; each sync is a trio of
functions on a shared framework (link table + bookmarks + idempotency + error
containment).

**Output shape is fixed: ONE runnable data-app script.** A Peliqan data app is a
single file with no cross-app import, so the framework is embedded in every
worker and deployed with `create_data_app` / `update_data_app`. Never split a
worker into modules, never introduce a bundler, a repo layout or a build step,
and never tell the dev to edit anything other than the app. (Running one worker
across many clients from a module tree with a bundler is a valid but *different*
product, out of scope for this skill.)

## First: read the contract and the pair's system references

Before emitting any code, read **`references/framework-contract.md`**. It is the
single source of truth for the helper API, the link-table schema, the 6-step
per-record contract, the bookmark rules and the transport conventions, and
**`assets/worker_template.py`** implements it. Both workflows below must satisfy
it.

The contract is deliberately **system-agnostic**. Everything system-specific
(timestamp field/format/granularity, comparator control, id shapes, how a
functional error hides in a 200, implicit filters, permission failure modes)
lives in **`references/systems/<system>.md`**: read the two files matching the
worker's pair (e.g. `shopify.md` + `odoo.md`). For a system with no file yet
(SAP, Salesforce, ...), create one from `references/systems/_checklist.md`
together with the dev. Never guess the answers; an unanswered checklist row is
a build-time question.

**Where a sync reads and writes.** By default a sync reads the source system's
API and writes the target system's API. Two variations:
- **The warehouse as the source:** when the source already lands in the
  warehouse through a Peliqan pipeline and the dev wants to read that table,
  use `dwh_drain` and read `references/systems/peliqan-dwh.md` together with
  the system's own file (pipeline lag, the build-time probe).
- **The warehouse as the target:** never for a new sync unless the dev
  explicitly asks for it; then follow contract §7a. Don't propose it yourself.

The framework is **versioned** (`FRAMEWORK_VERSION`, now 6). When adding a sync
to a worker with an older version, upgrade its framework block in place first
(contract §11).

## Route to one of two workflows

Check the live account first (`list_data_apps`, filter names on `sync|worker`):
no worker for the pair = scaffold; a worker exists = add a sync to it. Only if
that is still ambiguous, ask the single question "scaffolding a new worker, or
adding a sync to an existing one?" and proceed.

- **Scaffolding a worker for a system pair**
  → read and follow **`references/worker-build.md`**.
  Output: a runnable, sync-*empty* worker (the shared framework only).

- **Adding one sync** (orders, stock, customers, fulfilment, refunds, …) to an
  existing worker → read and follow **`references/sync-build.md`**.
  Output: a trio of functions + a `SYNC_*` constant + one registry entry,
  inserted into the current worker script.

A dev typically builds the worker once, then runs the sync workflow many times.
When the dev asks for "the sync" in one go ("set up the sync between X and Y"),
ask ONE multi-select question (which syncs) plus ONE safety question
(`TEST_LIMIT` and `SYNCS_ENABLED` for the first run) and build worker + syncs in
a single pass.

## Assets & scripts

- `assets/worker_template.py`: the sync-agnostic framework (v6), placeholdered
  for the system pair. The worker workflow starts here.
- `assets/sync_examples/product_syncs.py`: the three product-sync trios from the
  live worker:
  - sync 1: SYSTEM_A → SYSTEM_B, create/update
  - sync 2: SYSTEM_A → SYSTEM_B, parent dependency + seed-once (orphan-freeze)
  - sync 3: SYSTEM_B → SYSTEM_A, GraphQL writeback, write_date drain
- `scripts/test_bookmarks.py`: pure offline test of the bookmark rules
  (equal-timestamp truncation). Run it on every worker before deploying:
  `python scripts/test_bookmarks.py <worker.py>`. It exec's four pure helpers
  out of the worker (`sort_by_updated_at`, `advance_bookmark`,
  `bookmark_with_overlap`, `simulate_bookmark_run`), so those four stay in every
  worker, with the template's signatures.
- `assets/sync_examples/dwh_and_audit.py`: sync 1 reading a pipeline table
  instead of the API, plus an `audit_<sync>` function (missing / drift /
  orphans) for the opt-in audit (contract §12).
- `scripts/test_dwh_and_audit.py`: fake-platform test (DuckDB as the
  warehouse) of `dwh_drain` and the audit. Run it when either changes:
  `python scripts/test_dwh_and_audit.py <worker.py>` (needs `duckdb`).

## Ground rules (every build)

**A run is a write.** Never run a worker "to see what happens" against a live
target; verify with `TEST_LIMIT`, a sandbox copy, or by reading the link table
and the run log. Scheduling the worker and setting `TEST_LIMIT = 0` are the
dev's call: do not do either.

**Seed the test data before trusting a green run.** Every pair needs a small
seed script (a separate data app, never the worker) that creates what the syncs
need: stock on the linked products, one paid test order, a customer with
tags/note/address. Bare dev data hides field gaps: a one-line order with no
discount, no shipping cost and no deviating tax exercises none of those
mappings, so those fields stay unbuildable *and* untestable until realistic
shapes exist.

**A sandbox is a copy of the app, not a branch.** Copy the worker into a second
data app with its **own `PAIR`** (own link table, run log, views), a `TEST_LIMIT`
and the syncs off in `SYNCS_ENABLED`. The trap: a copy on the *same* connections
with an *empty* link table sees the whole catalogue as new and duplicates it
into the live target. So seed its link rows once from the production pair
(aborting the run if seeding fails) and copy the production bookmarks into its
state. Isolation lives in the link data, bookmarks and run history, not in the
target systems.

**Keep a trail.** `get_data_app` before editing; bump `WORKER_VERSION` and add a
dated changelog line at the top of the script with every deploy; after every
`create_data_app` / `update_data_app`, verify the returned script against what
was tested (worker-build.md, step 6).

**Nothing is deleted** unless the dev asks for it explicitly. The one exception
is the throwaway probe app from worker-build.md, step 2.

## Scope honesty

Adding a sync is code generation (~3 functions), not a config one-liner. The
value is that every sync inherits idempotency, hash-skip, error rows, replay and
bookmarks from the framework, not that syncs become trivial. Say so. And list
the v1 decisions taken for the dev to review (taxes, draft vs confirm,
single-variant, single-location, line ownership) in the hand-over instead of
leaving them in code comments only.
