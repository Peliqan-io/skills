---
name: peliqan-dashboard
description: "Build a dashboard on a Peliqan data warehouse, deployed as a data app (Streamlit by default), with every number verified on real records before it's built. Covers three starting points: rebuilding an existing report from any BI tool (Power BI, Tableau, Looker, Qlik, Excel) with its own formulas as the ground truth; a new dashboard from scratch with the business rules confirmed by the user; or a dashboard on tables that already exist. Sets up the data model the dashboard needs, from a single consumer view to a full Bronze/Silver/Gold medallion architecture. Use whenever someone wants to build, rebuild, migrate or port a dashboard or report, set up reporting layers for a data domain, compare dashboard numbers against an existing report, PBIX file or DAX measures, or verify that a dashboard's numbers are right — also when a .pbix, .twb or Excel report is shared with a request to build or check a dashboard, and on '/peliqan-dashboard'. To audit a finished dashboard use peliqan-audit; to diagnose a broken or stale one use peliqan-support."
---

# Peliqan Dashboard

Builds a dashboard on a Peliqan warehouse and proves its numbers are right.
The core discipline: **a query that runs is not a number that's correct.**
Every calculated value is checked against a ground truth on real records
before anything is built on top of it. When a source report exists, its own
formulas are the ground truth, even where they look unconventional. When none
exists, the business rules the user confirms are.

## First: which starting point?

Ask, or infer from what the user shared, and confirm before step 1:

| Starting point | Ground truth | Read |
|---|---|---|
| **Rebuild an existing report** (Power BI, Tableau, Looker, Qlik, Excel…) | The source report's formulas, field bindings and rendered look | `references/source_reports.md`, `references/formula_translation.md`, `references/visual_replication.md` |
| **New dashboard from scratch** | Business rules the user confirms, or standard definitions stated as assumptions | — |
| **Dashboard on tables that already exist** | The existing tables' definitions, plus rules the user confirms for anything new | — |

A user may not mention an existing report they have. If the request sounds
like "the same as what we have in X", ask for it: partial ground truth (a few
formulas, a few screenshots) beats none.

## Let the user know what's ahead

Before starting, give a short, plain-language preview of the stages and the
points where you'll check in (which report or page, whether a number is
confirmed, when to move from verifying to building). For example:

> "I'll first check what data is there and set up the layers the dashboard
> needs, then go through your report (or ask what you want if there isn't
> one), verify every number on a real record before building anything, build
> the dashboard, and document it. I'll check in with you at a few points."

Don't list every step. Repeat a shorter version if the conversation resumes
after a long gap.

## The workflow

### 1. Choose the data model the dashboard needs

Inspect the account first (`list_schemas`, `list_tables`, a few rows of the
relevant tables). If a layered model already exists, follow its conventions
and schema names. Otherwise, scale the model to the need:

| Situation | Data model |
|---|---|
| One clean source, a few simple KPIs, one consumer | A single consumer view (`dm_<domain>`) on the source tables. Business rules go in that one view, and nowhere else. |
| Several sources, real business rules, or several consumers (dashboard + API + exports) | Full medallion: **Bronze** (raw) → **Silver** (cleaned per source) → **Gold** (combined, all business rules) → **consumer layer** (`dm_<domain>`, passthrough). |

The rule that holds in both: **every business rule exists in exactly one
place, and the dashboard reads only from the consumer layer.** If the model
grows (a second source, a second consumer), move the rules into Gold rather
than duplicating them.

Some teams call the business-logic layer "Core" and the consumer layer
"Gold". Follow the schema names already in the warehouse over any document.
See `references/medallion_architecture.md` for the full rationale, a
kitchen analogy for non-technical readers, and a safe schema-rename procedure.

### 2. Catalog what the dashboard must show

- **Rebuilding a report:** confirm which report or page, then record every
  visual's type, the exact fields it binds (slicers and groupings included),
  and its styling. Check that the data behind each visual exists in the
  warehouse before committing to a plan. Ask for screenshots of the rendered
  report, not just the file. See `references/source_reports.md` and
  `references/visual_replication.md`.
- **From scratch or on existing tables:** ask what the dashboard is for,
  which KPIs and visuals the user wants, and how each KPI is defined. Don't
  guess visuals or definitions.

### 3. Pin down each formula

- **Rebuilding a report:** get the literal formula for each measure and
  translate it into SQL **literally**: its sign conventions, filters and
  scopes, even when two related measures look inconsistent. That
  inconsistency may be intentional. Map every field to its real warehouse
  column, and check per-unit vs. per-total by querying multi-quantity rows,
  never from the name. `references/formula_translation.md` lists the traps.
