# Workflow: Build a Worker

Goal: a runnable, **sync-empty** worker (framework v5) for one system pair.
It pins down two things for life (the two systems and the warehouse objects);
syncs are then added with `sync-build.md`.

## Platform fact that shapes this

Peliqan data apps are **single files**; there is no runtime import of shared code
across apps (a local bundler can flatten a multi-file app at deploy time, but
that needs CI outside the MCP flow). So the framework is **embedded and
versioned**: the skill owns the canonical copy (`FRAMEWORK_VERSION`), and stale
workers are upgraded in place (contract §11).

## Inputs to gather

1. **System pair** + the account's **exact connection names** (from
   `list_connections`; e.g. `'Odoo V2'` / `'Shopify V2'`, not the template's
   defaults). A wrong name crashes the app before the first sync.
2. **Account label**: header only (`{ACCOUNT_LABEL}`), plus today's date for the
   changelog line (`{DATE}`).
3. **Build-time options** (constants near the top of the template):
   - `MAX_ATTEMPTS`: failures before a row is marked `dead`.
   - `TEST_LIMIT`: cap per sync per run while testing (`None`/`0` = all).
   - `SYNCS_ENABLED`: which syncs run on the first live runs.
   - Cadence: if latency-sensitive syncs (stock, fulfilment) need to run more
     often than eventual-consistency ones (payouts, gift cards), note it; it may
     mean more than one scheduled worker or a per-sync gate later.
   - Several stores or companies on one side? Then multi-store scoping is a
     build-time decision (contract §8); it is not in the baseline.
4. **`PAIR`** (e.g. `"shopify_odoo"`, `"klaviyo_odoo"`): every warehouse object
   name derives from it, so workers for different pairs never collide. To reuse
   the original worker's rows instead of a fresh per-pair table, set
   `LINK_TABLE = "link_table"` / `RUNS_TABLE = "sync_runs"`.

## Steps

The order of operations that took a 5-sync worker from zero to two green live
runs in one session (2026-09-02). Every step is here because skipping it cost a
run or a redeploy that day.

1. **Inspect the account before asking the dev anything.** `list_connections`
   (exact names), `list_data_apps` (existing worker?), `list_schemas` (database
   id), and a 3-row `get_table_data` on the source tables in the DWH (paid test
   orders? customers? what a target product looks like). This answers half the
   sync spec and shows which test data exists. Read `framework-contract.md` and
   the two system references for the pair (`references/systems/<A>.md`,
   `<B>.md`); if one does not exist, create it from `_checklist.md` with the dev.
2. **Probe the target with a throwaway data app BEFORE building a sync that
   depends on a module or field.** For Odoo: one `search_read` on
   `ir.module.module` (`stock`, `sale`, `sale_management`, `account`) and one on
   each field you intend to read. Live, `stock` was *uninstalled* on the target
   so `product.product.qty_available` did not exist: the stock sync was built,
   then switched off. A 10-line probe would have said so first. Delete the probe
   app afterwards (`delete_data_app`).
3. **Register the link schema ONCE with the MCP `create_schema` tool** (database
   id from `list_schemas`) before the first run. `pq.refresh_schema` requires
   `schema_name` and 404s (`ERROR_SCHEMA_DOES_NOT_EXIST`) on a schema that is
   not in the catalog yet; a connection-level refresh does not exist. Once the
   schema is registered, `ensure_schema` registers and verifies its own tables.
   Without this step the first runs abort (correctly) on the schema guard.
4. **Fill in the template.** Take `assets/worker_template.py`, substitute
   `{ACCOUNT_LABEL}` and `{DATE}`, the connection names, `PAIR` and the
   build-time constants. Leave the SYNC INSERTION POINT, the empty
   `SYNC_REGISTRY` and `process_all` intact.
5. **Run the offline checks locally**: `py_compile`, `pyflakes` (ignore only the
   undefined `pq`/`st`) and `python scripts/test_bookmarks.py <worker.py>`. Once
   syncs exist, add a **fake-platform smoke test**: exec the worker with a stub
   `pq` (state dict, `dbconnect`, `connect`, `refresh_schema`), a stub `st` (log
   collector) and fake connections that answer the exact response shapes
   (`{"status":"success","detail":{"data":...}}` for Shopify,
   `{"status":"success","detail":{"result":...}}` for Odoo). Run it three
   times: run 1 creates, run 2 must write NOTHING (only `no change in hash ->
   skip` / `already linked`), run 3 propagates exactly one changed record. On
   the live build it caught two bugs before the first live write.
