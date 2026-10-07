# Source reports: Power BI and other BI tools

What's specific to rebuilding an existing report. Power BI is covered in
detail; other tools are at the end. The general workflow in
`SKILL.md` and the traps in `formula_translation.md` still apply; this file
covers only how to get the ground truth out of Power BI.

## Confirm which page before building anything

A PBIX file commonly contains multiple pages, each a different report (a
sales overview, a finance page, a projects page). Don't assume which one the
user wants rebuilt just because a PBIX was shared: ask which page, unless
it's obvious (only one page has real content, or they named it). Building the
wrong page's visuals wastes significant effort and one question avoids it.

Once the page is confirmed, compare the **data** its visuals reference
against what's in the warehouse, not just the layout. A visual's field may
reference a table or column that doesn't exist yet, and that gap needs to
surface before committing to a build plan.

## Where the ground truth lives in a PBIX

- **`Report/Layout` JSON** (inside the PBIX archive): which fields each visual
  is bound to and what type of visual it is (card, slicer, matrix, gauge…).
- **The data model's DAX measures.** If the PBIX can't be read, ask the user
  to paste each measure from Power BI's Modeling / Measures view.
- **Friendly names vs. real columns.** Names shown in the Power BI model often
  differ from the actual column names in the source tables. Confirm each
  mapping explicitly; never match on similarity.

## Ask for a screenshot of the rendered page too

The layout JSON says *what fields* a visual uses and *what type* it is, but
not what the page looks like rendered: colours, conditional formatting,
whether a slicer is a dropdown or a list, which matrix rows are expanded by
default, or truncated card text that reveals a formula's real output.

A screenshot is also an independent check on field mapping: a slicer whose
values list is full of short codes is bound to an ID column, not a
description, even before the layout JSON confirms it. Treat the screenshot as
ground truth alongside the DAX, and re-check any visual whose rendered output
doesn't match what the layout JSON implied.

## Partial access still helps

No full PBIX? A handful of DAX measures pasted in chat, or screenshots of
specific visuals, are enough to verify the calculations those visuals depend
on. Verify what you can, and list the rest as assumptions.

## Other BI tools

The same three questions apply to any source tool. Answer them with its own
artefacts:

| Tool | Formulas | Visual bindings | Rendered look |
|---|---|---|---|
| Power BI | DAX measures | `Report/Layout` JSON | Screenshot |
| Tableau | Calculated fields (`.twb` XML) | Worksheet shelves | Screenshot |
| Looker | LookML measures and dimensions | Explore / dashboard definition | Screenshot |
| Qlik | Set-analysis expressions | Sheet object properties | Screenshot |
| Excel | Cell formulas, pivot settings | Pivot / chart source ranges | The workbook itself |

For a tool with no file you can read, ask the user to paste the formulas and
share screenshots, and mark anything not covered as an assumption.