- **From scratch:** write each definition down in plain language, get the
  user's confirmation, then implement it. A standard definition you chose is
  an assumption until confirmed.

Formulas go in the business-logic layer (Gold, or the single consumer view
in the light model), never in the dashboard script.

### 4. Verify every number on real data

A translation isn't done because it runs. For each calculated field:

1. Pick real rows where the inputs vary meaningfully (quantity > 1, a
   non-zero secondary amount, a less common category).
2. Hand-compute what the ground truth produces for those rows.
3. Compare with the SQL output. A mismatch means the SQL is wrong, however
   cleanly it runs.

With a source report, compare against the numbers it displays for one
specific record. That checks the whole chain end to end.

**Debug one unknown at a time, on one record.** Aggregates mix formula
errors and scope errors, and they can cancel out. Pick one record the user
can check independently and compare every field. Move to aggregates only
once each part is confirmed in isolation.

**Keep verification queries** in a dedicated `CHECK` schema: they answer
"how do we know this is right?" later. At natural pauses, mention how many
have accumulated and ask whether to clean up. Never delete one unasked.

**Say explicitly when something checks out:** which record, what was
compared, and the matching values side by side. "Checked and correct" must
be distinguishable from "not checked yet".

**Treat leaving verification as a checkpoint.** Once a KPI is confirmed, ask
whether to continue to the next one, or, when all are done, whether to move
on to building.

### 5. Build the dashboard on the consumer layer

The dashboard is a Peliqan data app (Streamlit unless the user wants
otherwise). It queries **only** the consumer layer, never Gold or Silver.

- **Check every consumer-layer object, not just the script.** A `dm_*` table
  that reaches into Silver, unions sources or applies a rule breaks the model
  as much as the script would. Move that logic into Gold.
- **Same visual metaphor as the source.** A matrix with subtotals stays a
  hierarchy, a gauge stays a gauge. From scratch: build what the user asked
  for. See `references/visual_replication.md`.
- **Reuse before inventing.** For tricky UI problems (logos, headers, custom
  widgets), read a sibling dashboard in the same account first.
- **Name** the app with "Dashboard" at the end ("Sales Pipeline Dashboard").
  **Ask** for the title (don't take it from an unrelated textbox, don't
  translate it) and whether a logo is wanted, and from where.
- **Finish with consistency checks:** filters don't leak columns, number
  formatting matches the source or the user's convention, column names are
  consistent with sibling dashboards.

See `references/dashboard_build_gotchas.md` (logo handling, the consistency
checks) and `references/streamlit_patterns.md` (multi-select filters with
clear-all, SVG gauges, stable colour scales, the indented matrix table).

### 6. Distinguish "wrong" from "different on purpose"

Two measures in the same report can deliberately use different scopes (a
margin gauge on a whitelist of categories, a pie chart over all of them).
Before "fixing" one to match a sibling, check whether the source formula
specifies the difference. If in doubt, ask for that measure's formula.

### 7. Document twice

- **A technical reference** (SQL, field mappings, formula comparisons) for
  whoever maintains it.
- **A plain-language document** (no code, analogies where they help) for
  whoever signs off on the assumptions.

Never one document for both. Prepare them as files and hand them over. Don't
publish them to Notion, a wiki or any other tool unless that's asked for
separately.

### 8. Rule out stale data before trusting a formula fix

When a verified dashboard diverges from its source, treat freshness as its
own hypothesis. A green pipeline doesn't mean every row is current:
incremental sync can miss updates on specific records. Isolate one disputed
record and compare its last-modified timestamp with the connector's run
history. **Stop at diagnosis.** Don't propose or trigger a resync; lay out
the evidence and let the user decide. See
`references/freshness_and_performance.md`.

### 9. Check load time as its own pass

Once the numbers are right, check for the two common causes of a slow
dashboard: full-table pulls filtered in app code, and independent loads run
one after another. Present fixes as a checklist for the user to approve, and
afterwards confirm the numbers didn't change. See
`references/freshness_and_performance.md`.

## A note on iteration

This isn't linear. A formula that looked right in step 3 may need reverting
when step 4 or a newly shared formula shows otherwise (this has happened: a
"fix" to a margin calculation was reverted once the literal DAX showed the
original was right). Treat each new piece of ground truth as authoritative
over your own earlier reasoning, and say "I was wrong, here's why".