6. **Deploy with `create_data_app` and verify against the returned
   `raw_script`** (large results land as a file: parse it, don't guess its
   structure). The API strips the trailing newline: compare with
   `.rstrip("\n")`, then treat as byte-identical. Same after every
   `update_data_app` (wholesale replace; the script is pasted inline, so keep
   the worker lean). Name the app `"<A>-<B> data sync - Worker"`.
7. **First live run with `run_data_app(mode='shell')`.** The MCP call times out
   after 60 s while the run keeps going: on a timeout do NOT re-run, read
   `get_data_app_runs` + `get_data_app_run_logs`. (A double-triggered run showed
   up live; only the schema guard made it harmless.) The first run's log shows
   either a clean schema check or one `refresh_schema` line; an abort means the
   account needs attention, not the syncs.
8. **Second run = idempotence proof.** Expect the `>=` boundary re-reads to
   settle as `n x no change in hash -> skip` / `already linked`, bookmarks
   moving in the Bookmarks block, no duplicate writes. Only then hand over.
   Scheduling and `TEST_LIMIT = 0` are the dev's call.

A sync-empty worker is safe to schedule immediately: it does nothing until a
sync is registered.

## Keep the scaffold lean

A sync-empty scaffold ships the whole helper API unused: that is the contract,
not bloat. These parts are NOT contract and go in only when needed:

- **Custom fields only when the pair declares extension fields.** Then add a
  `CUSTOM_FIELDS` list next to the config and an `ensure_custom_fields()` call
  in `process_all` that creates them in the target idempotently, with ONE batch
  existence check and a per-field fallback. The *list* is pair-specific; the
  *mechanism* is framework. If the user lacks the permission, creation fails
  with only a warning while the run stays green: check the fields exist after
  the first run.
- **Multi-store scoping, delete reconciliation**: contract §8 and §10.
- **No one-caller indirections**: inline them.

And two that a lean review will flag but that STAY, because they prevent data
loss:

- **The 3× retry around the link-row insert.** A target write that succeeded
  with no link row is the silent-duplicate mode this whole framework exists to
  prevent; the retry plus the error-row fallback are the last line.
- **The monotonic `_next_link_id` guard.** A colliding bigint PK drops a link
  row silently. `time.time_ns()` alone is shorter and not safe against clock
  adjustments.

`simulate_bookmark_run` exists only for the test. Keep it (14 lines, pure)
because `scripts/test_bookmarks.py` exec's it.

## Peliqan platform gotchas (any pair)

- `update_data_app` replaces the script **wholesale**: always send the full
  file, then verify it as in step 6 before trusting the deploy.
- A Peliqan API call that errors (transient 500) may still have EXECUTED the
  action: two "failed" run attempts had in fact run and advanced bookmarks.
  After an API error, check run history / state before retrying anything
  non-idempotent.
- Bookmarks live in **app state** (`pq.get_state`/`set_state`), survive script
  updates, and can be edited via the MCP state tools. A bookmark rewind + one
  run is the standard recovery for records a drain missed (hash-skip makes the
  re-scan cheap). State writes shallow-merge at the top level: always write the
  full `bookmarks` object, never a single key.
- Large MCP tool results land as files; parse them, don't guess their structure.

## A different system pair (e.g. SAP ⇄ Salesforce)

As above, plus a mechanical rename of the two system tokens: `PAIR` (names the
link table / run log / views), the variables + `pq.connect(...)` names, the
`shopify_*`/`odoo_*` columns in `ensure_schema` / `insert_link_row` / `_SIDES` /
views, the transport helpers (new read/write for the new systems; keep `is_ok`
and make it catch how each system hides an error in a 200), and each source's
bookmark field/format. Those answers come from `references/systems/<system>.md`
(one per side); fill in missing ones via `_checklist.md` before generating
transport code. Contract §6 applies regardless of pair: `>=` drains, or
`bookmark_with_overlap` where the comparator is opaque.

## Do NOT

- Bake any single sync's logic into the framework.
- Reintroduce a `system_a`/`system_b` indirection.
- Change the helper argument names the sync trios depend on except as part of a
  full, consistent different-pair rename (that is the contract).
