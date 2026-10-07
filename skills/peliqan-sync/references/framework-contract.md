# Framework Contract (v5)

Single source of truth for the API a sync trio may rely on. The worker-builder
emits a framework that satisfies this; the sync-builder emits syncs that call
only these. If this file and the code disagree, `assets/worker_template.py` wins,
and the disagreement is a bug to fix in the same change.

**Framework is versioned.** The worker carries `FRAMEWORK_VERSION = "5"`. Data
apps are single files (no cross-app import), so the framework is embedded and
the skill owns the canonical copy. When it changes, bump the version here and in
the template; the sync-builder upgrades a stale worker's framework block in place
(§11). This is what prevents the drift seen between the first two hand-built
workers.

## Version history

**v5 (production learnings folded in).** Everything learned running the
Shopify ⇄ Odoo worker live, which used to sit in SKILL.md as amendments, is now
in the template: the per-run link cache (`prefetch_links` with write-through),
aggregated skips (`note_skip` / `write_skips`), `SYNCS_ENABLED`, a run summary
with durations and a Bookmarks block, `WORKER_VERSION` plus a changelog,
`ensure_schema` probing once, `is_ok` rejecting a functional error inside a 200,
`shopify_drain` and `find_or_create`. Dropped from the baseline because no live
worker used them: multi-store scoping (`MULTI_STORE`, `store_id`, `company_id`),
`reconcile_deletes` and `shopify_list_incremental`. Generate one only when asked
(§8, §10).

**v4 (data-loss fix): incremental drains MUST use `>=`, never strict `>`.**
Verified on a live account (2026-07-15): source timestamps have **second
granularity**, so several records routinely share one timestamp (bulk imports,
batch edits). With a strict `>` filter, any run that stops mid-cluster
(`TEST_LIMIT`, a crash, a page cap) sets the bookmark to that shared second and
the NEXT run skips the remaining records at that same second **permanently**:
no link row, no error row, no dead-letter entry, and their children orphan-freeze
forever. (Live incident: 3 products silently lost this way; recovered only by a
manual bookmark rewind.) The rules are in §6.

**v3 (breaking fix): warehouse objects must be CATALOG-REGISTERED.** Verified on
a live account: `dbconn.insert`/`dbconn.fetch` only work on tables registered in
Peliqan's catalog. Raw DDL via `dbconn.execute` creates the Postgres object but
does NOT register it: insert/fetch then 404 (`ERROR_TABLE_DOES_NOT_EXIST`)
while the DDL "succeeded", producing v2's failure mode: a green-looking run that
writes to the target with **no link rows** (duplicates on every run) and still
advances bookmarks. `ensure_schema` therefore runs the idempotent DDL, probes the
tables once with a real fetch, calls `pq.refresh_schema(connection_name=dw_name,
schema_name=LINK_SCHEMA)` if they are unregistered, re-probes only if that ran,
and **raises** if they are still unregistered; `process_all` then runs no syncs.
`refresh_schema` only works on a schema the catalog already knows, so the schema
is registered once with the MCP `create_schema` tool before the first run.
Two traps to never reintroduce: do not create the link table with
`dbconn.write()` (write-created tables are pipeline-flagged and `dbconn.insert`
is rejected on them), and do not treat a failed link write as a warning-only
event when the whole table is unusable.

## 1. Naming conventions

- **sync_name**: `<sourcesys>_<sourceobj>_to_<targetsys>_<targetobj>`.
- **fns**: `fieldmapping_*`, `process_<one record>`, `process_<sync>` (the loop).
- **Two systems fixed at creation, named concretely everywhere** (`shopify_*` /
  `odoo_*`). No `system_a`/`system_b` indirection: a different pair is a
  generation-time rename, not a runtime abstraction.

## 2. Warehouse objects, **per worker**, created by it (`ensure_schema`, first thing in `process_all`)

