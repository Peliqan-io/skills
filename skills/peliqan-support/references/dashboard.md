# Support: dashboards

Diagnoses a dashboard built with the `peliqan-dashboard` skill that is erroring,
showing stale data, or showing numbers that no longer match the report it
replaced. Data flows Bronze → Silver → Gold → consumer layer (`dm_<domain>`),
and the dashboard app reads only from the consumer layer.

That skill is the contract for what each layer and measure is *supposed* to
do. Read `../../peliqan-dashboard/SKILL.md` and, depending on the symptom,
`medallion_architecture.md`, `dax_comparison.md` or
`freshness_and_performance.md` from `../../peliqan-dashboard/references/`.
Use them as the reference for expected behaviour only: you don't rebuild
layers, rewrite measures or redeploy the dashboard. The fix goes through
`peliqan-dashboard` after the user's go-ahead.

## Step 1 — Classify the symptom

Most dashboard reports come down to two distinctions. Settle them first:

| Question | How to tell |
|---|---|
| **Dashboard-side or warehouse-side?** | Dashboard-side: the app run logs show an exception, or the app renders wrong from correct `dm_*` data. Warehouse-side: the `dm_*` table itself returns the wrong or old values. |
| **Stale or wrong?** | Stale: the values were right and stopped updating. An upstream pipeline stopped, a refresh order broke, or incremental sync missed a record. Wrong: the values are current but don't match the source report. A transform, binding or measure disagrees with the PBIX. |

## Step 2 — Evidence per class

- **App error:** `get_data_app_runs` and `get_data_app_run_logs` for the first
  failing run, compared with the last good one; `get_data_app` for the script.
  Common causes: a renamed or dropped `dm_*` column, a query timing out, a
  broken logo or asset (`dashboard_build_gotchas.md`).
- **Stale:** walk `get_table_lineage` from the `dm_*` table down to Bronze and
  find the first layer whose data stopped moving (`get_table_runs`,
  `get_connection_pipeline_runs`). If every run is green, isolate one disputed
  record and compare its last-modified timestamp against the connector's run
  history (`freshness_and_performance.md`). **Stop at diagnosis:** never
  trigger a resync.
- **Wrong:** isolate one record the user can check in the source report and
  compare every field, layer by layer (Silver → Gold → `dm_*`), to find the
  layer where the value first diverges. Check the existing `CHECK` schema
  queries for that KPI first: they record what was verified at build time.
  Then match the divergence against `dax_comparison.md`.
- **Slow:** check for full-table pulls filtered in app code and for
  sequential independent loads (`freshness_and_performance.md`).

## Step 3 — Report

Use the format in `../SKILL.md`. Name the layer that owns the fault and
whether it is stale or wrong. A wrong value whose fix changes a business rule
goes to Gold, never to the consumer layer or the dashboard script.
