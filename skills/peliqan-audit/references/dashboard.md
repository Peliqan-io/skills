# Audit: dashboards

Checks a deployed dashboard and its data model that nobody has reported as
broken yet. The dashboard was built with the `peliqan-dashboard` skill: either a
full medallion model (Bronze → Silver → Gold → consumer layer `dm_<domain>`) or
a light one (a single consumer view on the source tables), and a dashboard app
that reads only from the consumer layer.

The yardstick is that skill. Read `../../peliqan-dashboard/SKILL.md` and
`../../peliqan-dashboard/references/medallion_architecture.md` before scoring
anything. Use `formula_translation.md`, `source_reports.md`, `dashboard_build_gotchas.md` and
`freshness_and_performance.md` from the same folder for the checks that cite
them.

## Step 1 — Inventory

`list_data_apps` (the dashboard app, usually named "… Dashboard"), then
`get_data_app` and save the script locally. `list_schemas` / `list_tables` for
the layer schemas (Bronze, Silver, Gold or Core, `dm_*`, `CHECK`), and
`get_table` on each consumer-layer table for its query definition. Ask whether
a source report exists (a PBIX or other BI file, its formulas, or screenshots): with one, correctness
can be scored against it; without one, score only structure and hygiene and
say so.

## Step 2 — Architecture

| # | Check | Pass when | Severity if not |
|---|---|---|---|
| A1 | Model fits the need | Full medallion when there are several sources, real business rules or several consumers; a single consumer view is fine for one clean source. Follows the account's own naming | warn |
| A2 | Bronze is raw | (Full model) No transformations in Bronze | warn |
| A3 | Silver is per source | (Full model) One cleaned table per source entity; no cross-source joins, no business rules | **fail** |
| A4 | One place per rule | Every rule (revenue vs. cost, derived amounts, status labels) is defined once: in Gold, or in the single consumer view of a light model | **fail** |
| A5 | Consumer layer is a passthrough | (Full model) Every `dm_*` table is `SELECT … FROM GOLD.x` or light reshaping; none references `SILVER.*`, unions sources or applies a rule | **fail** |
| A6 | Dashboard reads the consumer layer only | The script queries `dm_*` tables only, never Gold or Silver | **fail** |

## Step 3 — Correctness

Only with a ground truth: the source report's formulas or screenshots, or the
business rules the user confirmed at build time. Without one: `n/a`, and list
the assumptions the build made instead.

| # | Check | Pass when | Severity if not |
|---|---|---|---|
| K1 | Verification queries | A `CHECK` schema holds the verification queries for each KPI | warn |
| K2 | One record, end to end | For one real record, every displayed field matches the source report | **fail** |
| K3 | Field bindings | Slicers, filters and matrix groupings use the exact field the source report binds, not a friendlier substitute (`formula_translation.md` §9) | **fail** |
| K4 | Known traps | Per-unit vs. per-total, sign conventions, padded codes, single-value picks over ambiguous values (`formula_translation.md`) | **fail** per trap hit |

## Step 4 — Presentation

| # | Check | Pass when | Severity if not |
|---|---|---|---|
| P1 | Visual types | Each visual uses the same metaphor as the source (a matrix stays a hierarchy, a gauge stays a gauge) | warn |
| P2 | Number formatting | Rounding and separators match the source report, no raw floats | warn |
| P3 | Column names | Display names match the source report or sibling dashboards | warn |
| P4 | Filters don't leak | A filter doesn't display a column it isn't meant to | warn |

## Step 5 — Freshness and load time

| # | Check | Pass when | Severity if not |
|---|---|---|---|
| F1 | Pipelines | Connector runs feeding Bronze complete on schedule (`get_connection_pipeline_runs`) | **fail** on failing runs |
| F2 | Row freshness | One sampled record's last-modified timestamp is consistent with the latest successful run (`freshness_and_performance.md`) | warn |
| F3 | Load time | No full-table pulls filtered afterwards in app code; independent loads run concurrently | warn |

## Report

Use the format in `../SKILL.md`. Route code and layer fixes to
`peliqan-dashboard`; route a failing pipeline or a stale table to
`peliqan-support`. Never apply a fix from here, and never touch the `CHECK`
schema.