Each worker (system pair) owns its **own** link table, run log and views, named
after its pair via top-of-file constants (`LINK_SCHEMA`, `PAIR`, `LINK_TABLE =
f"link_{PAIR}"`, `RUNS_TABLE = f"runs_{PAIR}"`). This is what lets several
workers for different pairs coexist: a shared table with fixed `shopify_id`/
`odoo_id` columns can't serve a Klaviyo⇄Odoo worker. All the helper queries build
the table name from `_LT = f"{LINK_SCHEMA}.{LINK_TABLE}"`, so a sync never names
the table itself.

`{LINK_SCHEMA}.{LINK_TABLE}` (e.g. `link_tables.link_shopify_odoo`), append-only,
shared by all syncs **in this worker**:

| column | meaning |
| --- | --- |
| `id` (bigint PK) | unique per row, `_next_link_id()` (monotonic guard) |
| `sync_name`, `action` (insert/update), `status` | see below |
| `attempt` (int) | failure count; **set by the framework**, not the sync |
| `shopify_id` / `odoo_id` | the two identities (text), named for this pair |
| `shopify_source_hash` / `odoo_source_hash` | `stable_hash` of owned fields, per direction |
| `shopify_source_json` / `odoo_source_json` | full source record, for replay |
| `error_detail`, `timestamp` | error text (error rows only); ISO `...Z` |

`status` values: `ok`, `source_error`, `target_error`, and **`dead`** (poison:
reached `MAX_ATTEMPTS`, stops retrying). Effective link = latest `ok` per
(sync_name, id). Append-only: every upsert is a new row.

Also created (per worker): `{LINK_SCHEMA}.{RUNS_TABLE}` (run log) and pair-suffixed
views `v_link_shopify_latest_{PAIR}`, `v_link_odoo_latest_{PAIR}`,
`v_dead_letter_{PAIR}`, `v_run_summary_{PAIR}`.

*Legacy:* the first hand-built worker used `link_tables.link_table`. To reuse that
data, set `LINK_TABLE = "link_table"` and `RUNS_TABLE = "sync_runs"` instead of
the per-pair names. A v4 worker's table keeps its `store_id`/`company_id`
columns after an upgrade; v5 leaves them empty.

## 3. Helper API (a sync may call ONLY these)

Config/const: `FRAMEWORK_VERSION`, `WORKER_VERSION`, `TEST_LIMIT`, `MAX_ATTEMPTS`,
`SYNCS_ENABLED`, `_limit_reached(processed)`.

