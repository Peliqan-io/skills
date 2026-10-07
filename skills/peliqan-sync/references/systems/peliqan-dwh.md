# Source channel reference: Peliqan pipeline table (DWH as source)

Not a system — a **read path**. Some accounts sync a source via its Peliqan
pipeline into the data warehouse and want the worker to read *that table*
instead of calling the source API (fewer API calls, no rate limits, the data
is already flat and queryable, one place to look). This file answers the
`_checklist.md` questions for that read path. **Read it together with the
system's own file** (`shopify.md`, `odoo.md`, …): the system file still owns
ids, ownership, writeback and functional-error detection. Only the drain
changes. The warehouse is not a sync target by default; writing to it only
happens on an explicit request (`framework-contract.md` §7a).

Verified: the drain mechanics (`dwh_drain`, offset paging on `dbconn.fetch`)
run on the same `dbconn.fetch` path the link table uses. **Unverified and
per-table** — probe at build time, never assume: the timestamp column's type
and format, whether pipeline tables carry a load timestamp, how nested
objects are split into child tables, and what happens to deleted source
records. An unanswered row is a build-time question for the developer.

## Checklist answers

| question | answer |
| --- | --- |
| Change-timestamp field + format | the source's own change timestamp as the pipeline stored it (Shopify `updated_at`, Odoo `write_date`, …). **Probe 3 rows**: `dbconn.fetch` may return it as text (`2026-07-03T11:03:37Z`, `2026-07-03 11:03:37`) or as a timestamp — the bookmark must use the *same* representation. Bookmark namespace: `<sync_name>` as always, never shared with an API bookmark for the same system |
| Timestamp granularity | seconds (inherited from the source) → the v4 `>=` rule applies in full |
| Comparator under our control? | **yes** — `dwh_drain` writes `ts_field >= bookmark`. Still pass `bookmark_with_overlap(bookmark, fmt=<table format>, seconds=<one pipeline interval>)` because of **pipeline lag** (below) |
| Record id shape | whatever the pipeline stored — usually the source's primary id (Shopify numeric id, Odoo integer). Probe it; link-table columns keep the system's id convention (`gid_to_numeric` still applies if the table stores gids) |
| Incremental read mechanism | `dwh_drain(table, ts_field, bookmark, id_field=, where=, page_size=)`: `ORDER BY ts_field, id_field`, `LIMIT/OFFSET` until an empty page. Deterministic because of the id tiebreak |
| How a functional error looks on a 200 | a failed query is raised by `dbconn.fetch` → `dwh_drain` **raises** a `source_error`, so the sync reports FAILED and its bookmark stays put (never the swallowing `fetch()` helper here). A **stale pipeline** is the DWH's silent failure: the query succeeds and returns nothing new — read the `max(ts_field)` freshness line |
| Writeback mechanism | n/a here: this file covers the warehouse as a source. Writes go to the target API per the target's system file. A warehouse table as the target is an explicit-request exception: `framework-contract.md` §7a |
| Permission / access failure modes | the table not catalog-registered (`ERROR_TABLE_DOES_NOT_EXIST` on fetch — the pipeline's own schema is registered by the pipeline, so this means a wrong schema/table name); the pipeline disabled or failing (table stops advancing — `get_connection_pipeline_runs` shows it) |
| Implicit server-side filters | none in the DWH — **the pipeline's own filters are**: a pipeline that only syncs active products, the last N months of orders, or one store/company, defines what the sync can ever see. Ask which filters the pipeline runs with |
| Data-model impedance | pipelines **flatten**: nested objects become JSON/text columns or **child tables** (`orders` + `orders_line_items`, `products` + `variants`). A sync that needs the children fetches them per page by parent id. Timestamps on child tables are usually the *child's* — drive the drain from the parent and read children as a lookup, never bookmark on both |
| Delete semantics options | depends on the pipeline: some keep deleted source rows forever, some remove them on a full refresh. Decides whether `reconcile_deletes` / the `orphan` audit can see deletes at all — a build-time question |

## Pipeline lag — the one new data-loss mode

With an API drain the source is live. With a pipeline table the source is as
fresh as the **last pipeline run**. The trap: pipeline run N loads records up
to source timestamp T; a record edited at T−5 min that the source API returned
late (eventual consistency, a long-running export) lands in run N+1. If the
worker ran in between and parked its bookmark at T, that record is **behind
the bookmark forever** — no link row, no error row, nothing in the dead
letter. Same shape as the v4 equal-second loss, only wider.

Rule: drain against `bookmark_with_overlap(bookmark, fmt=<table format>,
seconds=<one pipeline interval, e.g. 3600 for an hourly pipeline>)`. The
re-read records settle as `no change in hash -> skip`; the designed cost is a
pipeline interval's worth of no-ops per run. State the interval in the sync's
header comment. If the pipeline table carries its own **load timestamp**
column (probe for it), bookmarking on *that* instead removes the lag problem
entirely — it is monotonic with the pipeline — and the overlap can drop to the
usual 1 s.

## Build-time probe (do this before writing the loop)

```
get_table_data(<schema>.<table>, limit=3)   -- MCP, or:
SELECT <id_field>, <ts_field>, pg_typeof(<ts_field>) FROM <schema>.<table>
ORDER BY <ts_field> DESC LIMIT 3;
```

Record in the sync's header comment: table name, `ts_field` + its exact
format, `id_field`, child tables used, pipeline interval + the overlap chosen,
the pipeline's own filters. Those five lines are what `peliqan-support`
reads first when "nothing arrives" and the DWH is the source.

## The echo (not new, but closer)

A→B writes B through its API. B's pipeline later loads that write with a fresh
`write_date`; a B→A sync drained from B's pipeline table sees a "change". This
is the same echo an API drain sees. It stays harmless for the same reason: the
B→A hash covers only B-owned fields, so the echo settles as a hash-skip. If an
echo *does* write back, the ownership split is wrong — fix the hash, not the
drain.
