# Dashboards

Dashboards on your Peliqan warehouse, deployed as a data app. Rebuild a report from any BI tool, start from scratch, or build on tables you already have. Claude sets up the data model the dashboard needs and verifies every number on real records before it builds anything on top of it.

| | |
|---|---|
| **Build skill** | [`peliqan-dashboard`](../../skills/peliqan-dashboard) |
| **Audit** | [`peliqan-audit`](../../skills/peliqan-audit) → `references/dashboard.md` |
| **Support** | [`peliqan-support`](../../skills/peliqan-support) → `references/dashboard.md` |

**On this page**

1. [What it is](#1-what-it-is)
2. [When to use it](#2-when-to-use-it)
3. [How it works](#3-how-it-works)
4. [Using the skills](#4-using-the-skills)

---

## 1. What it is

A dashboard is a Peliqan data app (Streamlit by default) that reads from one place: a **consumer layer** in your warehouse. Behind that layer sits a data model that's as simple as the dashboard allows:

| Situation | Data model |
|---|---|
| One clean source, a few simple KPIs, one consumer | **Light:** a single consumer view (`dm_<domain>`) on the source tables, holding the business rules. |
| Several sources, real business rules, or several consumers (dashboard, API, exports) | **Full medallion:** Bronze → Silver → Gold → consumer layer, shown below. |

If your warehouse already has a layered model, the dashboard follows its conventions. A light model grows into the full one when a second source or consumer arrives.

<p align="center">
  <img src="images/medallion-layers.svg" width="900" alt="The full model: sources are loaded by connectors into Bronze (raw, append-only), cleaned per source in Silver, combined in Gold where all business rules live, and exposed as a passthrough in the dm_ consumer layer. The dashboard data app reads only from dm_. A wrong number is traced back one layer at a time.">
</p>

| Layer | Job | Think of it as |
|---|---|---|
| **Bronze** | Raw data exactly as the source sends it. Append-only, never transformed. | Ingredients delivered |
| **Silver** | One cleaned, deduplicated, typed table per source. No joins, no business rules. | Washed and chopped |
| **Gold** | Sources combined, and **every business rule lives here and only here**: what counts as revenue, how an amount is derived, how a status code becomes a label. | Cooked to the recipe |
| **`dm_<domain>`** | A passthrough of Gold, shaped for its consumers (`fct_` / `dim_` tables). No new logic. | Plated |

Every dashboard follows these principles, whichever model it uses:

| Principle | What it means for you |
|---|---|
| **One place for every rule** | A formula exists once. Change it there and every dashboard on top follows. |
| **The dashboard reads the consumer layer only** | Display logic in the app, business logic in the warehouse, never mixed. |
| **Verified, not assumed** | A query that runs isn't done. Each number is checked on a real record against the ground truth, and the checks are kept. |
| **Parity before polish** | When replacing a report, its own formulas decide what's correct, even where they look unconventional. |
| **Same look, not just same numbers** | When replacing a report, visual types, colours and hierarchies are replicated, not swapped for "close enough". |
| **Two documents** | A technical reference for whoever maintains it, and a plain-language one for whoever signs off on the assumptions. |

---

## 2. When to use it

| Starting point | Ground truth | Typical example |
|---|---|---|
| **Replace an existing report** | The report's own formulas, field bindings and rendered look | Move a Power BI, Tableau, Looker, Qlik or Excel report onto your Peliqan warehouse, with matching numbers |
| **A new dashboard** | The business rules you confirm | A KPI dashboard for a new domain, with the reporting layers it needs |
| **On tables you already have** | The existing tables, plus rules you confirm for anything new | A dashboard on top of an existing `dm_` layer, query table or sync output |

When something else is the better choice:

- **A quick one-off chart or export.** Query the table directly.
- **Writing data back to an app.** That's a [sync](../syncs/README.md), not a dashboard.

### Before / after

You have a sales report in a BI tool and want it as a dashboard on your Peliqan warehouse.

**Without the skill:** someone rewrites the measures in SQL from memory of what they *should* be, the totals are 3% off, and nobody can say which of twenty formulas is responsible.

**With the skill:**

> Rebuild the "Sales overview" page of this report as a dashboard.

Claude sets up the data model, catalogs every visual on that page, translates each formula literally, checks it on one real record against the report, and only then builds the dashboard. Every check is kept in a `CHECK` schema, so "how do we know this is right?" always has an answer.

---

## 3. How it works

<p align="center">
  <img src="images/build-flow.svg" width="900" alt="Build flow: 1 set up the data model the dashboard needs, 2 catalog every visual in the confirmed scope, 3 translate each formula literally into SQL in one place, 4 verify on one real record (kept in the CHECK schema), with a loop back to translate on a mismatch, then after your confirmation 5 build the dashboard on the consumer layer and 6 document it. Ground truth is the existing report's formulas, bindings and screenshots, or the rules you confirm.">
</p>

1. **Data model first.** Claude inspects what's in your warehouse and sets up the light or full model, following the naming you already use.
2. **Catalog the scope.** For a report you're replacing, you confirm which report or page. Claude records every visual's type, fields and styling, and checks that the data behind it exists. From scratch, Claude asks which KPIs and visuals you want and how each is defined.
3. **Translate literally.** Each formula becomes SQL in the business-logic layer, with its sign conventions, filters and scopes intact, even when two related measures look inconsistent. That inconsistency may be intentional. From scratch, each definition is written down and confirmed by you first.
4. **Verify on one real record.** Claude picks a record you can check, hand-computes the expected value and compares it with the SQL output, field by field. A mismatch goes back to step 3.
5. **Build** the dashboard on the consumer layer. This happens only after you confirm the numbers are verified.
6. **Document** in two versions: technical (SQL, field mappings, formula comparisons) and plain language (no code).

After go-live, **freshness** and **load time** are checked as their own passes. A green pipeline doesn't guarantee every row is current, and a correct dashboard can still be slow.

---

## 4. Using the skills

### What you need

- A Peliqan account with the **source data** in the warehouse (loaded by connectors, or written by a sync).
- When replacing a report: the **report file** (e.g. a PBIX), its **formulas**, and **screenshots** of the rendered pages. Partial access helps too: a few pasted formulas are enough to verify the visuals that use them.
- **Claude** with the Peliqan skills installed and the Peliqan MCP connected. See [Installation](../../README.md#installation).

### Build: `peliqan-dashboard`

> Rebuild this Power BI report as a dashboard.

> Build a sales dashboard on our order tables.

> Set up reporting layers for our project data, with a dashboard on top.

Claude previews the stages, then checks in at fixed points: the scope, whether a number is confirmed, and when to move from verifying to building. It also asks before assuming a title or a logo.

### Audit: `peliqan-audit`

> Check our sales dashboard before we switch off the old report.

Claude checks four things and gives you the same verdict, scorecard and fix list as for any audit:
- **Data model:** whether it fits the need, has one place per rule, and whether the dashboard reads only the consumer layer.
- **Correctness:** against the source report or the agreed rules.
- **Presentation:** visual types, number formatting and column names.
- **Health:** data freshness and load time.

### Support: `peliqan-support`

> The dashboard numbers don't match the old report anymore.

Claude first works out whether the problem is **dashboard-side or warehouse-side**, and whether the data is **stale** (stopped updating) or **wrong** (current but different). It then follows lineage down the layers, or isolates one record, to find the layer where the value first diverges. If the cause is stale data, it stops at the diagnosis and never triggers a resync itself.

### Safety rules built into the skills

- **The ground truth wins.** Claude doesn't "fix" a source formula that looks unconventional; it asks.
- **Business rules never go into the dashboard script**, not even as a quick fix.
- **Verification queries aren't deleted** without your confirmation.
- **No resyncs, no publishing to other tools.** Documentation is handed to you as files; pushing it to Notion or elsewhere is a separate request.