State/bookmark: `get_bookmark`, `set_bookmark`, `sort_by_updated_at(records, ts_field=)`,
`advance_bookmark(hw, ts)`, `bookmark_with_overlap(bookmark, fmt=, seconds=)`
(for comparators we don't control), `simulate_bookmark_run(records, current, limit, ts_field=)`.
The four pure ones are exec'd by `scripts/test_bookmarks.py`: keep them, with
these signatures, in every worker.

Hash: `stable_hash(dict) -> str`: canonical JSON md5 over the **owned/mapped
fields**. Use this; never concatenate `str(a)+str(b)`.

Link table:
- `insert_link_row(sync_name, action, status, shopify_id=, odoo_id=,`
  `shopify_source_hash=, odoo_source_hash=, shopify_source_json=,`
  `odoo_source_json=, error_detail=) -> bool`. Attempt counting and promotion
  to `dead` happen **inside** this call. Three retries plus an error-row
  fallback guard the insert; an `ok` row is written through to the link cache.
- `find_target(sync_name, shopify_id) -> (odoo_id, shopify_source_hash)`
- `find_link_by_odoo(sync_name, odoo_id) -> (shopify_id, odoo_source_hash)`
- `prefetch_links(sync_name, side, keys, chunk=500)`, `side` = `"shopify"` or
  `"odoo"`: loads the latest `ok` link for these keys in one query per chunk.
  Call it **once per page** of source records, for this sync **and** for every
  parent sync the loop resolves. Misses are cached as `(None, None)`; a failed
  query caches nothing, so `find_*` falls back to per-key lookups. *(Without
  it, one live run did 280+ queries for zero writes.)*

Logging and ops:
- `note_skip(sync_name, reason="no change in hash -> skip")`: count a skip
  instead of logging a line per record. `process_all` calls `write_skips()`
  after every sync (also when it failed), one line per sync and reason. Keep
  the default text: it is the idempotence proof in the log.
- `record_run(sync_name, started_at, counts, status=, detail=)`: called by
  `process_all`; a sync just returns its counts dict.
- `replay_source(sync_name, process_one, statuses=, include_dead=, limit=)`:
  re-drives error/dead rows from stored source JSON; `process_one(sync_name, record)`.
  This is how a failed record is retried once its cause is fixed: the normal
  run has already moved its bookmark past it.
- `ensure_schema()`: idempotent bootstrap of everything in §2 (see v3 above).

Transport (in the worker), all raising on a response that is not ok:
- `is_ok(result)`: `status == "success"` **and** no `detail.error` (Odoo fault
  in a 200) and no `detail.errors` (Shopify top-level errors, e.g.
  ACCESS_DENIED with `data: null`).
- Shopify: `gid_to_numeric`, `shopify_graphql`, `graphql_user_errors`,
  `shopify_drain(query, root, bookmark, extra_filter=, page_size=, max_pages=)`.
- Odoo: `odoo_object_add/update/search`, `odoo_search_read_incremental`,
  `extract_new_id`, `find_or_create(model, domain, record, cache, key, strict=)`.

## 4. The 6 steps (every single-record function)

1. **Validate source** → `insert_link_row(..., "source_error", ...)`, return.
2. **Lookup link** (`find_target` / `find_link_by_odoo`) → target id + last hash → insert vs update.
3. **Map + hash** (`fieldmapping_*` → `(shape, stable_hash(owned))`). Equal hash → `note_skip`, return `"skip"`. Shape may be one record or richer (header + lines, multiple models).
4. **Writeback**: one target record per call; fan out / branch / multi-model as the domain needs.
5. **Handle response**: `is_ok`; for GraphQL also `graphql_user_errors` (functional error on a 200). Attempt/`dead` promotion is automatic in step 6.
6. **Append link row**: `ok` with hash on success; else an error status with `error_detail` and no hash.

Return `"ok" | "skip" | "error"` from the single-record fn so the loop can
count. Log a line only for records that are written or fail, never for skips.

## 5. The loop (`process_<sync>`)

- `bookmark = get_bookmark(sync_name) or <epoch in this source's format>`.
- Read the changed set with a `>=` drain, `sort_by_updated_at(..., ts_field=<source field>)`
  when the drain does not already return time order.
- `prefetch_links` per page (this sync and its parents).
- Loop with `_limit_reached`; per-record try/except that records a row and continues; `advance_bookmark` only over reached records; orphan-freeze on a parent dep.
- **Return `{"processed": n, "errors": e, "skipped": s}`** so `process_all` logs the run.
- Register in `SYNC_REGISTRY`: `{"name": SYNC_X, "run": process_x, "replay": <optional>}`, in dependency order (parents first, Shopify→Odoo before Odoo→Shopify).

`process_all` skips a sync that `SYNCS_ENABLED` switches off, lists the on and
off syncs in one caption, and ends with a run summary: per sync the status,
duration and processed/errors/skipped, then a **Bookmarks** block with
`before -> after` or `unchanged`. A bookmark that does not move means "nothing
new" OR "frozen on an orphan", and nothing else in the log tells those apart.
Every summary tuple has the same arity, including the disabled branch: a
shorter one crashed a live run with a `ValueError` that read as "Worker aborted
unexpectedly".

## 6. Bookmark rules

Each source has its own timestamp field/format (see the system references,
`references/systems/`). **Never compare across sources.** Advance only over the
contiguous processed prefix. Orphan-freeze: freeze at the first child whose
parent isn't linked yet.

**Comparator (v4): `>=`, never strict `>`.** Timestamps have second granularity
and clusters of equal timestamps are normal; a truncated run + strict `>` loses
the rest of the cluster permanently. Self-written filters use `>=`;
unknown-comparator paths (a connector `list(bookmark=)`) get
`bookmark_with_overlap(bookmark)`. Boundary re-reads are absorbed by hash-skip.
This applies to ANY source with second-granularity change timestamps (Shopify
`updatedAt`, Odoo `write_date`, Salesforce `SystemModstamp`, SAP `CHANGEDAT`...);
a new system reference must state the granularity and whether the comparator is
under our control. `scripts/test_bookmarks.py` asserts these rules; run it
offline before deploying a worker or a new sync.

**A truncated unsorted read is a loss too.** A drain that returns records in
cursor order (not time order) and stops at a page cap would let the bookmark
jump past records it never read. `shopify_drain` therefore raises at
`max_pages` instead of returning a partial list.

## 7. Transport conventions

One record per mutation/write call; a single-row search may return a dict
(normalise to list); paginate reads with the source cursor; write the `>=`
filter yourself (`shopify_drain`, `odoo_search_read_incremental`) rather than
relying on a connector `list(bookmark=)`. A drain **raises** on a response that
is not ok, so a permission problem or an API fault surfaces as a failed sync
with an unchanged bookmark (it self-heals once fixed), never as "0 records".
`find_or_create` never falls through to a create after a failed search.
**System-specific transport quirks (query syntax, id shapes, functional-error
detection on 200s, permission failure modes, implicit filters) live in
`references/systems/<system>.md`**: the sync-builder reads the two files for the
worker's pair; this contract stays system-agnostic.

## 8. Multi-store / multi-company (not in the baseline)

No live worker needed it, so v5 does not ship it. When a pair really has
several Shopify stores or Odoo companies, decide it at build time (a single
`shopify_id ↔ odoo_id` mapping breaks the moment the same product exists in two
stores): add `store_id`/`company_id` columns, pass them to `insert_link_row`,
and scope `find_*` and `prefetch_links` on them, in the worker and with a
version bump. Say what it costs: every helper must stay consistent with it at
every later change.

## 9. Reliability summary (all generic; every sync inherits)

Two-layer idempotency (hash-skip + append-only link) · attempt counter → `dead`
poison handling · `replay_source` from stored snapshots · per-run link cache
with write-through · loud source errors · run log, run summary and monitor
views · nothing aborts the run except an unusable link table.

## 10. Known limitations / open items

- **Single-variant assumption** (`variants[0]`): a multi-variant matcher is planned.
- **Delete semantics** (unlink vs archive) are a per-sync decision and not in
  the baseline. When a sync needs it: after a full drain, diff the `ok` links
  against the live source ids and hand each orphan to a handler that archives
  or unlinks and writes a delete link row. Generate it only when asked.
- **Ingest-layer dedupe** (duplicate webhook events landing in the DWH) is
  separate from writeback dedupe and depends on confirming webhook-relay mode:
  a build-time question, not yet a helper.

## 11. Upgrading a worker's framework

When `FRAMEWORK_VERSION` here is newer than a worker's, the sync-builder should
replace everything from the header down to the `>>> SYNC INSERTION POINT <<<`
marker with the current template's framework, preserve the syncs and
`SYNC_REGISTRY` below the marker, and confirm the diff before `update_data_app`.

From v4 to v5, also check the syncs themselves:
- A sync that calls `shopify_list_incremental` moves to `shopify_drain`, or
  keeps a local copy of the old helper below the marker.
- A sync that passes `store_id`/`company_id` means the worker used multi-store:
  stop and add the §8 block before upgrading.
- A sync that calls `reconcile_deletes` keeps its own copy below the marker.
- Replace per-record `st.text("no change in hash -> skip")` with `note_skip`,
  and add `prefetch_links` per page. Neither is required for correctness
  except the write-through, which the framework does on its own.
- Carry over the worker's connection names, `PAIR`, `TEST_LIMIT` and
  `SYNCS_ENABLED`, bump `WORKER_VERSION` and add a changelog line.
